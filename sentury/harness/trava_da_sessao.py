"""Um turno por conversa de cada vez.

Com o goal, a conversa passa a ter dois autores: a pessoa e o executor que
continua sozinho. Os dois carregam o estado, rodam o turno e gravam; sem a
trava, o que gravasse por ultimo apagaria o turno do outro. A mensagem da
pessoa espera o turno automatico em curso terminar e entra no seguinte.

So vale dentro de um processo: o servidor do Sentury roda um so.
"""
from __future__ import annotations

import asyncio
from typing import Dict

_TRAVAS: Dict[str, asyncio.Lock] = {}


def da(session_id: str) -> asyncio.Lock:
    trava = _TRAVAS.get(session_id)
    if trava is None:
        trava = _TRAVAS[session_id] = asyncio.Lock()
    return trava


def ocupada(session_id: str) -> bool:
    trava = _TRAVAS.get(session_id)
    return bool(trava and trava.locked())


def esquecer(session_id: str) -> None:
    """Conversa apagada: a trava livre sai do mapa."""
    trava = _TRAVAS.get(session_id)
    if trava is not None and not trava.locked():
        _TRAVAS.pop(session_id, None)
