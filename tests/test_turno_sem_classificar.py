"""O turno nativo não aceita decisões anteriores à chamada do modelo."""
from unittest.mock import AsyncMock

import pytest

from sentury.harness.configuracao_do_turno import configurar, conselho_pedido, modo_nativo, experiencia_observada
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.llm.effort import use_effort, clear_effort
from tests.test_descoberta_multilingue import _Nativo
from tests.test_orchestrator import EchoResponder, NativeCouncil, _store


@pytest.mark.parametrize("pedido", ["conselho para melhorar o Medida", "请检查项目文件", "compare as opções"])
async def test_o_modelo_do_turno_e_a_unica_chamada(pedido):
    planner = _Nativo(["Resposta sem ação."])
    responder = AsyncMock()
    orq = SenturyOrchestrator(planner=planner, responder=responder, store=_store())
    resultado = await orq.handle_message(AnalysisState.new("nativo", "dono"), pedido)
    assert resultado["message"] == "Resposta sem ação."
    assert resultado["harness"]["events"] == []
    responder.complete.assert_not_called()
    assert len(planner.chamadas) == 1


@pytest.mark.parametrize("nivel, complexidade, modo", [
    ("low", "SIMPLE", "lightweight"), ("medium", "STANDARD", "lightweight"),
    ("high", "COMPLEX", "deliberate"), ("xhigh", "CRITICAL", "deliberate"),
])
async def test_esforco_explicito_decide_sem_classificar(nivel, complexidade, modo):
    orq = SenturyOrchestrator(planner=_Nativo([]), responder=EchoResponder(), store=_store())
    estado = AnalysisState.new("esforco", "dono")
    token = use_effort(nivel)
    try:
        configuracao = await configurar(orq, "plano urgente com conselho", estado, {})
        assert configuracao == (complexidade, False), "só o esforço e o pedido de conselho"
        assert modo_nativo(estado) == modo
        estado.funcoes_ativas = ["plano"]
        assert modo_nativo(estado) == "action_plan"
    finally:
        clear_effort(token)


def test_conselho_so_por_badge_ou_prefixo():
    estado = AnalysisState.new("conselho", "dono")
    assert not conselho_pedido("preciso de conselho para melhorar os clientes", estado)
    assert not conselho_pedido("explique o [llm-council]", estado)
    assert conselho_pedido("[llm-council] 請分析", estado)
    estado.funcoes_ativas = ["llm-council"]
    assert conselho_pedido("分析", estado)


async def test_palavra_conselho_no_pedido_nao_liga_conselho(setor_teste):
    conselho = NativeCouncil()
    orq = SenturyOrchestrator(planner=_Nativo(["Resposta."]), responder=EchoResponder(), store=_store(), council=conselho)
    estado = AnalysisState.new("nao-conselho", "dono")
    estado.register_result("consultar_medida", {}, {"medida": -31.2, "volume": 5000}, 1)
    await orq.handle_message(estado, "me dê conselho para melhorar os clientes")
    assert conselho.calls == []
    assert estado.history[0]["priority"] == "NORMAL"


async def test_badge_conselho_com_evidencia_usa_o_pedido(setor_teste):
    conselho = NativeCouncil()
    orq = SenturyOrchestrator(planner=_Nativo(["Avaliei as fontes."]), responder=EchoResponder(),
                              store=_store(), council=conselho)
    estado = AnalysisState.new("com-conselho", "dono")
    estado.funcoes_ativas = ["llm-council"]
    estado.register_result("consultar_medida", {}, {"medida": -31.2, "volume": 5000}, 1)
    resultado = await orq.handle_message(estado, "considere estas fontes")
    assert len(conselho.calls) == 1
    assert resultado["skill_activated"] == ["llm-council"]


def test_experiencia_descarta_falha_e_permissao_pendente():
    resultados = [
        {"tool": "falha", "result": {"erro": "recusada"}},
        {"tool": "pendente", "result": {"precisa_permissao": True}},
        {"tool": "negada", "result": {"ok": False, "recusado": True}},
        {"tool": "leitura", "result": {"conteudo": "obtido"}},
    ]
    assert experiencia_observada(resultados) == [{"tool": "leitura"}]


async def test_experiencia_grava_execucao_e_nao_ultimo_plano_vazio(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    (tmp_path / "nota.txt").write_text("Conteúdo observado.", encoding="utf-8")
    planner = _Nativo([
        ("search_tools", {"nomes": ["ler_arquivo"]}),
        ("ler_arquivo", {"caminho": "nota.txt"}), "Li a nota.",
    ])
    orq = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    orq.experience_library = AsyncMock()
    resultado = await orq.handle_message(AnalysisState.new("execucao", "dono"), "leia nota.txt")
    assert resultado["harness"]["ferramentas"] == ["search_tools", "ler_arquivo"]
    orq.experience_library.find_similar.assert_not_called()
    orq.experience_library.save.assert_awaited_once_with(
        "ferramentas", ["search_tools", "ler_arquivo"], success=True, user_message="leia nota.txt",
    )


@pytest.mark.parametrize("mensagem", ["oi", "oii, td bem?", "こんにちは", "por que caiu?"])
async def test_auto_nao_escolhe_esforco_pela_mensagem(monkeypatch, mensagem):
    """Saudação ou pedido, em qualquer língua ou grafia: o Auto trata igual."""
    from sentury.llm import effort as mod

    vistos = []
    original = mod.use_effort
    monkeypatch.setattr(mod, "use_effort", lambda lv: vistos.append(lv) or original(lv))
    orq = SenturyOrchestrator(planner=_Nativo([]), responder=EchoResponder(), store=_store())
    await orq.handle_message(AnalysisState.new("auto", "dono"), mensagem)
    assert vistos == []


async def test_barra_manual_define_o_esforco(monkeypatch):
    from sentury.llm import effort as mod

    vistos = []
    original = mod.use_effort
    monkeypatch.setattr(mod, "use_effort", lambda lv: vistos.append(lv) or original(lv))
    orq = SenturyOrchestrator(planner=_Nativo([]), responder=EchoResponder(), store=_store())
    await orq.handle_message(AnalysisState.new("manual", "dono"), "oi", effort="high")
    assert vistos == ["high"]
