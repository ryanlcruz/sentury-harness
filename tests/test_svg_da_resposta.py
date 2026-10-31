"""O bloco `svg` que o modelo escreve chega à pessoa como ele escreveu.

A tela mostra `svg` como código, com o botão Visualizar; quem desenha é o bloco
`vivo`. Cortar o bloco porque o texto dele lembra um gráfico ("eixo", "série")
apagava o código que a pessoa pediu, e só funcionava em português.
"""
import json

import pytest

from sentury.config import settings
from sentury.data.store import SemDados
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState

GRAFICO = """Evolução da série no eixo do tempo:
```svg
<svg viewBox="0 0 100 40"><g class="axis"></g><rect class="bar" x="10" y="10" width="10" height="30"/></svg>
```"""


class Modelo:
    supports_tools = False
    last_model = "teste:texto"

    async def complete(self, messages, **kwargs):
        return json.dumps({"plan": [], "message": GRAFICO})


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)


async def test_o_bloco_svg_chega_inteiro_mesmo_parecendo_grafico():
    orq = SenturyOrchestrator(planner=Modelo(), responder=Modelo(), store=SemDados())
    resultado = await orq.handle_message(AnalysisState.new("svg", "u"), "me mostra o svg desse gráfico")
    assert "```svg" in resultado["message"]
    assert 'class="axis"' in resultado["message"]
