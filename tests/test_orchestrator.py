from pathlib import Path
import base64
import json
from typing import List

from tests.fixtures.setor_teste.dados import StoreTeste
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.tools.catalog import execute_tool
from sentury.harness.artefato_do_turno import estrategia_visual, normalizar_passo_de_artefato, recusar_artefato_sem_lastro, tirar_html_repetido


class ScriptedPlanner:
    """Devolve, em ordem, cada resposta crua passada em `scripted`: simula a
    LLM planner sem depender de uma chamada de rede real."""

    def __init__(self, scripted: List[str]):
        self.scripted = list(scripted)
        self.last_model = "scripted-planner"

    async def complete(self, messages):
        return self.scripted.pop(0)


class EchoResponder:
    last_model = "scripted-responder"

    async def complete(self, messages):
        return json.dumps({"action": "respond", "message": "Resumo final."})


class CapturePlanner:
    last_model = "capture-planner"

    def __init__(self, raw_response: str):
        self.raw_response = raw_response
        self.calls = []

    async def complete(self, messages, temperature=0.1, complexity=None, profile=None):
        self.calls.append({
            "temperature": temperature,
            "complexity": complexity,
            "profile": profile,
            "messages": messages,
        })
        return self.raw_response


class RoteiroPlanner(CapturePlanner):
    """Devolve uma resposta por chamada; repete a ultima quando acabam."""

    def __init__(self, respostas):
        super().__init__(respostas[-1])
        self._respostas = list(respostas)

    async def complete(self, messages, **kwargs):
        await super().complete(messages, **kwargs)
        return self._respostas.pop(0) if len(self._respostas) > 1 else self._respostas[0]


class CaptureResponder:
    last_model = "capture-responder"

    def __init__(self, raw_response: str = "Resposta final."):
        self.raw_response = raw_response
        self.calls = []

    async def complete(self, messages, temperature=0.3, complexity=None, profile=None):
        self.calls.append({
            "temperature": temperature,
            "complexity": complexity,
            "profile": profile,
            "messages": messages,
        })
        return self.raw_response


class ContractPlanner:
    last_model = "contract-planner"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def complete(self, messages, temperature=0.1, complexity=None, profile=None):
        self.calls += 1
        return self.replies.pop(0)


class NativeCouncil:
    def __init__(self):
        self.calls = []

    async def analyze(self, user_message, tool_results):
        self.calls.append((user_message, tool_results))
        return {
            "perspectives": {
                "setor_teste": "CX prioriza reduzir atrito.",
                "operations": "Operacoes prioriza capacidade.",
                "finance": "Financeiro protege o investimento.",
                "commercial": "Comercial protege renovacoes.",
                "strategy": "Estrategia pede sequenciamento.",
            },
            "peer_reviews": ["Revisao 1"],
            "trade_offs": ["Velocidade versus custo."],
            "consensus_recommendation": "Atacar comunicacao e capacidade em paralelo.",
        }


class StubSubagentCoordinator:
    enabled = True

    def __init__(self):
        self.calls = []

    async def consultar(self, pedido, state, papeis=(), quantos=0, emit=None):
        self.calls.append((pedido, state.last_result_id))
        return {
            "requested": True,
            "requested_count": 2,
            "completed_count": 2,
            "results": [
                {"role": "evidence_analyst", "status": "completed", "summary": "Metrics checked."},
                {"role": "operations_critic", "status": "completed", "summary": "Risk checked."},
            ],
        }


def _tool_call(tool: str, **arguments) -> str:
    return json.dumps({"action": "tool_call", "tool": tool, "arguments": arguments})


def _respond(message: str) -> str:
    return json.dumps({"action": "respond", "message": message})


def _store() -> StoreTeste:
    return StoreTeste()


