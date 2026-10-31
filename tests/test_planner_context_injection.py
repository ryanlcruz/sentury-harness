"""O planejador recebe os resultados anteriores quando o pedido continua a conversa.

O contexto do turno vai no fim da conversa, e não no sistema: o sistema fica
igual entre os turnos para o provedor reaproveitar o prefixo.
"""

import json
import pytest
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.fixtures.setor_teste.dados import StoreTeste


class CapturingPlanner:
    """Guarda as mensagens recebidas e devolve plano vazio."""
    def __init__(self):
        self.captured_messages = []
        self.last_model = "capturing-planner"

    async def complete(self, messages, **kwargs):
        self.captured_messages = messages
        return json.dumps({"plan": [], "message": "Certo."})


class EchoResponder:
    last_model = "echo-responder"

    async def complete(self, messages, **kwargs):
        return json.dumps({"action": "respond", "message": "Echo response"})


def _store():
    return StoreTeste()


def _enviado(planner):
    """Tudo o que o planejador recebeu, e só o sistema."""
    tudo = "\n".join(str(m.get("content") or "") for m in planner.captured_messages)
    sistema = next((str(m.get("content") or "") for m in planner.captured_messages
                    if m.get("role") == "system"), None)
    assert sistema is not None, "o planejador precisa receber o sistema"
    return tudo, sistema


@pytest.mark.asyncio
async def test_planner_receives_context_for_follow_up():
    planner = CapturingPlanner()
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())

    state = AnalysisState.new("session1", "user1")
    state.history.append({"role": "user", "content": "Qual unidade de negócio está pior?"})
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: {'unidade': 'Serviço de Campo', 'medida': 45}"
    })

    await orch.handle_message(state, "Monte um plano de ação para isso")

    tudo, sistema = _enviado(planner)
    assert "Observações anteriores disponíveis" in tudo
    assert "consultar_medida" in tudo or "Serviço de Campo" in tudo
    assert "Observações anteriores disponíveis" not in sistema


@pytest.mark.asyncio
async def test_planner_no_context_for_independent_question():
    planner = CapturingPlanner()
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())

    state = AnalysisState.new("session1", "user1")
    state.history.append({"role": "user", "content": "Qual unidade de negócio está pior?"})
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: {'unidade': 'Serviço de Campo', 'medida': 45}"
    })

    await orch.handle_message(state, "Analise o Medida da grupo Alfa no período de janeiro a março")

    tudo, _ = _enviado(planner)
    assert "Observações anteriores disponíveis" in tudo


@pytest.mark.asyncio
async def test_planner_no_context_without_tool_results():
    planner = CapturingPlanner()
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())

    state = AnalysisState.new("session1", "user1")
    state.history.append({"role": "user", "content": "Oi, tudo bem?"})
    state.history.append({"role": "assistant", "content": "Olá! Tudo bem, e você?"})

    await orch.handle_message(state, "Monte um plano para isso")

    tudo, _ = _enviado(planner)
    assert "Observações anteriores disponíveis" not in tudo


@pytest.mark.asyncio
async def test_planner_context_includes_multiple_tool_results():
    planner = CapturingPlanner()
    orch = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())

    state = AnalysisState.new("session1", "user1")
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: {'grupo': 'Beta', 'medida': 45}"
    })
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: {'grupo': 'Beta', 'backlog': 47}"
    })

    await orch.handle_message(state, "Gere um plano baseado nisso")

    tudo, _ = _enviado(planner)
    assert "Observações anteriores disponíveis" in tudo
    assert "Resultado 1:" in tudo
    assert "Resultado 2:" in tudo
