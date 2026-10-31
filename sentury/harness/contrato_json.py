"""Repara respostas de planejadores que ainda devolvem ações em JSON textual.

Provedores sem chamadas nativas de ferramenta dependem desse formato. Quando o
JSON é inválido, uma nova chamada pede a estrutura correta; chamadas nativas
não precisam desse reparo.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple
from .chamada_da_volta import completar, ler_payload

logger = logging.getLogger(__name__)

PEDIDO_DE_REPARO = (
    "A resposta anterior não pôde ser lida pelo protocolo textual. "
    "Para continuar, devolva uma ação JSON válida, sem prosa em volta: "
    '{"plan":[{"tool":"...","arguments":{}}]} '
    'ou {"action":"respond","message":"..."}, caso não precise de ferramenta.'
)


async def reparar(
    orquestrador: Any,
    *,
    contract: str,
    messages: List[Dict[str, Any]],
    complexity: Any,
) -> Tuple[str, Dict[str, Any], str]:
    """Uma tentativa de reparo. Devolve `(raw, data, contract)`.

    Uma só: se o modelo errou o formato duas vezes, insistir é gastar a terceira
    chamada pelo mesmo motivo.
    """
    logger.warning("Planner returned %s; requesting one JSON-only repair.", contract)
    orquestrador.turno.reparos_json = orquestrador.turno.reparos_json + 1
    pedido = list(messages) + [{"role": "system", "content": PEDIDO_DE_REPARO}]
    raw = await completar(orquestrador, pedido, complexity)
    data, reparado = ler_payload(raw)
    return raw, data, ("repaired" if reparado == "ok" else reparado)
