"""Selecao temporaria de setor, isolada por contexto de execucao.

A escolha feita pela interface e persistente e pertence a instalacao. Testes e
jobs nao podem sobrescrever essa escolha global para conseguir executar com outro pacote. Este modulo oferece uma
sobreposicao por ``ContextVar``: ela atravessa ``await`` no mesmo task, sem
vazar para outro task nem escrever em ``~/.sentury/setor.json``.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional


_SETOR_DO_CONTEXTO: ContextVar[Optional[str]] = ContextVar(
    "sentury_setor_do_contexto", default=None
)


def setor_do_contexto() -> Optional[str]:
    """Retorna o override do task atual, ou ``None`` para usar a instalacao."""

    return _SETOR_DO_CONTEXTO.get()


@contextmanager
def usar_setor(nome: str) -> Iterator[None]:
    """Usa ``nome`` somente dentro deste contexto e restaura ao sair."""

    escolhido = str(nome or "").strip()
    if not escolhido:
        raise ValueError("o setor temporario nao pode ser vazio")
    token = _SETOR_DO_CONTEXTO.set(escolhido)
    try:
        yield
    finally:
        _SETOR_DO_CONTEXTO.reset(token)


__all__ = ["setor_do_contexto", "usar_setor"]
