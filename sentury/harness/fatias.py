"""Do que é feita a última chamada do planejador, em caracteres.

Sistema e esquema de ferramentas são o prefixo que o provedor pode guardar em
cache; o histórico cresce com a conversa; a última mensagem traz o pedido e o
contexto do turno. A tela mostra as fatias para a pessoa ver o que pesa. Fica
num contextvar: o orquestrador atende turnos ao mesmo tempo.
"""
from __future__ import annotations

import contextvars
import json
from typing import Any, Dict, List, Optional

_ULTIMA: contextvars.ContextVar[Optional[Dict[str, int]]] = contextvars.ContextVar(
    "fatias_da_chamada", default=None)


def _tamanho(mensagem: Dict[str, Any]) -> int:
    conteudo = mensagem.get("content")
    texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo or "", ensure_ascii=False)
    chamadas = mensagem.get("tool_calls")
    return len(texto) + (len(json.dumps(chamadas, ensure_ascii=False)) if chamadas else 0)


def medir(mensagens: List[Dict[str, Any]], ferramentas: Optional[List[Any]] = None) -> Dict[str, int]:
    mensagens = [m for m in mensagens or [] if isinstance(m, dict)]
    sistema = sum(_tamanho(m) for m in mensagens if m.get("role") == "system")
    resto = [m for m in mensagens if m.get("role") != "system"]
    ultima = _tamanho(resto[-1]) if resto else 0
    fatias = {
        "sistema": sistema,
        "ferramentas": len(json.dumps(ferramentas, ensure_ascii=False)) if ferramentas else 0,
        "historico": sum(_tamanho(m) for m in resto[:-1]),
        "pedido_e_contexto": ultima,
    }
    _ULTIMA.set(fatias)
    return fatias


def da_ultima_chamada() -> Optional[Dict[str, int]]:
    return _ULTIMA.get()


def zerar() -> None:
    _ULTIMA.set(None)
