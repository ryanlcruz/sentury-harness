"""Limpa e redige a saída antes do corte, que poderia deixar partes de chaves."""
from __future__ import annotations

import re
from typing import Tuple
from .segredos import redigir_segredos, tem_segredo

_ANSI = re.compile(r"\x1B(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])")



def limpar_ansi(texto: str) -> str:
    return _ANSI.sub("", texto or "")




def truncar_pelas_pontas(texto: str, teto: int, *, cabeca: float = 0.4) -> Tuple[str, bool]:
    """Guarda o comeco e o fim, que e onde mora a informacao.

    Cortar so o fim perde a linha de erro, que quase sempre e a ultima; cortar
    so o comeco perde o comando e o cabecalho. O meio de uma saida gigante e
    justamente a parte repetitiva.
    """
    bruto = texto or ""
    if teto <= 0 or len(bruto) <= teto:
        return bruto, False
    fatia_cabeca = max(1, int(teto * cabeca))
    fatia_cauda = max(1, teto - fatia_cabeca)
    omitidos = len(bruto) - fatia_cabeca - fatia_cauda
    return (
        f"{bruto[:fatia_cabeca]}\n"
        f"[... {omitidos} caracteres omitidos no meio ...]\n"
        f"{bruto[-fatia_cauda:]}",
        True,
    )


def preparar(texto: str, teto: int) -> Tuple[str, bool]:
    """Redigir antes do corte evita deixar só um fragmento de credencial."""
    seguro = redigir_segredos(limpar_ansi(texto))
    return truncar_pelas_pontas(seguro, teto)
