import asyncio
import json

from sentury.agents import ExplicitSubagentCoordinator
from sentury.harness.state import AnalysisState


class CaptureProvider:
    def __init__(self, responses=None, delay=0):
        self.responses = list(responses or [])
        self.delay = delay
        self.calls = []

    async def complete(self, messages, temperature=0.1, complexity=None, profile=None):
        self.calls.append({
            "messages": messages,
            "temperature": temperature,
            "complexity": complexity,
            "profile": profile,
        })
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.responses.pop(0) if self.responses else "Grounded summary."


def _state():
    state = AnalysisState.new("subagents", "user")
    state.history.extend([
        {"role": "user", "content": "private unrelated conversation"},
        {"role": "assistant", "content": "private answer"},
    ])
    state.filtros = {"grupo": "Alfa"}
    state.register_result(
        "consultar_medida",
        {"grupo": "Alfa"},
        {"medida": -31.2, "volume": 5000},
        5000,
    )
    return state


def test_a_mensagem_nao_dispara_subagente_por_palavra():
    """Quem decide é o modelo, pela ferramenta: palavra na mensagem não liga nada."""
    assert not hasattr(ExplicitSubagentCoordinator, "parse_request")
    assert not hasattr(ExplicitSubagentCoordinator, "run")


async def test_subagent_count_is_capped():
    coordinator = ExplicitSubagentCoordinator(CaptureProvider(), max_count=2)
    result = await coordinator.consultar("revise", _state(), quantos=9)
    assert result["requested_count"] == 2
    named = await coordinator.consultar("revise", _state(), papeis=["a1", "b2", "c3"])
    assert [r["role"] for r in named["results"]] == ["a1", "b2"]


async def test_subagents_receive_grounded_results_but_not_chat_history():
    provider = CaptureProvider(["Evidence summary.", "Operations summary."])
    coordinator = ExplicitSubagentCoordinator(provider, default_count=2)

    result = await coordinator.consultar("revise a analise", _state())

    assert result["completed_count"] == 2
    assert len(provider.calls) == 2
    rendered = json.dumps(provider.calls, ensure_ascii=False)
    assert "consultar_medida" in rendered
    assert "-31.2" in rendered
    assert "private unrelated conversation" not in rendered
    assert all(call["complexity"] == "SUBAGENT" for call in provider.calls)
    assert all(call["profile"] == "analysis" for call in provider.calls)


async def test_subagent_summary_is_capped():
    provider = CaptureProvider(["A" * 5000])
    coordinator = ExplicitSubagentCoordinator(provider, default_count=1, max_summary_chars=500)

    result = await coordinator.consultar("revise", _state())
    summary = result["results"][0]["summary"]

    assert len(summary) < 550
    assert "summary truncated" in summary


async def test_subagent_timeout_does_not_raise_or_break_parent():
    provider = CaptureProvider(delay=0.05)
    coordinator = ExplicitSubagentCoordinator(provider, default_count=1, timeout_seconds=0.01)

    result = await coordinator.consultar("revise", _state())

    assert result["completed_count"] == 0
    assert result["results"][0]["status"] == "timeout"


async def test_a_ferramenta_devolve_os_pareceres_para_o_modelo_juntar():
    from sentury.tools import subagentes

    subagentes.registrar(ExplicitSubagentCoordinator(CaptureProvider(["Risco baixo."]), default_count=1))
    try:
        sem_pedido = await subagentes.consultar(_state(), {})
        assert not sem_pedido["ok"] and "pedido" in sem_pedido["erro"]
        saida = await subagentes.consultar(_state(), {"pedido": "avalie o risco", "papeis": ["risco"]})
        assert saida["ok"] and saida["pareceres"] == [{"papel": "risco", "parecer": "Risco baixo."}]
        assert saida["relatorio"]["completed_count"] == 1
    finally:
        subagentes.registrar(None)
