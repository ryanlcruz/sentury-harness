"""A observação proativa: o setor diz o que é notável no último resultado de
análise, e o modelo só redige. Os números ficam travados: reescrita com número
que não estava no fato é descartada, e vale o texto do setor."""
from __future__ import annotations

import logging
import re
import sys
from typing import Any, Dict, Optional

from ..context.base import _texto_base
from ..llm.action_parser import extract_plain_text

logger = logging.getLogger(__name__)


def derivar(tool: Optional[str], result: Any) -> Optional[Dict[str, str]]:
    """A observação do setor ativo sobre o resultado, ou None. Sem setor não há:
    o generalista não sabe o que é notável num NPS."""
    if not isinstance(result, dict):
        return None
    from ..domains.do_setor import insight_proativo

    return insight_proativo(tool, result)


def numeros(texto: str) -> set:
    raw = re.findall(r"\d+(?:[.,]\d+)?", str(texto or "").replace("−", "-"))
    return {n.replace(",", ".") for n in raw}


async def polir(insight: Optional[Dict[str, str]], responder: Any) -> Optional[Dict[str, str]]:
    """A redação melhorada, ou o insight como veio quando a reescrita falha ou
    traz número que o original não tinha."""
    if not insight or "pytest" in sys.modules:  # nos testes, não gasta modelo
        return insight
    base = str(insight.get("text") or "")
    if not base:
        return insight
    msgs = [{"role": "system", "content": _texto_base("POLIR_INSIGHT")},
            {"role": "user", "content": base}]
    try:
        # A redação do card é secundária: nunca gasta o modelo forte.
        from robinbandit.sentury import no_ultra

        with no_ultra():
            raw = await responder.complete(msgs, temperature=0.4)
        novo = extract_plain_text(raw).strip().strip('"').strip()
        if novo and len(novo) >= 20 and numeros(novo).issubset(numeros(base)):
            return {**insight, "text": novo}
    except Exception as exc:
        logger.debug("A redação do insight proativo falhou; fica o texto do setor: %s", exc)
    return insight
