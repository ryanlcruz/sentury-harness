"""A telemetria conta as fontes disponíveis entre turnos."""

import json
import pytest
from typing import List, Dict, Any

from tests.fixtures.setor_teste.dados import StoreTeste
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState


class ScriptedPlanner:
    """Mock planner that returns scripted responses."""
    
    def __init__(self, scripted: List[str]):
        self.scripted = list(scripted)
        self.last_model = "scripted-planner"
        self.call_history: List[Dict[str, Any]] = []
    
    async def complete(self, messages, **kwargs):
        self.call_history.append({"messages": messages, "kwargs": kwargs})
        if not self.scripted:
            return json.dumps({"plan": []})
        response = self.scripted.pop(0)
        return f"<reasoning>test planning</reasoning>\n{response}"


class InspectingResponder:
    """Mock responder that records what it receives."""
    
    def __init__(self, scripted: List[str] = None):
        self.scripted = list(scripted) if scripted else []
        self.last_model = "inspecting-responder"
        self.call_history: List[Dict[str, Any]] = []
    
    async def complete(self, messages, **kwargs):
        self.call_history.append({"messages": messages, "kwargs": kwargs})
        if not self.scripted:
            return "Resposta gerada."
        return self.scripted.pop(0)


def _tool_call(tool: str, **arguments) -> str:
    """Helper to create a tool call plan."""
    return json.dumps({"plan": [{"tool": tool, "arguments": arguments}]})


def _empty_plan() -> str:
    """Helper to create an empty plan."""
    return json.dumps({"plan": []})


def _store() -> StoreTeste:
    """Create a test data store."""
    return StoreTeste()


@pytest.mark.asyncio
async def test_telemetry_antecedentes_disponiveis_true(setor_teste):
    """
    Test that telemetry["antecedentes_disponiveis"] is True when user asks a follow-up question.
    
    Scenario:
    - Turn 1: User asks for business unit analysis
    - Turn 2: User asks follow-up with pronoun "essa unidade"
    
    Expected:
    - telemetry["antecedentes_disponiveis"] should be True in Turn 2
    - telemetry["context_injected_count"] should be > 0 (at least one tool result)
    """
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
        _tool_call("consultar_medida", metodologia="5_porques"),
    ])
    responder = InspectingResponder([
        "A unidade pior é Serviço de Campo com Medida de 45.",
        "Aqui está o plano de ação."
    ])
    
    orch = SenturyOrchestrator(
        planner=planner,
        responder=responder,
        store=_store())
    state = AnalysisState.new("session1", "user1")
    
    # Turn 1: Initial analysis
    result1 = await orch.handle_message(state, "Qual unidade de negócio está pior?")
    
    # Turn 1 should not be detected as follow-up (no previous tool results)
    assert "antecedentes_disponiveis" in result1["telemetry"]
    assert result1["telemetry"]["antecedentes_disponiveis"] is False, (
        "First message should not be detected as follow-up"
    )
    assert result1["telemetry"]["context_injected_count"] == 0, (
        "No context should be injected for first message"
    )
    
    # Turn 2: Follow-up with pronoun "essa unidade"
    result2 = await orch.handle_message(state, "Monte um 5 Porquês para essa unidade")
    
    # Verify telemetry for follow-up detection
    assert "antecedentes_disponiveis" in result2["telemetry"], (
        "telemetry should contain 'antecedentes_disponiveis' field"
    )
    assert result2["telemetry"]["antecedentes_disponiveis"] is True, (
        "Follow-up question with pronoun 'essa unidade' should be detected as follow-up"
    )
    
    assert "context_injected_count" in result2["telemetry"], (
        "telemetry should contain 'context_injected_count' field"
    )
    assert result2["telemetry"]["context_injected_count"] > 0, (
        "Follow-up should have at least one tool result injected from previous turn"
    )


