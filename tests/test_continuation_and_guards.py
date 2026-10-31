import pytest
import unicodedata
from typing import List, Dict, Any

from sentury.harness.state import AnalysisState
from sentury.harness.orchestrator import SenturyOrchestrator

class MockPlanner:
    def __init__(self, responses: List[str]):
        self.responses = list(responses)
        self.last_model = "mock-planner"
        self.calls = 0
        
    async def complete(self, messages, *args, **kwargs):
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return '{"plan": []}'

class MockResponder:
    def __init__(self, response: str = "Mocked Response"):
        self.response = response
        self.last_model = "mock-responder"
        self.last_reasoning_summary = "mocked reasoning"
        
    async def complete(self, messages, *args, **kwargs):
        return self.response


class MockStore:
    def get_feedbacks(self, *args, **kwargs):
        return []
    def resolve_source(self, *args, **kwargs):
        return "resultado"

@pytest.mark.asyncio
async def test_plano_explicitamente_vazio_nao_e_forcado_por_texto_do_think():
    raw = (
        "<think>I should create an empty plan and respond directly.</think>"
        '{"plan": [], "message": "Claro. O que voce precisa?"}'
    )
    planner = MockPlanner([raw])
    responder = MockResponder("o redator não devia ser chamado")
    orchestrator = SenturyOrchestrator(
        planner=planner, responder=responder, store=MockStore(),
    )
    state = AnalysisState.new("conversa-sem-tarefa", "usuario")

    result = await orchestrator.handle_message(state, "explique isso para mim")

    assert result["message"] == "Claro. O que voce precisa?"
    assert planner.calls == 1
    assert not any(
        msg.get("role") == "system" and "indicou que iria executar" in msg.get("content", "")
        for msg in state.history
    )

@pytest.mark.asyncio
async def test_think_nao_vira_ordem_de_executar():
    planner = MockPlanner([
        '<think>vou criar um arquivo</think>{"action":"respond","message":"Preciso da fonte."}',
        '{"plan":[{"tool":"executar_python","arguments":{"codigo":"print(123)"}}]}',
    ])
    orchestrator = SenturyOrchestrator(planner, MockResponder("Preciso da fonte."), MockStore())
    resultado = await orchestrator.handle_message(AnalysisState.new("s", "u"), "Explique como criar um arquivo")
    assert resultado["message"] == "Preciso da fonte."
    assert planner.calls == 1
    assert resultado["harness"].get("ferramentas", []) == []