async def test_planner_repairs_missing_json_contract_once():
    planner = ContractPlanner([
        "I will reason about the request but omit the required JSON.",
        _tool_call("consultar_medida"),
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    plan = await orch._generate_plan(
        "analise o Medida geral",
        AnalysisState.new("contract", "u"),
        None,
        "",
        complexity="STANDARD",
    )

    assert plan == [{"tool": "consultar_medida", "arguments": {}}]
    assert planner.calls == 2
    assert orch.turno.contrato == "repaired"


async def test_llm_council_uses_native_engine_without_loading_skill_markdown(setor_teste):
    planner = ScriptedPlanner([])
    council = NativeCouncil()
    orch = SenturyOrchestrator(
        planner=planner,
        responder=EchoResponder(),
        store=_store(),
        council=council,
    )
    state = AnalysisState.new("council", "u")
    state.register_result("consultar_medida", {}, {"medida": -31.2, "volume": 5000}, 1)
    state.register_result("consultar_medida", {}, {"causas": ["backlog"]}, 1)

    result = await orch.handle_message(
        state,
        "[llm-council] faca um conselho para debater sobre o medida atual",
    )

    assert planner.scripted == []
    assert len(council.calls) == 1
    assert result["council"]["consensus_recommendation"]
    assert result["skill_activated"] == ["llm-council"]


async def test_saudacao_passa_pelo_mesmo_laco_que_qualquer_pedido():
    """Não há atalho por palavra de cumprimento: ele cobriria só as línguas da
    lista. Um "eae" chega ao modelo do turno como qualquer pedido."""
    planner = CapturePlanner(_respond("Oi! Como posso ajudar?"))
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("direct-chat-session", "u-direct")

    result = await orch.handle_message(state, "eae")

    assert planner.calls
    assert result["message"]
    assert "fast_path" not in result["telemetry"]


async def test_subagentes_sao_ferramenta_e_o_modelo_junta_os_pareceres(setor_teste):
    """O modelo chama `subagentes` depois de trazer o dado, lê os pareceres como
    resultado de ferramenta e escreve a resposta na mesma conversa: não há um
    segundo modelo reescrevendo."""
    planner = RoteiroPlanner([
        _tool_call("consultar_medida"),
        _tool_call("subagentes", pedido="revise o Medida geral", quantos=2),
        _respond("Resposta consolidada com os pareceres."),
    ])
    responder = CaptureResponder("o redator não devia ser chamado")
    coordinator = StubSubagentCoordinator()
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store(),
                               subagent_coordinator=coordinator)

    result = await orch.handle_message(AnalysisState.new("subagent-parent", "u-sub"),
                                       "use 2 subagentes para revisar o Medida geral")

    assert coordinator.calls and coordinator.calls[0][1] is not None, "o subagente vê o resultado verificado"
    assert result["subagents_beta"]["completed_count"] == 2
    assert result["message"] == "Resposta consolidada com os pareceres."
    assert "Metrics checked." in str(planner.calls[-1]["messages"])
    assert not responder.calls


def _tudo_que_foi(chamada):
    return "\n".join(str(m.get("content") or "") for m in chamada["messages"])


async def test_replanejar_manda_o_mesmo_sistema_da_primeira_volta():
    """O provedor só reaproveita o prefixo idêntico: o sistema não muda entre as voltas."""
    planner = CapturePlanner(json.dumps({"plan": []}))
    orch = SenturyOrchestrator(planner=planner, responder=CaptureResponder(), store=_store())
    state = AnalysisState.new("voltas", "u1")

    await orch._generate_plan("liste os arquivos da pasta", state, None, "")
    await orch._generate_plan("liste os arquivos da pasta", state, None, "", is_replanning=True)

    primeira, segunda = (c["messages"][0]["content"] for c in planner.calls[-2:])
    assert primeira == segunda
    assert "mode: deliberate" not in _tudo_que_foi(planner.calls[-1])


async def test_specialized_planner_modes_inject_the_right_operational_contract(setor_teste):
    planner = CapturePlanner(json.dumps({"plan": []}))
    orch = SenturyOrchestrator(planner=planner, responder=CaptureResponder(), store=_store())
    state = AnalysisState.new("mode-contracts", "u1")

    await orch._generate_plan(
        "organize as prioridades do Medida",
        state,
        None,
        "",
        planner_mode="action_plan",
    )
    action_prompt = _tudo_que_foi(planner.calls[-1])
    sistema_da_acao = planner.calls[-1]["messages"][0]["content"]

    await orch._generate_plan(
        "calcule em Python um indicador ponderado",
        state,
        None,
        "",
        planner_mode="deliberate",
    )
    outra_call = planner.calls[-1]

    # O modo muda com o pedido: vai no fim da conversa e o sistema fica igual.
    assert "mode:" not in sistema_da_acao
    assert sistema_da_acao == outra_call["messages"][0]["content"]
    assert "mode: action_plan" in action_prompt
    assert "criar_plano" in action_prompt and "plano-de-acao" in action_prompt
    assert "mode: deliberate" in _tudo_que_foi(outra_call)


async def test_planner_accepts_direct_skill_action_variant():
    planner = CapturePlanner(json.dumps({
        "action": "executar_skill",
        "skill": "ui-ux-design",
        "args": {"contexto": "dashboard executivo"},
    }))
    orch = SenturyOrchestrator(planner=planner, responder=CaptureResponder(), store=_store())
    state = AnalysisState.new("direct-skill", "u1")

    plan = await orch._generate_plan("aplique uma skill de design", state, None, "")

    assert plan == [{
        "tool": "executar_skill",
        "arguments": {"contexto": "dashboard executivo", "nome": "ui-ux-design"},
    }]


async def test_explicit_skill_tag_is_loaded_before_model_planning():
    planner = CapturePlanner(json.dumps({"plan": []}))
    orch = SenturyOrchestrator(planner=planner, responder=CaptureResponder(), store=_store())
    state = AnalysisState.new("explicit-skill", "u1")

    plan = await orch._generate_plan("[frontend-design] crie o html", state, None, "")

    assert plan == [{"tool": "executar_skill", "arguments": {"nome": "frontend-design"}}]
    assert planner.calls == []


async def test_natural_skill_is_chosen_by_model_from_index(setor_teste):
    planner = CapturePlanner(_tool_call("executar_skill", nome="consulta-medida"))
    orch = SenturyOrchestrator(planner=planner, responder=CaptureResponder(), store=_store())
    state = AnalysisState.new("natural-skill", "u1")

    plan = await orch._generate_plan("qual a causa-raiz da queda do Medida?", state, None, "")

    assert plan == [{"tool": "executar_skill", "arguments": {"nome": "consulta-medida"}}]
    assert len(planner.calls) == 1
    assert "consulta-medida" in planner.calls[0]["messages"][0]["content"]


async def test_skill_replanning_uses_registered_tools_without_forcing_python():
    planner = CapturePlanner(json.dumps({"plan": []}))
    orch = SenturyOrchestrator(planner=planner, responder=CaptureResponder(), store=_store())
    state = AnalysisState.new("skill-replan", "u1")
    state.history.append({"role": "system", "content": "[INSTRUÇÃO PROCEDURAL DE SKILL CARREGADA]\n\n# causa-raiz"})

    await orch._generate_plan("qual a causa-raiz da queda do Medida?", state, None, "", is_replanning=True)

    prompt = _tudo_que_foi(planner.calls[-1])
    assert "siga as etapas dela com as ferramentas registradas" in prompt
    assert "DEVE planejar a execução do código" not in prompt


async def test_replanejar_sem_skill_nao_inventa_skill_ativa():
    """O bloco dizia 'uma skill procedural foi carregada' em toda volta depois
    da primeira, com ou sem skill."""
    planner = CapturePlanner(json.dumps({"plan": []}))
    orch = SenturyOrchestrator(planner=planner, responder=CaptureResponder(), store=_store())
    await orch._generate_plan("liste a pasta", AnalysisState.new("sem-skill", "u1"), None, "", is_replanning=True)
    assert "SKILL PROCEDURAL" not in planner.calls[-1]["messages"][0]["content"]


async def test_a_chamada_que_responde_ve_o_resultado_da_ferramenta():
    """No passo unico esta chamada escreve a resposta final. O filtro antigo so
    deixava passar sistema com '[INSTRUÇÃO DO SISTEMA:', e o resultado da
    ferramenta, o anexo e o lembrete de repeticao ficavam de fora."""
    planner = CapturePlanner(json.dumps({"plan": []}))
    orch = SenturyOrchestrator(planner=planner, responder=CaptureResponder(), store=_store())
    state = AnalysisState.new("ve-resultado", "u1")
    state.history.append({"role": "user", "content": "o que tem na pasta?"})
    state.history.append({"role": "system", "content": 'RESULTADO DA FERRAMENTA "listar_arquivos": pyproject.toml, README.md'})
    state.history.append({"role": "system", "content": "ANEXO DA PESSOA: curriculo.pdf\nBackend Junior"})

    await orch._generate_plan("o que tem na pasta?", state, None, "", is_replanning=True)

    enviado = "\n".join(str(m["content"]) for m in planner.calls[-1]["messages"])
    assert "pyproject.toml" in enviado and "Backend Junior" in enviado


def test_html_with_unsupported_numeric_fact_is_rejected():
    orch = SenturyOrchestrator(
        planner=CapturePlanner(json.dumps({"plan": []})),
        responder=CaptureResponder(),
        store=_store(),
    )
    state = AnalysisState.new("html-grounding", "u1")
    state.results["resultado_001"] = {"summary": {"medida": -42.3, "pct_em_risco": 56.9}}
    state.last_result_id = "resultado_001"
    attachment = {
        "type": "html",
        "content_base64": base64.b64encode(
            b"<html><style>.x{width:87.5px}</style><body><strong>CSAT 4.2</strong></body></html>"
        ).decode("ascii"),
    }

    checked, message = recusar_artefato_sem_lastro(orch,
        state, attachment, "pronto", [], pre_turn_had_data=True
    )

    assert checked is None
    assert "sem respaldo" in message


def test_html_css_numbers_are_ignored_and_grounded_visible_fact_is_allowed():
    orch = SenturyOrchestrator(
        planner=CapturePlanner(json.dumps({"plan": []})),
        responder=CaptureResponder(),
        store=_store(),
    )
    state = AnalysisState.new("html-grounding-ok", "u1")
    state.results["resultado_001"] = {"summary": {"medida": -42.3, "pct_em_risco": 56.9}}
    state.last_result_id = "resultado_001"
    attachment = {
        "type": "html",
        "content_base64": base64.b64encode(
            b"<html><style>.x{width:87.5px}</style><body><strong>Medida -42.3</strong></body></html>"
        ).decode("ascii"),
    }

    checked, message = recusar_artefato_sem_lastro(orch,
        state, attachment, "pronto", [], pre_turn_had_data=True
    )

    assert checked is attachment
    assert message == "pronto"


async def test_pergunta_escolhida_pelo_modelo_nao_repete_depois_da_resposta(setor_teste):
    # A dúvida é semântica: é o planner que escolhe perguntar. O harness não
    # troca um plano por um questionário a partir da palavra "html".
    planner = CapturePlanner(json.dumps({
        "plan": [{
            "tool": "perguntar_usuario",
            "arguments": {"questions": [{
                "header": "Dados", "question": "Quais dados este material deve mostrar?",
                "options": [{"label": "Medida", "description": "Medida e lealdade"},
                            {"label": "Chamados", "description": "Operacao"}],
            }]},
        }],
    }))
    orch = SenturyOrchestrator(
        planner=planner,
        responder=CaptureResponder("Resposta final grounded."),
        store=_store(),
    )
    state = AnalysisState.new("ask-before-html", "u1")

    first = await orch.handle_message(state, "to querendo um html, faz algo ai")

    assert first["attachment"] is None
    assert first["clarification"] is not None
    assert first["harness"]["proposed_tool"] == "perguntar_usuario"
    assert not state.results

    orch.planner = CapturePlanner(json.dumps({
        "plan": [{"tool": "consultar_medida", "arguments": {}}],
    }))
    second = await orch.handle_message(
        state,
        "p: Quais dados este material deve mostrar?\nr: Medida e lealdade\n"
        "p: Quem vai usar esta entrega?\nr: Lideranca",
    )

    assert second.get("clarification") is None
    assert state.results


async def test_loop_guard_closes_duplicate_visual_step_as_skipped(setor_teste):
    # Com o laco ligado o planner e chamado de novo vendo o resultado; um
    # modelo de verdade encerra ali, e o duble faz o mesmo.
    planner = RoteiroPlanner([
        json.dumps({"plan": [
            {"tool": "consultar_medida", "arguments": {}},
            {"tool": "consultar_medida", "arguments": {}},
        ]}),
        json.dumps({"plan": []}),
    ])
    events = []
    orch = SenturyOrchestrator(
        planner=planner,
        responder=CaptureResponder("Analise concluida."),
        store=_store(),
    )
    state = AnalysisState.new("loop-guard", "u1")

    result = await orch.handle_message(state, "analise o Medida geral", progress_cb=events.append)

    assert result["telemetry"]["skipped_repeated_calls"] == 1
    assert len(state.results) == 1
    completed = [event for event in events if event.get("type") == "tool_complete"]
    assert {event.get("status") for event in completed} == {"ok", "skipped"}


async def test_planner_preso_no_mesmo_plano_para_por_nao_progresso(setor_teste, monkeypatch):
    from sentury.config import settings

    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    planner = CapturePlanner(json.dumps({"plan": [{"tool": "consultar_medida", "arguments": {}}]}))
    orch = SenturyOrchestrator(
        planner=planner,
        responder=CaptureResponder("Analise concluida."),
        store=_store(),
    )
    state = AnalysisState.new("planner-preso", "u1")

    result = await orch.handle_message(state, "analise o Medida geral")

    stats = result["harness"]["loop_stats"]
    assert stats["tool_calls"] == 1
    # uma volta que rodou + duas so de repeticao; nao o teto de voltas
    assert stats["loops"] <= 3
    # as voltas mais a chamada de fechamento, sem ferramenta, no mesmo modelo
    assert len(planner.calls) <= 4


def test_svg_helper_named_by_planner_is_safely_routed_through_python_sandbox():
    step = normalizar_passo_de_artefato(
        {
            "tool": "save_svg_diagram",
            "arguments": {
                "title": "Causa raiz",
                "boxes": [{"id": "A", "text": "Medida em queda", "level": 0}],
                "arrows": [],
            },
        },
        {"preferred_format": "svg", "layout_hint": "tree"},
    )

    assert step["tool"] == "executar_python"
    assert "save_svg_diagram" in step["arguments"]["codigo"]
    assert "layout='tree'" in step["arguments"]["codigo"]


def test_html_helper_named_by_planner_is_safely_routed_through_python_sandbox():
    step = normalizar_passo_de_artefato(
        {
            "tool": "save_html",
            "arguments": {"filename": "pagina.html", "html": "<h1>Oi</h1>"},
        },
        {"preferred_format": "html"},
    )

    assert step["tool"] == "executar_python"
    assert "save_html('pagina.html'" in step["arguments"]["codigo"]


async def test_chains_analysis_then_export_and_attaches_pdf(setor_teste):
    # O PDF vai para a pasta de entregas e volta ao modelo com onde ficou; quem
    # responde é o modelo, sem confirmação pronta.
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
        _tool_call("export_pdf"),
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s1", "u1")

    result = await orch.handle_message(state, "Gere um PDF do Medida geral")

    assert result["attachment"]["type"] == "pdf"
    assert result["harness"]["artifact_plan"]["preferred_format"] == "pdf"
    assert result["harness"]["artifact_validation"]["status"] == "ok"
    assert result["harness"]["harness_allowed"] is True
    assert Path(result["attachment"]["caminho"]).read_bytes()[:4] == b"%PDF"
    assert result["message"] and "Pronto" not in result["message"]
    assert any("ficou em" in str(m.get("content")) for m in state.history if m.get("role") == "system")
    assert state.history[0]["role"] == "user"
    assert state.history[-1] == {"role": "assistant", "content": result["message"]}
    assert result["harness"]["ferramentas"] == ["consultar_medida", "export_pdf"]


async def test_blocked_tool_call_is_not_persisted_in_history(setor_teste):
    planner = ScriptedPlanner([
        _tool_call("export_csv"),  # bloqueado: nenhum resultado computado ainda
        _tool_call("consultar_medida"),
        _respond("Segue a análise de registros."),
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s2", "u2")

    result = await orch.handle_message(state, "Exporte os registros")

    assert result["harness"]["proposed_tool"] == "consultar_medida"
    assert result["harness"]["harness_allowed"] is True
    assert result["harness"]["ferramentas"] == ["consultar_medida"]
    assert [m["chamada"]["nome"] for m in state.history if m.get("chamada")] == ["consultar_medida"]
    assert all("export_csv" not in str(m.get("chamada") or {}) for m in state.history)


async def test_prosa_nao_forca_segunda_chamada():
    planner = ScriptedPlanner([
        _respond("Vou verificar os dados de Medida agora."),
        _tool_call("consultar_medida"),
        _respond("Medida geral calculado com sucesso."),
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s3", "u3")

    result = await orch.handle_message(state, "Qual o Medida geral?")

    assert result["harness"].get("ferramentas", []) == []
    assert state.last_result_id is None
    assert len(planner.scripted) == 2


async def test_resposta_vazia_ganha_a_chamada_de_fechamento_e_responde():
    """Resposta vazia não chega à pessoa: o mesmo modelo recebe o pedido de
    responder com o que tem, sem ferramenta."""
    planner = ScriptedPlanner([
        _respond(""),
        _respond("Resumo final."),
    ])
    orch = SenturyOrchestrator(
        planner=planner,
        responder=EchoResponder(),
        store=_store(),
    )
    state = AnalysisState.new("s4", "u4")

    result = await orch.handle_message(state, "resuma o contexto")

    assert result["message"] == "Resumo final."


async def test_inline_planner_response_is_captured_when_plan_is_requested_with_results(setor_teste):
    planner = ScriptedPlanner([
        _respond("Resposta direta do think.")
    ])
    responder = CaptureResponder("Resposta fraca que nao deveria ser usada.")
    store = _store()
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=store)
    state = AnalysisState.new("s4b", "u4")
    medida = await execute_tool(store, state, "consultar_medida", {"grupo": None})
    state.history.append({
        "role": "system",
        "content": f'RESULTADO DA FERRAMENTA "consultar_medida" (ja executada):\n{json.dumps(medida, ensure_ascii=False)}',
    })

    plan = await orch._generate_plan(
        "explique isso em uma frase",
        state,
        contexto_adicional=None,
        rag_context="",
        complexity="STANDARD",
    )

    assert plan == []
    assert orch.turno.resposta_direta == "Resposta direta do think."
    assert responder.calls == []


async def test_voltas_esgotadas_fecham_na_mesma_conversa(setor_teste):
    """Acabaram as voltas com o modelo ainda pedindo ferramenta: o mesmo modelo
    recebe o pedido de fechar sem ferramenta e responde com o que achou."""
    class LoopingPlanner:
        last_model = "looping-planner"

        async def complete(self, messages):
            if "As voltas deste turno acabaram" in str(messages[-1].get("content")):
                return _respond("Resumo final.")
            return _tool_call("consultar_medida")

    orch = SenturyOrchestrator(planner=LoopingPlanner(), responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s5", "u5")

    result = await orch.handle_message(state, "Analisa tudo")

    assert result["message"] == "Resumo final."
    assert result["harness"]["proposed_tool"] == "consultar_medida"


async def test_tool_execution_failure_is_given_to_the_response_model(setor_teste, monkeypatch):
    from sentury.harness import execucao_do_passo

    async def falhar(*args, **kwargs):
        raise RuntimeError("consulta indisponível")

    monkeypatch.setattr(execucao_do_passo, "execute_tool", falhar)
    planner = RoteiroPlanner([_tool_call("consultar_medida"),
                              _respond("A consulta ficou indisponível neste turno.")])
    responder = CaptureResponder("o redator não devia ser chamado")
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    state = AnalysisState.new("s6", "u6")

    result = await orch.handle_message(state, "Correlacione algo")

    assert result["message"] == "A consulta ficou indisponível neste turno."
    assert not responder.calls
    assert "consulta indisponível" in str(planner.calls[-1]["messages"])
    assert result["harness"]["ferramentas"] == ["consultar_medida"]


async def test_valor_fabricado_vem_com_aviso_em_vez_de_ser_apagado():
    # Sem nenhuma ferramenta rodada, qualquer valor em R$ e inventado. O numero
    # fica e o aviso vai junto: quem vai usar o valor precisa saber que ele nao
    # tem lastro, e reescrever custaria uma chamada de modelo.
    class CurrencyResponder:
        last_model = "currency-responder"

        async def complete(self, messages):
            return json.dumps({"action": "respond", "message": "A economia seria de R$ 100.000,00 por mês."})

    planner = ScriptedPlanner([_respond("A economia seria de R$ 100.000,00 por mês.")])
    orch = SenturyOrchestrator(planner=planner, responder=CurrencyResponder(), store=_store())
    state = AnalysisState.new("sg", "ug")

    result = await orch.handle_message(state, "quanto eu economizaria?")

    assert "R$ 100.000,00" in result["message"], "o valor nao e mais apagado"
    assert "Não encontrei lastro" in result["message"]


async def test_saida_de_exportacao_fecha_a_telemetria_como_as_outras(setor_teste):
    """Tempo, tokens e custo do turno valem em toda saída, inclusive a da exportação."""
    planner = ScriptedPlanner([_tool_call("consultar_medida"), _tool_call("export_pdf")])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())

    result = await orch.handle_message(AnalysisState.new("s1", "u1"), "Gere um PDF do Medida geral")

    assert result["attachment"]["type"] == "pdf"
    for campo in ("total_ms", "tokens", "custo_usd"):
        assert campo in result["telemetry"], campo
    assert "compacted" in result


async def test_binary_export_bytes_never_enter_history(setor_teste):
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
        _tool_call("export_xlsx"),
        _respond("Aqui está a planilha."),
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s7", "u7")

    result = await orch.handle_message(state, "Exporte em excel")

    assert result["attachment"]["type"] == "xlsx"
    assert result["harness"]["artifact_plan"]["preferred_format"] == "xlsx"
    assert result["harness"]["artifact_validation"]["status"] == "ok"
    history_text = json.dumps(state.history)
    assert result["attachment"]["content_base64"] not in history_text


async def test_python_dashboard_html_is_inlined_and_attached(setor_teste):
    planner = ScriptedPlanner([
        _tool_call(
            "executar_python",
            codigo="resultado = save_html_dashboard('painel', '<html><body><h1>ok</h1></body></html>')",
        ),
        _respond("Criei o painel com os dados disponíveis."),
    ])
    responder = CaptureResponder("Criei o painel com os dados disponíveis.")
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    state = AnalysisState.new("dash1", "u1")
    await execute_tool(orch.store, state, "consultar_medida", {})

    result = await orch.handle_message(state, "gere um dashboard html")

    assert result["attachment"]["type"] == "html"
    assert "```html" not in result["message"]
    assert result["message"] == "Criei o painel com os dados disponíveis."
    assert not responder.calls
    assert "<h1>ok</h1>" in base64.b64decode(result["attachment"]["content_base64"]).decode("utf-8")
    assert "html_root" in result["harness"]["artifact_validation"]["checks_run"]
    assert "html_body" in result["harness"]["artifact_validation"]["checks_run"]


async def test_sandbox_source_is_not_returned_or_registered_as_session_result(setor_teste):
    store = _store()
    state = AnalysisState.new("sandbox-no-anchor", "u1")

    result = await execute_tool(store, state, "executar_python", {"codigo": "resultado = len(registros)"})

    assert result["resultado"] > 0
    assert "codigo" not in result
    assert state.results == {}
    assert state.last_result_id is None


async def test_direct_svg_helper_plan_is_routed_to_sandbox_and_delivered_as_attachment():
    planner = ScriptedPlanner([
        _tool_call(
            "save_svg_diagram",
            title="Causa raiz do Medida",
            boxes=[
                {"id": "A", "text": "Tempo de resposta", "level": 0},
                {"id": "B", "text": "Medida baixo", "level": 1},
            ],
            arrows=[{"from": "A", "to": "B"}],
            layout="flow",
        ),
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("svg1", "u1")

    result = await orch.handle_message(state, "monte um diagrama de causa raiz")

    assert result["attachment"]["type"] == "svg"
    svg = base64.b64decode(result["attachment"]["content_base64"]).decode("utf-8")
    assert "Tempo de resposta" in svg and "Medida baixo" in svg
    assert "svg_root" in result["harness"]["artifact_validation"]["checks_run"]


async def test_pedido_de_dashboard_nao_exporta_sem_chamada_do_modelo(setor_teste):
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
        _respond("Montei um panorama inicial do Medida."),
    ])
    responder = CaptureResponder("o redator não devia ser chamado")
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    state = AnalysisState.new("dash2", "u1")

    result = await orch.handle_message(state, "gere um dashboard html do medida geral")

    assert result["attachment"] is None
    assert result["harness"]["ferramentas"] == ["consultar_medida"]
    assert result["message"] == "Montei um panorama inicial do Medida."


async def test_pedido_de_html_sem_markup_nao_vira_dashboard_generico(setor_teste):
    """O modelo não escreveu a página: nenhum painel pronto entra no lugar, e o
    plano da entrega diz o que de fato saiu (texto), não o que o pedido parecia
    pedir."""
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
        _respond("Página solicitada."),
    ])
    responder = CaptureResponder("A página está pronta.")
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    state = AnalysisState.new("custom-html-fallback", "u1")

    result = await orch.handle_message(state, "faça um HTML que explique os motivos da queda do Medida")

    assert result["attachment"] is None
    assert result["harness"]["ferramentas"] == ["consultar_medida"]
    assert result["harness"]["artifact_plan"]["preferred_format"] == "markdown"
    assert result["harness"]["artifact_plan"]["delivery_mode"] == "inline"


async def test_caminho_de_texto_nao_escolhe_modo_pela_palavra():
    """Plano, código ou painel na mensagem não mudam o modo: só o esforço e a
    função marcada, como no passo único."""
    planner = CapturePlanner('{"plan": []}')
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("modo", "u1")

    for pedido in ("monte um plano de ação passo a passo", "calcule em python", "gere um dashboard html"):
        await orch._generate_plan(pedido, state, None, "", complexity="STANDARD")
        assert "mode: lightweight" in _tudo_que_foi(planner.calls[-1]), pedido
    state.funcoes_ativas = ["plano"]
    await orch._generate_plan("oi", state, None, "", complexity="STANDARD")
    assert "mode: action_plan" in _tudo_que_foi(planner.calls[-1])


async def test_o_turno_nao_escolhe_perfil_pela_palavra():
    """Perfil escolhido por palavra só acerta em uma língua e com a grafia
    certa; sem classificador, o roteador decide sem dica."""
    planner = CapturePlanner('{"plan": []}')
    responder = CaptureResponder("Segue a query.")
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    state = AnalysisState.new("perfil", "u1")

    for pedido in ("crie um script python", "gere um dashboard html"):
        await orch._generate_plan(pedido, state, None, "", complexity="STANDARD")
        assert planner.calls[-1]["profile"] is None
    await orch._generate_plan("rode a rotina", state, None, "", complexity="STANDARD", is_replanning=True)
    assert planner.calls[-1]["profile"] is None


async def test_generate_chart_exposes_visual_strategy_in_harness(setor_teste):
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
        _tool_call("generate_chart", tipo="linha"),
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("chart1", "u1")

    result = await orch.handle_message(state, "como esta o medida geral?")

    assert result["attachment"]["type"] == "chart_json"
    assert result["harness"]["planner_mode"] == "lightweight"
    assert result["harness"]["visual_strategy"]["surface"] == "chart_inline"
    assert result["harness"]["visual_strategy"]["chart_type"] == "line"
    assert "chart_datasets" in result["harness"]["artifact_validation"]["checks_run"]


async def test_bloco_no_texto_nao_executa_python_na_pos_resposta(setor_teste):
    texto = (
        "Vou gerar o grafico agora.\n\n```python run\n"
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots()\n"
        "ax.plot([1, 2, 3], [10, 20, 15])\n"
        "plt.savefig('/tmp/nps_chart.png')\n"
        "```"
    )
    planner = ScriptedPlanner([_tool_call("consultar_medida"), _respond(texto)])
    responder = CaptureResponder(texto)
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    state = AnalysisState.new("chart2", "u1")

    result = await orch.handle_message(state, "gere um grafico disso")

    assert result["attachment"] is None
    assert result["harness"]["ferramentas"] == ["consultar_medida"]
    assert result["harness"]["artifact_plan"]["preferred_format"] == "markdown"
    assert "```python run" in result["message"]


async def test_bloco_sem_declaracao_nao_roda_no_sandbox(setor_teste):
    """Pedir para VER codigo nao pode executar codigo."""
    texto = (
        "Claro, aqui vai o codigo:\n\n```python\n"
        "import matplotlib.pyplot as plt\n"
        "plt.savefig('/tmp/nps_chart.png')\n"
        "```"
    )
    planner = ScriptedPlanner([_tool_call("consultar_medida"), _respond(texto)])
    responder = CaptureResponder(texto)
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    state = AnalysisState.new("chart2b", "u1")

    result = await orch.handle_message(state, "me passa um codigo em python que salva um grafico")

    assert result["attachment"] is None
    assert "```python" in result["message"]


async def test_invalid_export_source_falls_back_to_last_result_for_chart_request(setor_teste):
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
        _tool_call("generate_chart", source="nps_lealdade_distribuicao"),
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("chart3", "u1")

    result = await orch.handle_message(state, "gere um grafico disso")

    assert result["attachment"]["type"] == "chart_json"
    assert Path(result["attachment"]["caminho"]).is_file()


async def test_afirmacao_de_grafico_sem_anexo_avisa_sem_exportar(setor_teste):
    planner = RoteiroPlanner([
        _tool_call("consultar_medida"),
        _respond("O gráfico já está pronto e anexado aqui: nps_tendencia.png"),
    ])
    responder = CaptureResponder("O gráfico já está pronto e anexado aqui: nps_tendencia.png")
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    state = AnalysisState.new("chart4", "u1")

    result = await orch.handle_message(state, "gere um grafico disso")

    assert result["attachment"] is None
    assert result["harness"]["ferramentas"] == ["consultar_medida"]
    assert any("confirma esses arquivos" in str(m) for m in state.history)


async def test_modelo_escolhe_a_consulta_apos_recusa_de_grafico_sem_fonte(monkeypatch, setor_teste):
    from sentury.config import settings

    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    planner = RoteiroPlanner([
        _tool_call("generate_chart", tipo="bar"),
        _tool_call("consultar_medida"),
        _tool_call("generate_chart", tipo="bar"),
    ])
    orch = SenturyOrchestrator(
        planner=planner, responder=EchoResponder(), store=_store(),
    )
    state = AnalysisState.new("chart-auto-source", "u1")

    result = await orch.handle_message(
        state,
        "p: Qual metrica voce quer visualizar?\nr: Medida\n"
        "p: Qual formato?\nr: Barras",
    )

    assert result["attachment"]["type"] == "chart_json"
    assert result["harness"]["harness_allowed"] is True
    assert any(recipe["tool"] == "consultar_medida" for recipe in state.results.values())
    assert len(planner.calls) >= 3
    avisos = [m["content"] for m in planner.calls[1]["messages"] if m["role"] == "system"]
    assert any("generate_chart" in aviso for aviso in avisos), avisos


async def test_chart_without_source_or_metric_never_falls_back_to_fabricated_html():
    """Sem métrica, a pergunta do modelo é a resposta: nada de gráfico ou HTML
    inventado no lugar. Depois de um resultado, o texto direto vale, então o
    redator não é chamado."""
    planner = RoteiroPlanner([
        _tool_call("generate_chart"),
        _respond("Qual metrica voce quer visualizar?"),
    ])
    responder = CaptureResponder("Qual metrica voce quer visualizar?")
    orch = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    state = AnalysisState.new("chart-no-metric", "u1")

    result = await orch.handle_message(state, "gere um grafico")

    assert result["attachment"] is None
    assert "qual metrica" in result["message"].lower()
    assert "grafico inventado" not in result["message"]
    assert result["harness"]["artifact_plan"]["preferred_format"] == "markdown"
    assert len(planner.calls) == 2


def test_svg_attachment_maps_to_diagram_visual_strategy():
    visual_strategy = estrategia_visual(
        {"artifact_kind": "diagram", "preferred_format": "svg", "layout_hint": "tree"},
        {"type": "svg"},
    )

    assert visual_strategy["surface"] == "diagram_svg"
    assert visual_strategy["artifact_kind"] == "diagram"
    assert visual_strategy["layout_hint"] == "tree"


# Unit tests for _detect_follow_up_and_extract_context method
async def test_detect_follow_up_with_demonstrative_pronoun_isso():
    """Test detection of follow-up question using 'isso' pronoun"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s10", "u10")
    
    # Add a tool result to history
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Medida geral = 72%"
    })
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Monte um plano de ação para isso", state
    )
    
    assert is_follow_up is True
    assert len(tool_results) == 1
    assert "RESULTADO DA FERRAMENTA" in tool_results[0]["content"]


async def test_detect_follow_up_with_demonstrative_pronoun_esse():
    """Test detection of follow-up question using 'esse' pronoun"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s11", "u11")
    
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Serviço de Campo = 45"
    })
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Gere um 5 Porquês para esse resultado", state
    )
    
    assert is_follow_up is True
    assert len(tool_results) == 1