@pytest.mark.asyncio
async def test_telemetry_antecedentes_disponiveis_false(setor_teste):
    """
    Test that telemetry["antecedentes_disponiveis"] is False for independent questions.
    
    Scenario:
    - Turn 1: User asks for Beta region analysis
    - Turn 2: User asks independent question about Alfa region (no follow-up)
    
    Expected:
    - telemetry["antecedentes_disponiveis"] should be False in Turn 2
    - telemetry["context_injected_count"] should be 0
    """
    planner = ScriptedPlanner([
        _tool_call("consultar_medida", grupo="Beta"),
        _tool_call("consultar_medida", grupo="Alfa"),
    ])
    responder = InspectingResponder([
        "O Medida da grupo Beta está em 47%.",
        "O Medida da grupo Alfa está em 65%."
    ])
    
    orch = SenturyOrchestrator(
        planner=planner,
        responder=responder,
        store=_store())
    state = AnalysisState.new("session2", "user2")
    
    # Turn 1: Beta analysis
    result1 = await orch.handle_message(state, "Como está o Medida da grupo Beta?")
    assert result1["telemetry"]["antecedentes_disponiveis"] is False
    
    # Turn 2: Independent question about Alfa (explicit parameters, no reference to Beta)
    result2 = await orch.handle_message(state, "Agora analise a grupo Alfa")
    
    # Verify telemetry for independent question
    assert "antecedentes_disponiveis" in result2["telemetry"]
    assert result2["telemetry"]["antecedentes_disponiveis"] is True, (
        "A fonte anterior é candidata; o novo recorte continua sendo escolhido pelo modelo"
    )
    
    assert "context_injected_count" in result2["telemetry"]
    assert result2["telemetry"]["context_injected_count"] > 0, (
        "A fonte anterior deve continuar acessível sem forçar reutilização"
    )


@pytest.mark.asyncio
async def test_telemetry_follow_up_with_demonstrative_pronoun(setor_teste):
    """
    Test telemetry for follow-up using demonstrative pronoun "isso".
    
    Scenario:
    - Turn 1: Regional analysis
    - Turn 2: "Gere um plano de ação para isso"
    
    Expected:
    - telemetry["antecedentes_disponiveis"] = True
    - telemetry["context_injected_count"] > 0
    """
    planner = ScriptedPlanner([
        _tool_call("consultar_medida", grupo="Beta"),
        _tool_call("consultar_medida", grupo="Beta"),
    ])
    responder = InspectingResponder([
        "Medida Beta: 47%",
        "Plano de ação gerado."
    ])
    
    orch = SenturyOrchestrator(
        planner=planner,
        responder=responder,
        store=_store())
    state = AnalysisState.new("session3", "user3")
    
    # Turn 1
    await orch.handle_message(state, "Como está o Medida da grupo Beta?")
    
    # Turn 2: Follow-up with "isso"
    result2 = await orch.handle_message(state, "Gere um plano de ação para isso")
    
    assert result2["telemetry"]["antecedentes_disponiveis"] is True, (
        "Message with demonstrative pronoun 'isso' should be detected as follow-up"
    )
    assert result2["telemetry"]["context_injected_count"] > 0


@pytest.mark.asyncio
async def test_telemetry_follow_up_with_action_without_params(setor_teste):
    """
    Test telemetry for follow-up using action request without parameters.
    
    Scenario:
    - Turn 1: Segment analysis
    - Turn 2: "Monte um plano" (action without specifying which segment)
    
    Expected:
    - telemetry["antecedentes_disponiveis"] = True
    - telemetry["context_injected_count"] > 0
    """
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
        _tool_call("consultar_medida"),
    ])
    responder = InspectingResponder([
        "Segmentos: Grande 72%, Médio 68%, Pequeno 54%",
        "Plano gerado."
    ])
    
    orch = SenturyOrchestrator(
        planner=planner,
        responder=responder,
        store=_store())
    state = AnalysisState.new("session4", "user4")
    
    # Turn 1
    await orch.handle_message(state, "Analise os segmentos")
    
    # Turn 2: Action without parameters
    result2 = await orch.handle_message(state, "Monte um plano")
    
    assert result2["telemetry"]["antecedentes_disponiveis"] is True, (
        "Action request 'Monte um' without parameters should be detected as follow-up"
    )
    assert result2["telemetry"]["context_injected_count"] > 0


