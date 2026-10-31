import json
"""Testa o contrato/orçamento do loop, puro, sem LLM."""
from sentury.harness.loop_budget import (
    BudgetTracker,
    LoopBudget,
    ProgressReport,
    StopReason,
    canonicalize_arguments,
    tool_signature,
)


def test_para_por_max_loops():
    t = BudgetTracker(budget=LoopBudget(max_loops=2))
    t.record_iteration()
    assert t.stop_reason() is None
    t.record_iteration()
    assert t.stop_reason() == StopReason.BUDGET_EXHAUSTED


def test_para_por_max_tool_calls():
    t = BudgetTracker(budget=LoopBudget(max_tool_calls=1))
    t.record_tool()
    assert t.stop_reason() == StopReason.BUDGET_EXHAUSTED


def test_para_por_falhas():
    t = BudgetTracker(budget=LoopBudget(max_failures=2))
    t.record_tool(failed=True)
    assert t.stop_reason() is None
    t.record_tool(failed=True)
    assert t.stop_reason() == StopReason.TOOL_FAILURE


def test_para_por_no_progress():
    t = BudgetTracker(budget=LoopBudget(max_consecutive_no_progress=2))
    t.record_tool(progressed=False)
    assert t.stop_reason() is None
    t.record_tool(progressed=False)
    assert t.stop_reason() == StopReason.REPETITION_DETECTED


def test_progresso_reseta_no_progress():
    t = BudgetTracker(budget=LoopBudget(max_consecutive_no_progress=2))
    t.record_tool(progressed=False)
    t.record_tool(progressed=True)
    t.record_tool(progressed=False)
    assert t.stop_reason() is None


def test_canonicalize_valores_sem_diferenca_de_caixa():
    a = tool_signature("consultar_medida", {"grupo": "Alfa"})
    b = tool_signature("consultar_medida", {"grupo": "alfa"})
    c = tool_signature("consultar_medida", {"grupo": "ALFA"})
    assert a == b == c


def test_canonicalize_ordem_e_vazios():
    assert canonicalize_arguments({"b": "x", "a": "y", "c": ""}) == (("a", "y"), ("b", "x"))


def test_progress_report():
    assert ProgressReport(new_evidence_count=2).made_progress
    assert not ProgressReport().made_progress


def test_from_settings_usa_defaults_quando_ausente():
    class S:
        pass
    assert LoopBudget.from_settings(S()).max_loops == LoopBudget().max_loops


# --- W1: motivo de saida do turno ---

async def test_exit_reason_marca_conclusao_normal(setor_teste):
    from tests.test_orchestrator import (
        EchoResponder, ScriptedPlanner, _respond, _store, _tool_call,
    )
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState

    orch = SenturyOrchestrator(
        planner=ScriptedPlanner([_tool_call("consultar_medida"), _respond("Pronto.")]),
        responder=EchoResponder(),
        store=_store(),
    )
    r = await orch.handle_message(AnalysisState.new("s-exit1", "u"), "como esta o medida?")
    stats = r["harness"]["loop_stats"]
    assert stats["exit_reason"] == StopReason.COMPLETED
    assert stats["repeated_calls_skipped"] == 0


async def test_passo_repetido_e_registrado_sem_sujar_a_conclusao(setor_teste):
    """Passo pulado e REGISTRADO, mas nao redefine o motivo de saida.

    Antes eu tinha feito virar REPETITION_DETECTED. Com o loop livre isso vira
    rotina saudavel -- o guard de evidencia injeta uma ferramenta, o planner
    propoe a mesma, o guard de repeticao corta -- e marcar o turno como sujo
    esconderia a repeticao que importa, a que vem do agente girando em falso."""
    from tests.test_orchestrator import (
        EchoResponder, ScriptedPlanner, _respond, _store, _tool_call,
    )
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState

    plano = json.dumps({"action": "tool_call", "plan": [
        {"tool": "consultar_medida", "arguments": {}},
        {"tool": "consultar_medida", "arguments": {}},
    ]})
    orch = SenturyOrchestrator(
        planner=ScriptedPlanner([plano, _respond("Pronto.")]),
        responder=EchoResponder(),
        store=_store(),
    )
    r = await orch.handle_message(AnalysisState.new("s-exit2", "u"), "como esta o medida?")
    stats = r["harness"]["loop_stats"]
    assert stats["repeated_calls_skipped"] >= 1
    assert stats["exit_reason"] == StopReason.COMPLETED


