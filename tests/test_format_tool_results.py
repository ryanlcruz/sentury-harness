"""
Unit tests for _format_tool_results_for_context function

Tests the formatting logic that prepares tool results for injection into Planner context.
"""

import pytest
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.fixtures.setor_teste.dados import StoreTeste


class ScriptedPlanner:
    """Planner that returns a pre-defined plan."""
    def __init__(self, plan):
        self.plan = plan
    async def complete(self, messages, **kwargs):
        import json
        return json.dumps({"plan": self.plan})


class EchoResponder:
    """Responder that echoes back the user message."""
    async def complete(self, messages, **kwargs):
        return "Echo: " + messages[-1]["content"]


def _store():
    """Create a mock store for testing."""
    return StoreTeste()


class TestFormatToolResultsForContext:
    """Tests for _format_tool_results_for_context method."""
    
    def test_format_single_tool_result(self):
        """Should format a single tool result correctly."""
        orch = SenturyOrchestrator(
            planner=ScriptedPlanner([]),
            responder=EchoResponder(),
            store=_store()
        )
        
        tool_results = [
            {
                "role": "system",
                "content": "RESULTADO DA FERRAMENTA consultar_medida: {'grupo': 'Beta', 'medida': 45}"
            }
        ]
        
        formatted = orch._format_tool_results_for_context(tool_results)
        
        assert "Resultado 1:" in formatted
        assert "consultar_medida" in formatted
        assert "Beta" in formatted
        assert "45" in formatted
    
    def test_format_multiple_tool_results(self):
        """Should format multiple tool results with numbering."""
        orch = SenturyOrchestrator(
            planner=ScriptedPlanner([]),
            responder=EchoResponder(),
            store=_store()
        )
        
        tool_results = [
            {
                "role": "system",
                "content": "RESULTADO DA FERRAMENTA tool1: data1"
            },
            {
                "role": "system",
                "content": "RESULTADO DA FERRAMENTA tool2: data2"
            }
        ]
        
        formatted = orch._format_tool_results_for_context(tool_results)
        
        assert "Resultado 1:" in formatted
        assert "Resultado 2:" in formatted
        assert "tool1" in formatted
        assert "tool2" in formatted
    
    def test_format_empty_list(self):
        """Should return empty string for empty list."""
        orch = SenturyOrchestrator(
            planner=ScriptedPlanner([]),
            responder=EchoResponder(),
            store=_store()
        )
        
        formatted = orch._format_tool_results_for_context([])
        
        assert formatted == ""
    
    def test_format_truncates_long_results(self):
        """Should truncate tool results longer than 500 characters."""
        orch = SenturyOrchestrator(
            planner=ScriptedPlanner([]),
            responder=EchoResponder(),
            store=_store()
        )
        
        long_data = "x" * 600
        tool_results = [
            {
                "role": "system",
                "content": f"RESULTADO DA FERRAMENTA tool: {long_data}"
            }
        ]
        
        formatted = orch._format_tool_results_for_context(tool_results)
        
        assert "... (dados adicionais truncados)" in formatted
        assert len(formatted) < 600
    
    def test_format_handles_missing_marker(self):
        """Should handle messages without RESULTADO DA FERRAMENTA marker."""
        orch = SenturyOrchestrator(
            planner=ScriptedPlanner([]),
            responder=EchoResponder(),
            store=_store()
        )
        
        tool_results = [
            {
                "role": "system",
                "content": "Some system message without marker"
            }
        ]
        
        formatted = orch._format_tool_results_for_context(tool_results)
        
        # Should not include results without the marker
        assert "Resultado 1:" not in formatted
    
    def test_format_extracts_data_after_marker(self):
        """Should extract only the data portion after RESULTADO DA FERRAMENTA."""
        orch = SenturyOrchestrator(
            planner=ScriptedPlanner([]),
            responder=EchoResponder(),
            store=_store()
        )
        
        tool_results = [
            {
                "role": "system",
                "content": "Some prefix text RESULTADO DA FERRAMENTA analyze_units: Serviço de Campo Medida=45"
            }
        ]
        
        formatted = orch._format_tool_results_for_context(tool_results)
        
        assert "Resultado 1:" in formatted
        assert "analyze_units" in formatted
        assert "Serviço de Campo" in formatted
        assert "Medida=45" in formatted
        # Should not include the prefix
        assert "Some prefix text" not in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