async def test_detect_follow_up_with_reference_verb_anterior():
    """Test detection of follow-up question using 'anterior' reference verb"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s12", "u12")
    
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: backlog grupo Beta = 47%"
    })
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Com base na análise anterior, gere um plano", state
    )
    
    assert is_follow_up is True
    assert len(tool_results) == 1


async def test_detect_follow_up_with_action_without_params():
    """Test detection of follow-up question using action request without parameters"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s13", "u13")
    
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Pequeno=54, Médio=68, Grande=72"
    })
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Monte um plano de ação", state
    )
    
    assert is_follow_up is True
    assert len(tool_results) == 1


async def test_not_follow_up_without_tool_results():
    """Test that message with follow-up indicators but no tool results is not detected as follow-up"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s14", "u14")
    
    # No tool results in history
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Monte um plano para isso", state
    )
    
    assert is_follow_up is False
    assert len(tool_results) == 0


async def test_not_follow_up_independent_question():
    """Observações são candidatas, não determinam o assunto.not detected as follow-up"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s15", "u15")
    
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Medida geral = 72%"
    })
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Analise o Medida da grupo Alfa no período de janeiro a março", state
    )
    
    assert is_follow_up is True
    assert len(tool_results) == 1


async def test_not_follow_up_conceptual_question():
    """Observações são candidatas, não determinam o assunto.not detected as follow-up"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s16", "u16")
    
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Medida geral = 72%"
    })
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "O que é Medida?", state
    )
    
    assert is_follow_up is True
    assert len(tool_results) == 1


async def test_extract_multiple_tool_results():
    """Test extraction of multiple tool results from history"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s17", "u17")
    
    # Add multiple tool results
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Medida geral = 72%"
    })
    state.history.append({
        "role": "user",
        "content": "E os registros?"
    })
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: backlog = 45%"
    })
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Gere um plano baseado nisso", state
    )
    
    assert is_follow_up is True
    assert len(tool_results) == 2
    assert all("RESULTADO DA FERRAMENTA" in result["content"] for result in tool_results)


