"""O canal de eventos ao vivo do turno, alcançável de dentro das ferramentas.

O `_emit` do orquestrador é uma closure do turno; a ferramenta do navegador
roda vários passos dentro de UMA chamada (o roteiro) e precisa avisar cada um
à tela. Passar o callback por parâmetro atravessaria catalog, registry e
roteiro; o ContextVar faz o mesmo sem mudar essas assinaturas, e vale só no
turno que o definiu: dois turnos simultâneos não trocam eventos.
"""
from __future__ import annotations

import contextvars
from typing import Any, Callable, Dict, Optional

EMISSOR: contextvars.ContextVar[Optional[Callable[[Dict[str, Any]], None]]] = \
    contextvars.ContextVar("sentury_emissor_do_turno", default=None)


def emitir(evento: Dict[str, Any]) -> None:
    """Manda o evento para a tela, se houver turno ouvindo. Nunca levanta:
    o aviso não pode derrubar a ação que ele anuncia."""
    fn = EMISSOR.get()
    if fn is None:
        return
    try:
        fn(evento)
    except Exception:
        pass


__all__ = ["EMISSOR", "emitir"]
