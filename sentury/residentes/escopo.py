"""O turno vestido de agente: quem está falando e o que ele pode usar.

É a porta que o harness enxerga dos residentes. O orquestrador é o mesmo do
Sentury; o agente do turno vive num contextvar, e o schema que vai ao modelo e
a policy que decide a chamada leem dele, sem o estado da conversa precisar
saber de residentes. O texto da identidade mora em `identidade.py`.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from .manifesto import Manifesto


_AGENTE: contextvars.ContextVar[Optional[Manifesto]] = contextvars.ContextVar(
    "agente_residente", default=None)
# A tarefa que o residente está fazendo: pedido a colega sai dela.
_TAREFA: contextvars.ContextVar[Any] = contextvars.ContextVar("tarefa_do_residente", default=None)


def agente_do_turno() -> Optional[Manifesto]:
    return _AGENTE.get()


def tarefa_do_turno() -> Any:
    return _TAREFA.get()


def ferramentas_permitidas() -> Optional[set]:
    """None fora de turno de agente: aí vale a mesa inteira do Sentury.

    O núcleo do Sentury não entra: ele traz o shell, e o residente só usa o
    que está no manifesto mais o que o `tools.yaml` dá a todo residente."""
    agente = _AGENTE.get()
    if agente is None:
        return None
    from ..tools.registry import TOOL_REGISTRY, de_todo_residente, so_residente

    proprias = {n for n, m in TOOL_REGISTRY.items() if so_residente(m) or de_todo_residente(m)}
    return set(agente.ferramentas) | proprias


def pode_usar(ferramenta: str) -> bool:
    permitidas = ferramentas_permitidas()
    return permitidas is None or ferramenta in permitidas


@contextmanager
def vestido(agente: Manifesto, tarefa: Any = None) -> Iterator[Manifesto]:
    token = _AGENTE.set(agente)
    token_tarefa = _TAREFA.set(tarefa)
    try:
        yield agente
    finally:
        _TAREFA.reset(token_tarefa)
        _AGENTE.reset(token)


def nome_visivel(agente: Manifesto) -> str:
    return agente.nome[:1].upper() + agente.nome[1:]


def quem_e() -> str:
    """A primeira linha do prompt: o Sentury, ou o residente deste turno."""
    agente = _AGENTE.get()
    if agente is None:
        return "Você é o Sentury."
    return f"Você é {nome_visivel(agente)}, {agente.papel}: um agente residente criado pelo Sentury."
