import base64
import logging

import pytest

from sentury.config import settings
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.llm.action_parser import _try_load
from tests.test_descoberta_multilingue import _Nativo, _orq
from tests.test_orchestrator import ContractPlanner, EchoResponder, RoteiroPlanner, _store, _tool_call
from sentury.harness.artefato_do_turno import recusar_artefato_sem_lastro


def test_falha_json_registra_posicao_sem_conteudo(caplog):
    with caplog.at_level(logging.DEBUG, logger="sentury.llm.action_parser"):
        assert _try_load('{"segredo":"valor-privado",}') is None
    assert "JSON inválido" in caplog.text
    assert "linha 1" in caplog.text and "coluna" in caplog.text
    assert "valor-privado" not in caplog.text


def test_recusa_do_artefato_informa_o_modelo_sem_entrega():
    state = AnalysisState.new("s", "u")
    orq = _orq(_Nativo([]))
    anexo = {"type": "html", "content_base64": base64.b64encode(b"<p>Venda 42.7</p>").decode()}
    recebido, texto = recusar_artefato_sem_lastro(orq,
        state, anexo, "Entreguei", [], pre_turn_had_data=False,
    )
    assert recebido is None
    assert "não entregue" in texto
    assert len(state.history) == 1
    aviso = state.history[0]
    assert aviso["role"] == "system"
    assert "não há fonte" in aviso["content"] and "não foi entregue" in aviso["content"]
    assert "consultar uma fonte" in aviso["content"]


@pytest.mark.asyncio
async def test_nativo_vazio_nao_pede_reparo_json(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    planner = _Nativo([""])
    orq = _orq(planner)
    assert await orq._generate_plan("Leia um arquivo", AnalysisState.new("s", "u"), None, "") == []
    assert len(planner.chamadas) == 1
    assert orq.turno.reparos_json == 0


@pytest.mark.asyncio
async def test_reparo_textual_e_contado():
    planner = ContractPlanner(["formato ilegível", _tool_call("ler_arquivo", caminho="resumo.txt")])
    orq = SenturyOrchestrator(planner, EchoResponder(), _store())
    plano = await orq._generate_plan("Leia resumo.txt", AnalysisState.new("s", "u"), None, "")
    assert plano == [{"tool": "ler_arquivo", "arguments": {"caminho": "resumo.txt"}}]
    assert planner.calls == 2 and orq.turno.reparos_json == 1


@pytest.mark.asyncio
async def test_contexto_anterior_nao_altera_argumentos_do_modelo(setor_teste):
    planner = RoteiroPlanner([
        _tool_call("consultar_medida"),
        '{"action":"respond","message":"Resultado geral."}',
    ])
    orq = SenturyOrchestrator(planner, EchoResponder(), _store())
    state = AnalysisState.new("s", "u")
    state.filtros = {"grupo": "Alfa"}
    state.history = [{"role": "system", "content": "RESULTADO DA FERRAMENTA consultar_medida: Alfa"}]
    await orq.handle_message(state, "请分析所有工单。")
    assert state.results[state.last_result_id]["arguments"] == {}
    assert any("Alfa" in str(chamada["messages"]) for chamada in planner.calls)
