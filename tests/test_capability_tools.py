"""L2: conhecimento e experiencia deixam de ser PRE-BUSCA do classify e viram
tool que o modelo chama quando percebe que precisa.

O gate adivinhava antes de qualquer dado existir. A tool e chamada depois.
"""
import json

from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.tools.registry import TOOL_REGISTRY
from tests.test_orchestrator import (
    EchoResponder, ScriptedPlanner, _respond, _store, _tool_call,
)


class _ExpLib:
    def __init__(self, resposta=None):
        self.chamadas = []
        self.resposta = resposta

    async def find_similar(self, intent, user_message):
        self.chamadas.append((intent, user_message))
        return self.resposta

    async def save(self, *a, **kw):
        return None


def test_experiencia_e_uma_tool_registrada():
    assert "consultar_experiencia" in TOOL_REGISTRY


async def test_modelo_consulta_experiencia_quando_quer():
    exp = _ExpLib({"intent": "ANALYSIS", "flow": ["consultar_medida", "consultar_medida"]})
    orch = SenturyOrchestrator(
        planner=ScriptedPlanner([_tool_call("consultar_experiencia", consulta="causa do medida"),
                                 _respond("Pronto.")]),
        responder=EchoResponder(), store=_store(), experience_library=exp,
    )
    r = await orch.handle_message(AnalysisState.new("s-l2a", "u"), "por que o medida caiu?")
    assert exp.chamadas, "a tool nao chegou na biblioteca"
    assert r["message"]


async def test_abertura_do_turno_nao_pre_busca_experiencia():
    """Experiência entra só quando o modelo chama a ferramenta: a abertura do
    turno não adivinha antes de ver os dados."""
    exp = _ExpLib({"intent": "ANALYSIS", "flow": ["consultar_medida"]})
    orch = SenturyOrchestrator(
        planner=ScriptedPlanner([_respond("ok")] * 3), responder=EchoResponder(),
        store=_store(), experience_library=exp)
    await orch.handle_message(AnalysisState.new("s-sem-pre-busca", "u"), "por que caiu?")
    assert not exp.chamadas


async def test_experiencia_ausente_nao_quebra():
    orch = SenturyOrchestrator(
        planner=ScriptedPlanner([_tool_call("consultar_experiencia", consulta="x"), _respond("ok")]),
        responder=EchoResponder(), store=_store(),
        experience_library=_ExpLib(None),
    )
    r = await orch.handle_message(AnalysisState.new("s-l2c", "u"), "por que caiu?")
    assert r["message"]