# --- L1: o orcamento como limitador, no lugar da contagem de voltas ---

async def test_loop_livre_desligado_mantem_o_teto_de_2(monkeypatch):
    """Default intocado: sem a flag, o turno continua com as 2 voltas."""
    from sentury.config import settings
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState
    from tests.test_orchestrator import (
        EchoResponder, ScriptedPlanner, _respond, _store, _tool_call,
    )

    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", False)
    # Sempre pede skill (que forca re-planejamento): sem teto isso nao pararia.
    planner = ScriptedPlanner([_tool_call("consultar_medida"), _respond("ok"),
                               _respond("ok"), _respond("ok")])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(),
                               store=_store())
    r = await orch.handle_message(AnalysisState.new("s-l1a", "u"), "como esta o medida?")
    assert r["harness"]["loop_stats"]["loops"] <= 2


async def test_loop_livre_usa_o_orcamento_como_teto(monkeypatch):
    """Com a flag, quem manda e o LoopBudget -- e ele e configuravel, nao um
    numero cravado no meio da funcao."""
    from sentury.config import settings
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState
    from tests.test_orchestrator import (
        EchoResponder, ScriptedPlanner, _respond, _store, _tool_call,
    )

    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setattr(settings, "SENTURY_MAX_LOOPS", 5)
    planner = ScriptedPlanner([_tool_call("consultar_medida")] + [_respond("ok")] * 6)
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(),
                               store=_store())
    r = await orch.handle_message(AnalysisState.new("s-l1b", "u"), "como esta o medida?")
    assert r["harness"]["loop_stats"]["loops"] <= 5


def test_orcamento_para_por_ferramenta_tempo_e_falha():
    """O ponto do L1: contar VOLTA mede a coisa errada. Uma volta que roda 4
    analises custa mais que tres voltas triviais -- quem limita e o consumo."""
    b = BudgetTracker(budget=LoopBudget(max_loops=99, max_tool_calls=3))
    for _ in range(3):
        b.record_tool()
    assert b.exhausted()
    assert b.stop_reason() == StopReason.BUDGET_EXHAUSTED

    b2 = BudgetTracker(budget=LoopBudget(max_loops=99, max_failures=2))
    b2.record_tool(failed=True)
    b2.record_tool(failed=True)
    assert b2.exhausted()

    b3 = BudgetTracker(budget=LoopBudget(max_loops=99, max_consecutive_no_progress=2))
    b3.record_tool(progressed=False)
    b3.record_tool(progressed=False)
    assert b3.exhausted()


# --- L1b: releitura em circulo (hash do RESULTADO) ---

def test_leitura_repetida_com_mesmo_resultado_e_nao_progresso():
    """O caso que a eval mostrou: consultar_medida chamado duas vezes no mesmo turno.
    A chamada 'deu certo', entao contador de FALHA nao pega -- so o hash do
    resultado denuncia que nao veio nada novo."""
    b = BudgetTracker()
    dado = {"medida": -31.2, "volume": 5000}
    assert b.observe_result("consultar_medida", dado) is True    # 1a vez: novidade
    assert b.observe_result("consultar_medida", dado) is False   # 2a: mesma coisa


def test_resultado_diferente_conta_como_progresso():
    b = BudgetTracker()
    assert b.observe_result("consultar_medida", {"medida": -31.2}) is True
    assert b.observe_result("consultar_medida", {"medida": -44.4}) is True  # outro recorte


def test_ferramenta_que_escreve_fica_de_fora():
    """Repetir escrita e outro problema, e resultado igual ali e esperado."""
    b = BudgetTracker()
    reg = {"status": "criada"}
    assert b.observe_result("criar_acao", reg) is True
    assert b.observe_result("criar_acao", reg) is True


def test_releitura_em_circulo_esgota_o_orcamento():
    b = BudgetTracker(budget=LoopBudget(max_loops=99, max_consecutive_no_progress=2))
    dado = {"medida": -31.2}
    for _ in range(3):
        b.record_tool(progressed=b.observe_result("consultar_medida", dado))
    assert b.exhausted()
    assert b.stop_reason() == StopReason.REPETITION_DETECTED


def test_fingerprint_aguenta_objeto_nao_serializavel():
    from sentury.harness.loop_budget import result_fingerprint

    class Estranho:
        pass

    assert result_fingerprint(Estranho())
    assert result_fingerprint({"a": 1}) == result_fingerprint({"a": 1})
    assert result_fingerprint({"a": 1}) != result_fingerprint({"a": 2})