async def test_empty_history_not_follow_up():
    """Test that empty history returns no follow-up detection"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s18", "u18")
    
    # Empty history
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Monte um plano para isso", state
    )
    
    assert is_follow_up is False
    assert len(tool_results) == 0


async def test_history_without_tool_results_not_follow_up():
    """Test that history without tool results returns no follow-up detection"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s19", "u19")
    
    # History with only user and assistant messages
    state.history.append({"role": "user", "content": "Olá"})
    state.history.append({"role": "assistant", "content": "Oi, como posso ajudar?"})
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Monte um plano para isso", state
    )
    
    assert is_follow_up is False
    assert len(tool_results) == 0


async def test_detect_follow_up_case_insensitive():
    """Test that follow-up detection is case insensitive"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s20", "u20")
    
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Medida geral = 72%"
    })
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "MONTE UM PLANO PARA ISSO", state
    )
    
    assert is_follow_up is True
    assert len(tool_results) == 1


async def test_detect_follow_up_with_pronoun_variations():
    """Test detection with various pronoun forms (desse, dessa, nisso, etc.)"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s21", "u21")
    
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Medida geral = 72%"
    })
    
    # Test 'desse'
    is_follow_up, _ = orch._detect_follow_up_and_extract_context(
        "Fale mais sobre desse resultado", state
    )
    assert is_follow_up is True
    
    # Test 'dessa'
    is_follow_up, _ = orch._detect_follow_up_and_extract_context(
        "Com base nessa análise", state
    )
    assert is_follow_up is True
    
    # Test 'nisso'
    is_follow_up, _ = orch._detect_follow_up_and_extract_context(
        "Quero focar nisso", state
    )
    assert is_follow_up is True


