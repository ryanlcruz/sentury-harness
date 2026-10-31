"""Guardas do loop não decidem ferramentas pelo idioma.

Provedores roteados medem execução do contrato, não compreensão da LLM.
Fonte e renderizador reais provam que não removemos a validação dos dados.
"""
import json

import pytest

from sentury.config import settings
from sentury.harness.state import AnalysisState
from sentury.tools.catalog import execute_tool
from tests.test_descoberta_multilingue import _Nativo, _orq
from tests.test_orchestrator import RoteiroPlanner


def _proibir_guardas(orq, monkeypatch):
    """As guardas que escolhiam ferramenta por palavra do pedido não existem mais."""
    for nome in ("_inject_root_cause_if_needed", "_inject_action_plan_if_needed", "_needs_causal_evidence",
                 "_inject_artifact_if_needed", "_inject_missing_artifact_clarification"):
        assert not hasattr(orq, nome)


def _configurar(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setattr(settings, "SENTURY_PROGRESSIVE_CAPABILITIES", True)
    monkeypatch.setattr(settings, "SENTURY_GRAVAR_TRACOS", False)


@pytest.mark.parametrize("nativo", [False, True])
@pytest.mark.parametrize("pedido", ["请绘制趋势图。", "ارسم الاتجاه الزمني.",
                                    "Покажи график изменения показателя."])
async def test_grafico_escolhido_pelo_agente_nao_e_apagado(monkeypatch, setor_teste, pedido, nativo):
    _configurar(monkeypatch)
    planner = _Nativo([
        ("search_tools", {"nomes": ["generate_chart"]}),
        ("generate_chart", {}),
        "Gráfico pronto.",
    ]) if nativo else RoteiroPlanner([
        json.dumps({"plan": [{"tool": "generate_chart", "arguments": {}}]}),
        json.dumps({"plan": []}),
    ])
    orq = _orq(planner)
    _proibir_guardas(orq, monkeypatch)
    state = AnalysisState.new("chart", "dono")
    await execute_tool(orq.store, state, "consultar_medida", {})
    result = await orq.handle_message(state, pedido)
    assert "generate_chart" in result["harness"]["ferramentas"]
    assert result["attachment"]["type"] == "chart_json"
    assert result["attachment"]["chart_data"]["data"]["datasets"]
    assert "chart_datasets" in result["harness"]["artifact_validation"]["checks_run"]


@pytest.mark.parametrize("nativo", [False, True])
@pytest.mark.parametrize("pedido", ["Explique o que é um relatório; não crie nenhum.",
                                    "O que significa causa raiz do Medida?",
                                    "请解释报告是什么，不要创建文件。"])
async def test_plano_vazio_nao_vira_ferramenta_ou_questionario(monkeypatch, setor_teste, pedido, nativo):
    _configurar(monkeypatch)
    planner = _Nativo(["É uma explicação, sem ação."]) if nativo else RoteiroPlanner([
        json.dumps({"plan": []}),
    ])
    orq = _orq(planner)
    _proibir_guardas(orq, monkeypatch)
    result = await orq.handle_message(AnalysisState.new("sem-acao", "dono"), pedido)
    assert result["harness"]["ferramentas"] == []
    assert result.get("clarification") is None
    assert result["attachment"] is None


async def test_followup_ultra_nao_pula_planner_por_palavra(monkeypatch, setor_teste):
    _configurar(monkeypatch)
    import robinbandit.sentury
    monkeypatch.setattr(robinbandit.sentury, "is_ultra_active", lambda: True)
    planner = RoteiroPlanner([json.dumps({"plan": []})])
    orq = _orq(planner)
    state = AnalysisState.new("followup", "dono")
    await execute_tool(orq.store, state, "consultar_medida", {})
    state.history.append({"role": "system", "content": "RESULTADO DA FERRAMENTA: fonte disponível"})
    result = await orq.handle_message(state, "Explique como funcionaria um gráfico disso.")
    assert planner.calls, "ter dados e dizer gráfico não autoriza pular a escolha do modelo"
    assert result["harness"]["planner_mode"] != "short_circuit_followup"


async def test_sem_fonte_grafico_escolhido_continua_bloqueado(monkeypatch, setor_teste):
    _configurar(monkeypatch)
    planner = _Nativo([
        ("search_tools", {"nomes": ["generate_chart"]}),
        ("generate_chart", {}),
        "Preciso de uma fonte real para construir o gráfico.",
    ])
    # O export existe neste pacote, mas não há nenhum resultado para renderizar.
    state = AnalysisState.new("sem-fonte", "dono")
    result = await _orq(planner).handle_message(state, "请绘制趋势图。")
    assert result["attachment"] is None
    assert not result["harness"]["harness_allowed"]
    assert not state.results
