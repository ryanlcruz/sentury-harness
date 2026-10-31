"""Aplica prazos por ferramenta para que uma chamada presa não trave o turno.

O cancelamento é cooperativo: uma tarefa síncrona no executor pode continuar
até terminar, mesmo após o abandono da espera. O estouro vira resultado de
erro para o modelo, que pode escolher outro caminho. O prazo padrão é menor
que o orçamento do turno.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Dict

logger = logging.getLogger(__name__)

# Uma ferramenta que passa disto sem declarar prazo proprio esta travada, nao
# lenta. Menor que o orcamento do turno (120s): prazo que estoura depois do turno
# nao protege ninguem.
PRAZO_PADRAO_S = 45.0


def prazo_de(tool: str, argumentos: Any = None) -> float:
    """Quanto esta ferramenta pode demorar: o `prazo_s` declarado (ou o padrão)
    e, com `prazo_por_caractere_s`, mais um tanto por caractere do `texto` ou
    `valor`. Digitar em ritmo de mão um texto longo passa do prazo fixo."""
    try:
        from .registry import TOOL_REGISTRY

        meta = TOOL_REGISTRY.get(tool) or {}
    except Exception:
        meta = {}
    try:
        valor = float(meta.get("prazo_s"))
    except (TypeError, ValueError):
        valor = PRAZO_PADRAO_S
    valor = valor if valor > 0 else PRAZO_PADRAO_S
    try:
        por_caractere = float(meta.get("prazo_por_caractere_s") or 0)
    except (TypeError, ValueError):
        por_caractere = 0.0
    if por_caractere > 0 and isinstance(argumentos, dict):
        texto = argumentos.get("texto") or argumentos.get("valor") or ""
        valor += por_caractere * len(str(texto))
    return valor


def estouro(tool: str, segundos: float) -> Dict[str, Any]:
    """O que o modelo lê quando a chamada não voltou.

    Vai como resultado com `erro`, e não como exceção: é o formato que o resto do
    laço já sabe tratar: vira instrução no histórico e o modelo escolhe outra
    rota.
    """
    return {
        "erro": (
            f"a ferramenta '{tool}' nao respondeu em {segundos:.0f}s e foi abandonada. "
            "Tente outro caminho, ou responda com o que ja tem dizendo o que faltou."
        ),
        "timeout": True,
    }


async def com_prazo(tool: str, chamada: Awaitable[Any], argumentos: Any = None) -> Any:
    """Espera a chamada até o prazo dela; passando disso, devolve o estouro."""
    segundos = prazo_de(tool, argumentos)
    try:
        return await asyncio.wait_for(chamada, timeout=segundos)
    except asyncio.TimeoutError:
        # Cooperativo: a espera foi abandonada. Uma ferramenta sincrona no
        # executor pode continuar ate terminar sozinha: e dizer o contrario
        # seria mentira que o turno seguinte pagaria.
        logger.warning("Ferramenta %s nao respondeu em %.0fs; abandonando a espera.", tool, segundos)
        return estouro(tool, segundos)
