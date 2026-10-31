"""Quando o pedido não cabe em provedor nenhum: compactar e tentar de novo.

A cadeia do RobinBandit levanta `FalhaDaCadeia` com o tipo de cada falha.
Se TODOS recusaram por tamanho (413, contexto estourado), trocar de provedor
não resolve e repetir o mesmo pedido também não: o que resolve é um pedido
menor. Antes, o planner engolia o erro e seguia sem ferramentas, e a resposta
final batia no mesmo limite e virava "tive um problema, tente de novo".

Só tamanho. `content_policy` também é "da requisição", mas compactar não
muda o que a política recusou: tentar de novo só gastaria outra rodada.

Uma tentativa. Se a conversa já é curta demais para compactar, ou se o que
não cabe é a última mensagem (que a compactação nunca corta), a segunda
recusa sobe como subiria a primeira.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional, Tuple, TypeVar

from .caixa_do_turno import marcar_vistas

logger = logging.getLogger(__name__)

COMPACTAVEIS = frozenset({"request_too_large", "context_length"})

T = TypeVar("T")


def _falha_da_cadeia(exc: Optional[BaseException], limite: int = 4) -> Optional[BaseException]:
    """A `FalhaDaCadeia` na corrente da exceção. Por forma, não por import:
    o harness não depende da classe do plugin, só do que ela carrega."""
    for _ in range(limite):
        if exc is None:
            return None
        if isinstance(getattr(exc, "tipos", None), list):
            return exc
        exc = exc.__cause__ or exc.__context__
    return None


def pede_compactar(exc: BaseException) -> bool:
    """Todos os provedores recusaram o pedido por TAMANHO."""
    falha = _falha_da_cadeia(exc)
    if falha is None:
        return False
    tipos = falha.tipos
    return bool(tipos) and all(t in COMPACTAVEIS for t in tipos)


async def compactar_para_caber(state: Any, gerente: Any) -> bool:
    """Compacta sem olhar a régua. Falhar aqui não derruba o turno: sem
    compactação, a recusa original é o que sobe."""
    from .emissor import emitir

    try:
        return bool(await gerente.manage(state, progress_cb=emitir, forcar=True))
    except Exception:
        logger.warning("Compactação depois de pedido grande demais falhou.", exc_info=True)
        return False


async def chamar_cabendo(
    state: Any,
    gerente: Any,
    montar: Callable[[], Any],
    chamar: Callable[[Any], Awaitable[T]],
) -> Tuple[T, Any]:
    """`chamar(montar())`; recusado por tamanho, compacta, remonta e tenta
    uma vez mais. Devolve a resposta e as mensagens que a produziram.

    `montar` lê o `state.history` de novo: as mensagens da segunda tentativa
    saem do histórico já compactado, não de uma cópia da primeira.
    """
    mensagens = montar()
    try:
        return _viu(state, await chamar(mensagens), mensagens), mensagens
    except Exception as exc:
        if not pede_compactar(exc):
            raise
        # O primeiro remédio é menos ferramenta: o catálogo inteiro pode ser o que
        # não coube numa janela pequena. Esquema resumido não serve, ele é o contrato.
        from .descoberta import passar_para_sob_demanda

        if passar_para_sob_demanda():
            logger.info("O catálogo inteiro não coube: o turno segue com carga sob demanda.")
            mensagens = montar()
            try:
                return _viu(state, await chamar(mensagens), mensagens), mensagens
            except Exception as menor:
                if not pede_compactar(menor):
                    raise
        if not await compactar_para_caber(state, gerente):
            logger.warning("Pedido grande demais para todos os provedores e nada a compactar.")
            raise
        logger.info("Pedido grande demais para todos os provedores: compactado, tentando de novo.")
    mensagens = montar()
    return _viu(state, await chamar(mensagens), mensagens), mensagens


def _viu(state: Any, resposta: T, mensagens: Any) -> T:
    """A chamada voltou: a orientação que estava nas mensagens foi vista
    (ver harness/caixa_do_turno.py)."""
    marcar_vistas(state, mensagens)
    return resposta


__all__ = ["COMPACTAVEIS", "chamar_cabendo", "compactar_para_caber", "pede_compactar"]