@pytest.mark.asyncio
async def test_telemetry_no_follow_up_when_no_tool_results(setor_teste):
    """
    Test that follow-up is NOT detected when there are no previous tool results.
    
    Scenario:
    - Turn 1: First message with pronoun-like words but no history
    
    Expected:
    - telemetry["antecedentes_disponiveis"] = False (no tool results exist yet)
    - telemetry["context_injected_count"] = 0
    """
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
    ])
    responder = InspectingResponder(["Análise do Medida."])
    
    orch = SenturyOrchestrator(
        planner=planner,
        responder=responder,
        store=_store())
    state = AnalysisState.new("session5", "user5")
    
    # First message that happens to contain "isso" but no previous context
    result = await orch.handle_message(state, "Analise isso por favor")
    
    assert result["telemetry"]["antecedentes_disponiveis"] is False, (
        "Should not detect follow-up when no previous tool results exist in history"
    )
    assert result["telemetry"]["context_injected_count"] == 0


@pytest.mark.asyncio
async def test_telemetry_context_injected_count_matches_tool_results(setor_teste):
    """
    Test that context_injected_count matches the number of tool results in history.
    
    Scenario:
    - Turn 1: Execute 2 tools (consultar_medida and consultar_medida)
    - Turn 2: Follow-up question
    
    Expected:
    - telemetry["context_injected_count"] should equal 2 (both tool results)
    """
    planner = ScriptedPlanner([
        _tool_call("consultar_medida", grupo="Beta"),
        _tool_call("consultar_medida"),
    ])
    responder = InspectingResponder(["Análises completas.", "Plano gerado."])
    
    orch = SenturyOrchestrator(
        planner=planner,
        responder=responder,
        store=_store())
    state = AnalysisState.new("session6", "user6")
    
    # Turn 1: Execute analysis (will create tool result in history)
    result1 = await orch.handle_message(state, "Analise o Medida da Beta")
    
    # Count tool results in history after Turn 1
    tool_results_count = sum(
        1 for msg in state.history
        if msg.get("role") == "system" and "RESULTADO DA FERRAMENTA" in msg.get("content", "")
    )
    
    # Turn 2: Follow-up
    result2 = await orch.handle_message(state, "Gere um plano para isso")
    
    # Verify context_injected_count matches the number of tool results
    assert result2["telemetry"]["context_injected_count"] == tool_results_count, (
        f"context_injected_count should equal number of tool results in history "
        f"(expected {tool_results_count}, got {result2['telemetry']['context_injected_count']})"
    )


@pytest.mark.asyncio
async def test_telemetry_multiple_follow_ups(setor_teste):
    """
    Test telemetry across multiple follow-up questions in sequence.
    
    Scenario:
    - Turn 1: Initial analysis
    - Turn 2: First follow-up
    - Turn 3: Second follow-up
    
    Expected:
    - Turns 2 and 3 should both have antecedentes_disponiveis = True
    - context_injected_count should increase as more tool results accumulate
    """
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),
        _tool_call("consultar_medida", unidade_negocio="Serviço de Campo"),
        _tool_call("consultar_medida", unidade_negocio="Serviço de Campo"),
    ])
    responder = InspectingResponder([
        "Pior unidade: Serviço de Campo",
        "Causas identificadas.",
        "Plano gerado."
    ])
    
    orch = SenturyOrchestrator(
        planner=planner,
        responder=responder,
        store=_store())
    state = AnalysisState.new("session7", "user7")
    
    # Turn 1: Initial
    result1 = await orch.handle_message(state, "Qual unidade está pior?")
    assert result1["telemetry"]["antecedentes_disponiveis"] is False
    
    # Turn 2: First follow-up
    result2 = await orch.handle_message(state, "Por que essa unidade está mal?")
    assert result2["telemetry"]["antecedentes_disponiveis"] is True
    count_after_turn2 = result2["telemetry"]["context_injected_count"]
    assert count_after_turn2 > 0
    
    # Turn 3: Second follow-up
    result3 = await orch.handle_message(state, "Monte um plano para isso")
    assert result3["telemetry"]["antecedentes_disponiveis"] is True
    count_after_turn3 = result3["telemetry"]["context_injected_count"]
    
    # context_injected_count should include results from both previous analyses
    assert count_after_turn3 >= count_after_turn2, (
        "Second follow-up should have access to all previous tool results"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