async def test_detect_follow_up_with_additional_action_verbs():
    """Test detection with various action verbs without parameters"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s22", "u22")
    
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Pequeno=54"
    })
    
    # Test 'crie um'
    is_follow_up, _ = orch._detect_follow_up_and_extract_context(
        "Crie um plano de ação", state
    )
    assert is_follow_up is True
    
    # Test 'elabore um'
    is_follow_up, _ = orch._detect_follow_up_and_extract_context(
        "Elabore um relatório", state
    )
    assert is_follow_up is True
    
    # Test 'construa um'
    is_follow_up, _ = orch._detect_follow_up_and_extract_context(
        "Construa um diagnóstico", state
    )
    assert is_follow_up is True


async def test_only_extracts_system_messages_with_tool_results():
    """Test that only system messages with 'RESULTADO DA FERRAMENTA' are extracted"""
    planner = ScriptedPlanner([])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState.new("s23", "u23")
    
    # Add various message types
    state.history.append({"role": "user", "content": "Analise o Medida"})
    state.history.append({"role": "assistant", "content": "Vou analisar"})
    state.history.append({
        "role": "system",
        "content": "Some system message without tool result"
    })
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Medida = 72%"
    })
    state.history.append({"role": "user", "content": "E os registros?"})
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: backlog = 45%"
    })
    
    is_follow_up, tool_results = orch._detect_follow_up_and_extract_context(
        "Monte um plano baseado nisso", state
    )

    assert is_follow_up is True
    assert len(tool_results) == 2
    # Verify only system messages with tool results are extracted
    for result in tool_results:
        assert result["role"] == "system"
        assert "RESULTADO DA FERRAMENTA" in result["content"]


# --- DEDUP de preview HTML (evita 2 previews: fence inline + card do attachment) ---

_HTML_ATT = {"type": "html", "filename": "x.html"}


def _leaked_html(text: str) -> bool:
    low = text.lower()
    return any(t in low for t in ("<div", "<!doctype", "```html", "<section", "<header", "<main"))


def test_dedup_html_fence_fechado():
    msg = "Pronto:\n\n```html\n<!doctype html><html><body><div>Medida 62</div></body></html>\n```\nNo card."
    out = tirar_html_repetido(msg, _HTML_ATT)
    assert not _leaked_html(out)
    assert "No card." in out


def test_dedup_html_fence_truncado_pelo_flash():
    # flash corta a marcação e não fecha o fence: o dedup antigo deixava o HTML vazar.
    msg = "Segue:\n\n```html\n<!doctype html><html><body><div>Medida 62</div></body></html>"
    out = tirar_html_repetido(msg, _HTML_ATT)
    assert not _leaked_html(out)


def test_dedup_fragmento_div_cru_sem_doctype():
    # HTML solto, sem fence e sem <!doctype>: vira attachment e duplicava na bolha.
    msg = "Aqui:\n<div class='dash'><h1>CX</h1><section>Medida 62</section></div>\nPronto."
    out = tirar_html_repetido(msg, _HTML_ATT)
    assert not _leaked_html(out)
    assert "Pronto." in out


def test_dedup_preserva_texto_sem_html():
    msg = "Montei o dashboard, tá no card abaixo. Abre em tela cheia."
    out = tirar_html_repetido(msg, _HTML_ATT)
    assert out == msg


def test_dedup_nao_roda_sem_attachment_html():
    # sem attachment html, um bloco ```python``` legítimo com '<div>' NÃO pode sumir.
    msg = "Rodei isso:\n```python\nprint('<div>ok</div>')\n```\nfim."
    assert tirar_html_repetido(msg, None) == msg


# --- GUARD anti-fabricação: artefato de dados sem análise na sessão = placeholder ---

def _empty_state() -> AnalysisState:
    return AnalysisState(
        session_id="s", user_id="u", history=[], filtros={}, results={}, last_result_id=None
    )


def test_reject_artefato_de_dados_sem_grounding():
    orch = SenturyOrchestrator(planner=ScriptedPlanner([]), responder=EchoResponder(), store=_store())
    att, reply = recusar_artefato_sem_lastro(orch,
        _empty_state(), _HTML_ATT, "montei o dashboard", [], pre_turn_had_data=False
    )
    assert att is None  # artefato rejeitado
    assert "invent" in reply.lower() or "sobre" in reply.lower()


def test_mantem_artefato_quando_houve_analise_no_turno():
    orch = SenturyOrchestrator(planner=ScriptedPlanner([]), responder=EchoResponder(), store=_store())
    att, reply = recusar_artefato_sem_lastro(orch,
        _empty_state(), _HTML_ATT, "montei o dashboard",
        [{"tool": "consultar_medida", "result": {}}], pre_turn_had_data=False,
    )
    assert att == _HTML_ATT  # grounded → mantém


def test_mantem_artefato_quando_havia_dado_antes_do_turno():
    orch = SenturyOrchestrator(planner=ScriptedPlanner([]), responder=EchoResponder(), store=_store())
    att, reply = recusar_artefato_sem_lastro(orch,
        _empty_state(), _HTML_ATT, "html disso", [], pre_turn_had_data=True
    )
    assert att == _HTML_ATT


# --- BRIDGE de SQL: modelo escreve ```sql mas não emite a tool → harness roda -----

def test_erro_de_ferramenta_nao_vira_resultado_ancora():
    # bug: um SQL contra tabela inexistente virava resultado_NNN e movia o
    # last_result_id → o próximo "gráfico disso" miraria a falha. Erro não registra.
    from sentury.tools.catalog import _registrar_se_houver_dados
    st = _empty_state()
    _registrar_se_houver_dados(st, "consultar_sql", {"sql": "x"}, {"erro": "no such table: chamados"})
    assert st.last_result_id is None and not st.results
    # resultado VÁLIDO continua registrando normalmente
    _registrar_se_houver_dados(st, "consultar_sql", {}, {"volume": 1, "dados": [{"a": 1}]})
    assert st.last_result_id is not None and len(st.results) == 1


async def test_plano_nao_duplica_entre_bolha_e_card(setor_teste, monkeypatch):
    """No Ultra a LLM reescreve o plano rico e ele vai SO no card. O historico
    tem que refletir a bolha curta, senao ao reabrir a conversa o balao volta
    com o plano inteiro E o card aparece embaixo.

    Nenhum pacote declara entrega com arquivo hoje (o plano de acao virou
    skill); o teste declara uma sobre `consultar_medida`, que devolve
    o esqueleto em `markdown`."""
    from robinbandit.sentury import clear_ultra_provider, use_ultra_provider
    from sentury.harness import anexo_do_resultado
    from sentury.harness import artefato_do_turno as modulo

    entrega = {"consultar_medida": {
        "titulo": "Plano de Acao", "arquivo": "plano-de-acao.md",
        "aviso": "Pronto.", "reescrita": "[ESQUELETO]\n{markdown}\nReescreva.",
    }}
    monkeypatch.setattr(modulo, "_entregas_do_setor", lambda: entrega)
    monkeypatch.setattr(anexo_do_resultado, "_entregas_do_setor", lambda: entrega)
    monkeypatch.setattr("sentury.domains.do_setor.entregas", lambda: entrega)
    from sentury.harness import execucao_do_passo

    execucao_real = execucao_do_passo.execute_tool

    async def _execute(store, state, tool, arguments, *a, **k):
        if tool == "consultar_medida":
            return {"markdown": "## Plano\n\n- [ ] Passo do esqueleto"}
        return await execucao_real(store, state, tool, arguments, *a, **k)

    monkeypatch.setattr(execucao_do_passo, "execute_tool", _execute)

    plano = chr(10).join([
        "> [!INSIGHT] Base em risco.",
        "",
        "## Plano de Acao",
        "",
        "- [ ] Reforcar equipe",
        "- [ ] Definir prazo",
    ])
    # O modelo da volta reescreve o esqueleto no plano rico.
    planner = ScriptedPlanner([_tool_call("consultar_medida"), _respond(plano)])
    responder = CaptureResponder(plano)
    orch = SenturyOrchestrator(
        planner=planner,
        responder=responder,
        store=_store(),
    )
    state = AnalysisState.new("s-plano-dup", "u-plano")

    token = use_ultra_provider(planner)  # so precisa nao ser None
    try:
        result = await orch.handle_message(state, "monte um plano de acao")
    finally:
        clear_ultra_provider(token)

    att = result.get("attachment") or {}
    assert att.get("filename") == "plano-de-acao.md"
    assert "Reforcar equipe" in (att.get("content") or "")
    assert "Reforcar equipe" not in (result.get("message") or "")

    ultimo = [m for m in state.history if m.get("role") == "assistant"][-1]
    assert ultimo["content"] == result["message"]


def test_falha_do_modo_separa_provedor_de_erro_interno():
    """Erro interno não pode mandar a pessoa conferir a conta do provedor."""
    from robinbandit.routing.chain import FalhaDaCadeia
    from sentury.main import _ultra_failure_result

    provedor = _ultra_failure_result(AnalysisState.new("f1", "u"), "oi", "ultra_max",
                                     FalhaDaCadeia("Todos os provedores de LLM falharam: limite", ["quota"]))
    interno = _ultra_failure_result(AnalysisState.new("f2", "u"), "oi", "ultra_max",
                                    TypeError("fechar() got an unexpected keyword argument"))
    assert "não responderam" in provedor["message"] and "Provedores" in provedor["message"]
    assert "erro interno do Sentury" in interno["message"] and "Provedores" not in interno["message"]
