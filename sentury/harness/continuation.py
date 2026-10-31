"""Contexto para o modelo retomar depois de uma ação recusada."""
from __future__ import annotations


def registrar_bloqueio(state, tool, decision, log):
    """Devolve a recusa ao modelo sem escolher a próxima ferramenta."""
    from ..llm.prompts import build_block_instruction

    log["harness_allowed"] = decision.allowed
    log["harness_reason"] = decision.reason
    state.history.append({
        "role": "system",
        "content": build_block_instruction(tool, decision.missing, state, decision.reason),
    })
