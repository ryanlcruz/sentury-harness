"""A validação preserva os dados e devolve ao modelo a recusa de entrega."""
from __future__ import annotations

import base64
import logging
import re
from typing import Any

from .grounding import evidence_text, find_ungrounded

logger = logging.getLogger(__name__)


def _texto_visivel(anexo: dict[str, Any]) -> str:
    try:
        texto = base64.b64decode(anexo.get("content_base64") or "").decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""
    texto = re.sub(r"<(style|script)\b[^>]*>.*?</\1\s*>", " ", texto, flags=re.I | re.S)
    texto = re.sub(r"<!--.*?-->|<[^>]+>", " ", texto, flags=re.S)
    return re.sub(r"\s+", " ", texto).strip()


def julgar(state: Any, attachment: Any, reply_text: str, tool_results: list,
           *, pre_turn_had_data: bool, grounding_tools: set) -> tuple[Any, str]:
    if not attachment:
        return attachment, reply_text
    tipo = str(attachment.get("type") or "").lower()
    if tipo not in {"html", "chart_json", "pdf", "xlsx", "csv", "dashboard", "chart"} and "chart" not in tipo:
        return attachment, reply_text
    tem_dado = pre_turn_had_data or any(
        item.get("tool") in grounding_tools
        and not (isinstance(item.get("result"), dict) and item["result"].get("falhou"))
        for item in tool_results or []
    )
    motivo = ""
    if not tem_dado:
        motivo = "não há fonte de dados confirmada; entregar números inventados seria incorreto"
    elif tipo == "html" and attachment.get("content_base64"):
        encontrados = find_ungrounded(_texto_visivel(attachment), evidence_text(state))
        if encontrados.get("currency") or encontrados.get("decimals"):
            motivo = "o HTML contém números sem respaldo nos resultados confirmados"
    if not motivo:
        return attachment, reply_text
    aviso = (f"Artefato {tipo} recusado: {motivo}. Ele não foi entregue. "
             "Considere consultar uma fonte disponível e refazer o material com os resultados "
             "confirmados; se faltar acesso ou informação, explique a lacuna à pessoa.")
    if not any(m.get("content") == aviso for m in state.history):
        state.history.append({"role": "system", "content": aviso})
    logger.warning("Artefato recusado: %s", motivo)
    try:
        from ..observability import record_intervention

        record_intervention("grounding_reject", detail=f"artefato {tipo}: {motivo}")
    except Exception:
        logger.debug("Falha ao registrar a recusa", exc_info=True)
    return None, f"Artefato não entregue: {motivo}."
