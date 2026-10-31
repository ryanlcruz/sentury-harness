"""O stop no meio da compactação jogava o resumo inteiro fora.

`manage` chamava o modelo e só **depois** trocava `state.history`. O botão de
parar aborta a requisição e o `await` morre antes da troca: o resumo ia para o
lixo e o turno seguinte recompactava do zero, pagando outra chamada.

O diário grava o resumo assim que ele sai, com a identidade do snapshot. Quem
recompactar o mesmo histórico acha o resultado pronto.
"""
import pytest

from sentury.harness.context_budget import ContextBudgetManager
from sentury.harness.state import AnalysisState, ConversationState


class _Contextualizador:
    """Conta quantas vezes o modelo foi chamado: é o que está em jogo."""

    def __init__(self):
        self.chamadas = 0

    async def summarize_and_extract(self, mensagens, estado=None):
        self.chamadas += 1
        return f"resumo {self.chamadas}", (estado or ConversationState())


def _estado(sessao: str, quantas: int = 40) -> AnalysisState:
    st = AnalysisState.new(sessao, "u")
    st.history = [{"role": "user", "content": f"mensagem {i} " + "x" * 400}
                  for i in range(quantas)]
    return st


@pytest.mark.asyncio
async def test_o_mesmo_historico_nao_paga_duas_chamadas():
    motor = _Contextualizador()
    orcamento = ContextBudgetManager(contextualizer=motor)

    assert await orcamento.manage(_estado("s-igual")) is True
    assert motor.chamadas == 1

    # Mesma sessão, mesmo histórico: é o cenário do stop seguido de retomada.
    assert await orcamento.manage(_estado("s-igual")) is True
    assert motor.chamadas == 1, "o resumo tinha que vir do diário"


@pytest.mark.asyncio
async def test_sessao_diferente_nao_reaproveita():
    """Identidade é por sessão e por snapshot: reaproveitar entre conversas
    entregaria o resumo de um usuário para outro."""
    motor = _Contextualizador()
    orcamento = ContextBudgetManager(contextualizer=motor)
    await orcamento.manage(_estado("s-um"))
    await orcamento.manage(_estado("s-dois"))
    assert motor.chamadas == 2


@pytest.mark.asyncio
async def test_diario_quebrado_nao_derruba_o_turno(monkeypatch):
    """Perder o reaproveitamento é barato; perder o turno não é."""
    import sentury.harness.compactacao_persistente as cp

    def _explode(*a, **k):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(cp, "DiarioDeCompactacao", _explode)
    motor = _Contextualizador()
    assert await ContextBudgetManager(contextualizer=motor).manage(_estado("s-ruim")) is True
    assert motor.chamadas == 1
