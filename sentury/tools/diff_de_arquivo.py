"""O diff de um arquivo que a Sentury criou ou editou, para a conversa mostrar.

`escrever_arquivo` e `editar_arquivo` devolvem o diff em `diff_para_a_tela`; o
`execute_tool` o tira dali antes de o resultado ir ao modelo (ele não precisa
reler o que acabou de escrever, e o diff inteiro gastaria contexto) e o manda
à tela como evento `diff`. O Processo do turno guarda, então ele sobrevive a
recarregar a conversa.
"""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

CONTEXTO = 3
TETO_DE_LINHAS = 400
TETO_DE_LINHA = 400


def _cortar(texto: str) -> str:
    return texto if len(texto) <= TETO_DE_LINHA else texto[:TETO_DE_LINHA] + "…"


def montar(caminho: str, antes: str, depois: str, *, criado: bool = False) -> Optional[Dict[str, Any]]:
    """Os trechos que mudaram, com número de linha dos dois lados.

    Cada linha é `[tipo, texto, linha_antes, linha_depois]`, com tipo `+`, `-`
    ou ` ` (contexto). Passando de `TETO_DE_LINHAS`, corta e diz que cortou.
    Arquivo que não é texto (tem byte nulo) não tem diff.
    """
    if "\x00" in antes or "\x00" in depois:
        return None
    velhas, novas = antes.splitlines(), depois.splitlines()
    trechos: List[Dict[str, Any]] = []
    adicionadas = removidas = total = 0
    cortado = False
    for grupo in difflib.SequenceMatcher(None, velhas, novas, autojunk=False).get_grouped_opcodes(CONTEXTO):
        a0, b0 = grupo[0][1], grupo[0][3]
        a1, b1 = grupo[-1][2], grupo[-1][4]
        linhas: List[list] = []
        for tag, i1, i2, j1, j2 in grupo:
            if tag == "equal":
                for k in range(i2 - i1):
                    linhas.append([" ", _cortar(velhas[i1 + k]), i1 + k + 1, j1 + k + 1])
                continue
            if tag in ("replace", "delete"):
                for k in range(i1, i2):
                    linhas.append(["-", _cortar(velhas[k]), k + 1, None])
                removidas += i2 - i1
            if tag in ("replace", "insert"):
                for k in range(j1, j2):
                    linhas.append(["+", _cortar(novas[k]), None, k + 1])
                adicionadas += j2 - j1
        if total + len(linhas) > TETO_DE_LINHAS:
            linhas = linhas[:max(0, TETO_DE_LINHAS - total)]
            cortado = True
        total += len(linhas)
        if linhas:
            trechos.append({"cabecalho": f"@@ -{a0 + 1},{a1 - a0} +{b0 + 1},{b1 - b0} @@", "linhas": linhas})
        if cortado:
            break
    if cortado:
        # As contagens dizem o tamanho real, mesmo com o trecho cortado.
        adicionadas = removidas = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, velhas, novas, autojunk=False).get_opcodes():
            if tag in ("replace", "delete"):
                removidas += i2 - i1
            if tag in ("replace", "insert"):
                adicionadas += j2 - j1
    return {"arquivo": caminho, "criado": criado, "adicionadas": adicionadas, "removidas": removidas,
            "trechos": trechos, "cortado": cortado}


__all__ = ["montar"]
