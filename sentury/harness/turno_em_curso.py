"""Permite interromper o turno em andamento por chat ou atalho global.

O atalho cancela a tarefa a partir de qualquer thread. A parada pedida no chat
espera uma ação mutante terminar, até o prazo limite, para não deixar trabalho
pela metade.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

PRAZO_PARA_PARAR = 30.0

_trava = threading.Lock()
_turnos: Dict[str, Tuple[asyncio.AbstractEventLoop, asyncio.Task]] = {}
_paradas: "set[int]" = set()
# Ferramentas rodando agora, por sessão: (nome, interrompível).
_ferramentas: Dict[str, List[Tuple[str, bool]]] = {}
# Sessões com Parar pedido esperando uma ferramenta não interrompível acabar.
_pedidas: "set[str]" = set()


def registrar(sessao: str, tarefa: asyncio.Task, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    """Chamado pelo stream logo depois de criar a task do turno."""
    loop = loop or tarefa.get_loop()
    with _trava:
        _turnos[str(sessao)] = (loop, tarefa)


def esquecer(sessao: str, tarefa: asyncio.Task) -> None:
    """Só esquece se ainda for ESTA task: um turno novo da mesma sessão pode
    já ter se registrado por cima."""
    with _trava:
        atual = _turnos.get(str(sessao))
        if atual is not None and atual[1] is tarefa:
            del _turnos[str(sessao)]
            _pedidas.discard(str(sessao))
            _ferramentas.pop(str(sessao), None)
        _paradas.discard(id(tarefa))


def parar(sessao: str) -> bool:
    """Cancela o turno da sessão. De qualquer thread. Devolve se havia turno."""
    with _trava:
        atual = _turnos.get(str(sessao))
        if atual is None:
            return False
        loop, tarefa = atual
        if tarefa.done():
            return False
        _paradas.add(id(tarefa))
    try:
        loop.call_soon_threadsafe(tarefa.cancel)
    except RuntimeError:  # loop já fechado: não há mais o que parar
        return False
    return True


def pedir_parada(sessao: str, prazo: Optional[float] = None) -> Dict[str, Any]:
    """O Parar do chat. Devolve `{"havia": bool, "esperando": nome | None}`:
    `esperando` é a ferramenta que vai terminar antes de o turno parar."""
    sessao = str(sessao)
    with _trava:
        atual = _turnos.get(sessao)
        if atual is None or atual[1].done():
            return {"havia": False, "esperando": None}
        loop, tarefa = atual
        _paradas.add(id(tarefa))
        segurando = [nome for nome, pode in _ferramentas.get(sessao, []) if not pode]
        if segurando:
            _pedidas.add(sessao)
    try:
        if not segurando:
            loop.call_soon_threadsafe(tarefa.cancel)
            return {"havia": True, "esperando": None}
        loop.call_soon_threadsafe(loop.call_later, PRAZO_PARA_PARAR if prazo is None else prazo,
                                  _forcar, sessao, tarefa)
    except RuntimeError:
        return {"havia": False, "esperando": None}
    return {"havia": True, "esperando": segurando[0]}


def _forcar(sessao: str, tarefa: asyncio.Task) -> None:
    if not tarefa.done():
        logger.warning("Parar: a ferramenta de %s passou do prazo; cortando o turno.", sessao)
        tarefa.cancel()


def parada_pedida(sessao: str) -> bool:
    with _trava:
        return str(sessao) in _pedidas


@contextmanager
def na_ferramenta(sessao: str, nome: str, interrompivel: bool) -> Iterator[None]:
    """Em volta de cada ferramenta. Com Parar pedido, não começa a próxima; e
    a que não podia ser cortada, quando acaba, para o turno ali."""
    sessao = str(sessao)
    if parada_pedida(sessao):
        raise asyncio.CancelledError()
    item = (nome, interrompivel)
    with _trava:
        _ferramentas.setdefault(sessao, []).append(item)
    try:
        yield
    finally:
        with _trava:
            rodando = _ferramentas.get(sessao, [])
            if item in rodando:
                rodando.remove(item)
    if parada_pedida(sessao):
        raise asyncio.CancelledError()


def foi_parado(tarefa: asyncio.Task) -> bool:
    """O turno acabou porque alguém pediu `parar`, não por queda."""
    with _trava:
        return id(tarefa) in _paradas


def em_curso(sessao: str) -> bool:
    with _trava:
        atual = _turnos.get(str(sessao))
        return atual is not None and not atual[1].done()


__all__ = ["PRAZO_PARA_PARAR", "em_curso", "esquecer", "foi_parado", "na_ferramenta", "parada_pedida",
           "parar", "pedir_parada", "registrar"]
