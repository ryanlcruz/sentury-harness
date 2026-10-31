"""Confere a entrega existente sem executar ações depois da resposta."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from .artefato_do_turno import recusar_artefato_sem_lastro, tirar_html_repetido


async def aplicar(
    orquestrador: Any,
    *,
    user_message: str,
    state: Any,
    attachment: Optional[Dict[str, Any]],
    reply_text: str,
    tool_results: List[Dict[str, Any]],
    pre_turn_had_data: bool,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Devolve o par `(anexo, texto)` já processado."""
    # Se o HTML virou anexo (card), o bloco ```html``` sai da mensagem: senão o
    # front mostra dois previews, o inline e o card.
    reply_text = tirar_html_repetido(reply_text, attachment)

    # O anexo precisa de lastro nos resultados, mesmo quando a resposta parece convincente.
    return recusar_artefato_sem_lastro(orquestrador,
        state, attachment, reply_text, tool_results,
        pre_turn_had_data=pre_turn_had_data,
    )
