"""Stubs do filho: operacoes privilegiadas voltam ao pai por RPC."""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Iterable

_url = ""
_token = ""
_permitidas: frozenset[str] = frozenset()


def configurar(url: str, token: str, permitidas: Iterable[str]) -> None:
    global _url, _token, _permitidas
    _url = str(url)
    _token = str(token)
    _permitidas = frozenset(str(nome) for nome in permitidas)


def _chamar(ferramenta: str, *argumentos: Any, **nomeados: Any) -> Any:
    if ferramenta not in _permitidas or not _url or not _token:
        raise RuntimeError(f"ferramenta RPC indisponivel: {ferramenta}")
    corpo = json.dumps({
        "ferramenta": ferramenta,
        "argumentos": list(argumentos),
        "nomeados": nomeados,
    }, ensure_ascii=False).encode("utf-8")
    pedido = urllib.request.Request(
        _url,
        data=corpo,
        headers={
            "Authorization": f"Bearer {_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(pedido, timeout=20) as resposta:
        carga = json.loads(resposta.read().decode("utf-8"))
    if not carga.get("ok"):
        raise RuntimeError(str(carga.get("erro") or "falha no RPC"))
    return carga.get("resultado")


def gif_search(query: str) -> str:
    return str(_chamar("gif_search", query))


def arxiv_search(query: str, max_results: int = 5) -> list:
    resultado = _chamar("arxiv_search", query, max_results=max_results)
    return resultado if isinstance(resultado, list) else []
