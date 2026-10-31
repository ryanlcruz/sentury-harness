"""O encerramento identifica a conta e conserva a tentativa na telemetria."""
import pytest

from robinbandit.providers import ReinforcedProvider
from robinbandit.providers.erro_cli import classificar_cli
from robinbandit.routing.sentury import ChainProvider, use_ultra_provider, clear_ultra_provider
from robinbandit.state.atividade import Atividade
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.test_orchestrator import EchoResponder, _store


async def test_turno_com_limite_no_dedicado_explica_e_mede(monkeypatch):
    from sentury.config import settings
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)

    class Conta:
        name = "claude_code"
        models = ["haiku"]
        supports_tools = True
        last_attempted_model = "claude_code:haiku"

        async def complete(self, messages, temperature=0.2, tools=None, **kwargs):
            raise classificar_cli(RuntimeError("You've hit your limit token-privado-exemplo"), "claude", self.name)

    grupo = ReinforcedProvider([Conta()], name="ultra_max")
    atividade = Atividade()
    planner = ChainProvider([grupo], activity=atividade)
    planner.router.order = lambda *args, **kwargs: [grupo]
    orq = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    token = use_ultra_provider(grupo)
    try:
        saida = await orq.handle_message(AnalysisState.new("falha", "pessoa"), "Liste os arquivos de trabalho")
    finally:
        clear_ultra_provider(token)
    texto = saida["message"]
    assert "Claude Code" in texto and "limite da assinatura" in texto
    assert "troque o modelo" in texto and "token-privado-exemplo" not in str(saida)
    assert saida["telemetry"]["provider"] == "claude_code"
    assert saida["telemetry"]["model"] == "claude_code:haiku"
    assert atividade.resumo()[0]["provedor"] == "claude_code"
