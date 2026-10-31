"""Sem chamada de classificação antes do laço.

Classificar antes cobrava uma chamada de modelo a mais em todo turno, e a
regra de cumprimento por palavra só cobria as línguas da lista. O pedido vai
direto ao modelo do turno.
"""
from pathlib import Path

import pytest

from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.test_orchestrator import CapturePlanner, EchoResponder, _respond, _store


@pytest.mark.parametrize("pedido", ["bom dia", "おはよう", "compare agosto com julho"])
async def test_o_turno_chama_o_modelo_uma_vez(pedido):
    planner = CapturePlanner(_respond("Pronto."))
    orq = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    await orq.handle_message(AnalysisState.new("sem-classificar", "u"), pedido)
    assert len(planner.calls) == 1


def test_nao_ha_modulo_de_classificacao_no_harness():
    pasta = Path(__file__).parents[1] / "sentury" / "harness"
    for nome in ("mini_orchestrator.py", "rule_classifier.py", "classify_shadow.py"):
        assert not (pasta / nome).exists(), nome
