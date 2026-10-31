"""Chamada de ferramenta escrita no texto vira aviso e mais uma volta.

Sem o aviso, a tag `<tool_call>` limpa da resposta deixaria o turno vazio.
"""
from sentury.config import settings
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.resposta_direta import AVISO_CHAMADA_EM_TEXTO, sem_chamada_vazada
from sentury.harness.state import AnalysisState
from tests.test_orchestrator import EchoResponder, _store
from sentury.harness.turno import Turno


class _Nativo:
    """Provedor com ferramenta nativa que devolve textos em ordem."""

    supports_tools = True

    def __init__(self, textos):
        self.textos = list(textos)
        self.vistas = []
        self.last_model = "dublê"
        self.last_tool_calls = None
        self.last_usage = None

    async def complete(self, messages, temperature=0.2, tools=None, **_):
        self.vistas.append(messages)
        self.last_tool_calls = None
        return self.textos.pop(0) if self.textos else "fim"


def test_detector_nao_confunde_json_comum_com_chamada():
    assert sem_chamada_vazada('<tool_call>{"tool_name": "ler_arquivo"}</tool_call>') == ("", True)
    assert sem_chamada_vazada('```json\n{"plan": [{"tool": "x"}]}\n```')[1]
    texto = 'Config: ```json\n{"porta": 80}\n```'
    assert sem_chamada_vazada(texto) == (texto, False)



async def test_chamada_em_texto_ganha_aviso_e_o_turno_responde(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    planner = _Nativo([
        '<tool_call>{"action": "call_tool", "tool_name": "ler_arquivo", "arguments": {}}</tool_call>',
        "A função é `_nome_limpo`.",
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    state = AnalysisState("s", "u")
    saida = await orch.handle_message(state, "qual a função que limpa o nome?")

    assert "_nome_limpo" in saida["message"]
    assert len(planner.vistas) == 2
    assert any(AVISO_CHAMADA_EM_TEXTO in str(m.get("content")) for m in planner.vistas[1])


class _NativoComChamadas(_Nativo):
    """Cada item e texto (resposta) ou (nome, argumentos) (chamada nativa)."""

    async def complete(self, messages, temperature=0.2, tools=None, **_):
        import json

        self.vistas.append(messages)
        item = self.textos.pop(0) if self.textos else "fim"
        if isinstance(item, tuple):
            nome, argumentos = item
            self.last_tool_calls = [{"id": f"c{len(self.vistas)}", "type": "function",
                                     "function": {"name": nome, "arguments": json.dumps(argumentos)}}]
            return ""
        self.last_tool_calls = None
        return item


async def test_pergunta_depois_de_ler_chega_a_pessoa(monkeypatch, tmp_path):
    """A pergunta feita depois de uma ferramenta chega à pessoa, com ou sem opções."""
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    (tmp_path / "a.csv").write_text("x\n1\n", encoding="utf-8")
    planner = _NativoComChamadas([
        ("listar_arquivos", {"caminho": "."}),
        ("perguntar_usuario", {"pergunta": "Qual dos arquivos voce quer somar?"}),
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    saida = await orch.handle_message(AnalysisState("s", "u"), "some o arquivo")

    # Pergunta aberta: nao ha o que clicar, a pergunta e a resposta do turno.
    assert saida["message"] == "Qual dos arquivos voce quer somar?"
    assert len(planner.vistas) == 2

    com_opcoes = _NativoComChamadas([
        ("listar_arquivos", {"caminho": "."}),
        ("perguntar_usuario", {"pergunta": "Qual arquivo?", "opcoes": ["a.csv", "b.csv"]}),
    ])
    orch = SenturyOrchestrator(planner=com_opcoes, responder=EchoResponder(), store=_store())
    saida = await orch.handle_message(AnalysisState("s2", "u"), "some o arquivo")
    assert saida.get("clarification"), saida["message"]


class _PlanoEmTexto(_Nativo):
    """Provedor sem ferramenta nativa: o plano vem como JSON no texto."""

    supports_tools = False


async def test_pergunta_na_segunda_volta_do_plano_em_texto(monkeypatch, tmp_path):
    """Sem ferramenta nativa o plano vem em JSON, e a pergunta da segunda volta
    também vira cartão."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    planner = _PlanoEmTexto([
        '{"plan": [{"tool": "ler_arquivo", "arguments": {"caminho": "sumiu.txt"}}]}',
        '{"plan": [{"tool": "perguntar_usuario", "arguments": {"pergunta": "Qual arquivo?",'
        ' "opcoes": ["notas.txt", "outro"]}}]}',
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    saida = await orch.handle_message(AnalysisState("s", "u"), "leia sumiu.txt")

    assert not orch.turno.passo_unico
    assert saida.get("clarification"), saida["message"]
    assert "sem executor" not in str(saida)


class _RedatorContado:
    last_model = "redator"

    def __init__(self):
        self.chamadas = 0

    async def complete(self, messages, **_):
        self.chamadas += 1
        return "texto do redator"


async def test_message_depois_dos_resultados_e_a_resposta_sem_redator(monkeypatch, tmp_path):
    """No plano em texto, o `message` escrito depois de ver os resultados é a
    resposta: outra chamada só reescreveria o mesmo."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    planner = _PlanoEmTexto([
        '{"plan": [{"tool": "listar_arquivos", "arguments": {"caminho": "."}}]}',
        '{"plan": [], "message": "A pasta tem um arquivo, a.txt."}',
    ])
    redator = _RedatorContado()
    orch = SenturyOrchestrator(planner=planner, responder=redator, store=_store())
    saida = await orch.handle_message(AnalysisState("s", "u"), "o que tem na pasta?")

    assert saida["message"] == "A pasta tem um arquivo, a.txt."
    assert redator.chamadas == 0
    assert len(planner.vistas) == 2


async def test_plano_vazio_sem_message_fecha_no_mesmo_modelo(monkeypatch, tmp_path):
    """Sem texto do modelo, quem escreve é o mesmo modelo, na chamada de
    fechamento: não há um segundo modelo reescrevendo."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    planner = _PlanoEmTexto([
        '{"plan": [{"tool": "listar_arquivos", "arguments": {"caminho": "."}}]}',
        '{"plan": []}',
        '{"action": "respond", "message": "A pasta está vazia."}',
    ])
    redator = _RedatorContado()
    orch = SenturyOrchestrator(planner=planner, responder=redator, store=_store())
    saida = await orch.handle_message(AnalysisState("s", "u"), "o que tem na pasta?")

    assert redator.chamadas == 0
    assert saida["message"] == "A pasta está vazia."


async def test_pergunta_so_no_intro_vira_a_resposta_do_turno(monkeypatch, tmp_path):
    """O plano em texto não passa pelo esquema: com `questions` vazio, o
    `intro` é a pergunta."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    planner = _PlanoEmTexto([
        '{"plan": [{"tool": "ler_arquivo", "arguments": {"caminho": "sumiu.txt"}}]}',
        '{"plan": [{"tool": "perguntar_usuario", "arguments": {"intro": "Qual o caminho certo?",'
        ' "questions": []}}]}',
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    saida = await orch.handle_message(AnalysisState("s", "u"), "leia sumiu.txt")

    assert saida["message"] == "Qual o caminho certo?"
    assert len(planner.vistas) == 2


def test_pergunta_sem_texto_sai_do_plano_e_o_modelo_fica_sabendo():
    """Sem texto não há o que mostrar: a pergunta sai do plano e o modelo é avisado."""
    from sentury.harness.esclarecimento import resolver
    from sentury.harness.perguntas import extrair

    class _Orq:
        def _extract_clarification(self, plan):
            return extrair(plan, None)

    state = AnalysisState("s", "u")
    plano = [{"tool": "perguntar_usuario", "arguments": {"questions": []}},
             {"tool": "listar_arquivos", "arguments": {}}]
    saida, pergunta = resolver(_Orq(), plano, state=state, user_message="x",
                               retomar=None, max_perguntas_seguidas=2)

    assert pergunta is None
    assert [p["tool"] for p in saida] == ["listar_arquivos"]
    assert "sem texto de pergunta" in state.history[-1]["content"]


async def test_voltas_acabam_e_o_turno_fecha_com_texto(monkeypatch, tmp_path):
    """Quando as voltas acabam com o modelo ainda pedindo ferramenta, o turno
    fecha numa chamada sem ferramenta, e não vazio."""
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setattr(settings, "SENTURY_MAX_LOOPS", 2)
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    for nome in ("a", "b", "c", "d"):
        (tmp_path / nome).mkdir()
    planner = _NativoComChamadas([
        ("listar_arquivos", {"caminho": "a"}),
        ("listar_arquivos", {"caminho": "b"}),
        ("listar_arquivos", {"caminho": "c"}),
        ("listar_arquivos", {"caminho": "d"}),
        "Olhei as pastas a e b; nao cheguei nas outras.",
    ])

    class _RedatorVazio:
        """Redator que não escreve nada."""
        last_model = "vazio"

        async def complete(self, messages, **_):
            return ""

    orch = SenturyOrchestrator(planner=planner, responder=_RedatorVazio(), store=_store())
    saida = await orch.handle_message(AnalysisState("s", "u"), "liste todas as pastas")

    assert saida["message"].strip(), "turno terminou vazio"
    assert "listar_arquivos" not in saida["message"] or "Parei no limite" in saida["message"]


async def test_provedor_que_recusa_nao_vira_limite_de_passos(monkeypatch):
    """Recusa por taxa (429) é o provedor parando, não o limite de passos, e a
    mensagem diz isso."""
    from sentury.harness.encerramento import responder_no_limite

    class _Recusa:
        async def complete(self, *a, **k):
            raise RuntimeError("Client error '429 Too Many Requests'")

    class _Orq:
        planner = _Recusa()
        turno = Turno(prompt_do_passo="sistema")

    texto = await responder_no_limite(_Orq(), AnalysisState("s", "u"), "oi", ["ler_arquivo"])
    assert "limitou o uso" in texto and "limite de passos" not in texto
    assert "ler_arquivo" in texto


async def test_bloco_marcado_para_rodar_vira_aviso_e_nao_roda_depois(monkeypatch):
    """Bloco ```python run escrito no texto vira aviso ao modelo, que chama a
    ferramenta; o harness não roda o bloco depois do laço."""
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    cerca = chr(96) * 3
    planner = _Nativo([
        f"Vou montar.\n\n{cerca}python run\nraise RuntimeError('quebrou')\n{cerca}",
        "Montei o grafico com os totais por mes.",
    ])
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    saida = await orch.handle_message(AnalysisState("s", "u"), "faca um grafico disso")

    assert saida["message"] == "Montei o grafico com os totais por mes."
    assert any(AVISO_CHAMADA_EM_TEXTO in str(m.get("content")) for m in planner.vistas[1])


def test_motivo_vem_do_tipo_que_a_cadeia_classificou():
    """O texto da falha da cadeia não traz o 429; o motivo vem do tipo classificado."""
    from robinbandit.routing.chain import FalhaDaCadeia
    from sentury.harness.encerramento import _motivo_do_provedor

    exc = FalhaDaCadeia("Todos os provedores de LLM falharam: ...", ["rate_limit"])
    assert _motivo_do_provedor(exc) == "o provedor limitou o uso por agora"
