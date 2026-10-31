"""Quando o caminho não existe, o que existe ao lado.

O caso real: pediram `robinbadit`, a pasta chama `Robinbendit`, e a ferramenta
respondeu "não é uma pasta". O agente então anunciou a falha ao usuário (que
tinha só errado uma letra) quando a resposta estava na pasta irmã.

Errar o nome é o normal, não a exceção: gente digita rápido, modelo lembra
aproximado, e no Windows ainda entra a caixa alta. Quem sabe os nomes de
verdade é o disco, então a sugestão sai daqui e não de um palpite do modelo.
"""
from __future__ import annotations

import difflib
import logging
import unicodedata
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# Mais que isto não ajuda a escolher: vira outra lista para o modelo ler.
QUANTAS = 5
# Abaixo disto a "sugestão" é outra palavra, e sugerir errado é pior que calar.
SEMELHANCA = 0.6


def _nua(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", str(texto or ""))
    return sem.encode("ascii", "ignore").decode("ascii").lower()


def sugestoes(alvo: Path, quantas: int = QUANTAS) -> List[str]:
    """Nomes irmãos parecidos com o que foi pedido, do mais próximo ao menos.

    Compara sem acento e sem caixa porque é assim que o erro acontece: `Área`
    virando `Area`, `Robinbendit` virando `robinbadit`.
    """
    try:
        pai = alvo.parent
        if not pai.is_dir():
            return []
        vizinhos = [item.name for item in pai.iterdir()]
    except (OSError, ValueError):
        logger.debug("Nao consegui olhar a pasta de %s", alvo, exc_info=True)
        return []
    if not vizinhos:
        return []

    procurado = _nua(alvo.name)
    por_nua = {}
    for nome in vizinhos:
        por_nua.setdefault(_nua(nome), nome)

    perto = difflib.get_close_matches(procurado, list(por_nua), quantas, SEMELHANCA)
    # Quem contém o pedido inteiro entra mesmo com semelhança baixa: `robin`
    # dentro de `Robinbendit` é acerto, e a razão de Ratcliff não vê isso.
    for chave, nome in por_nua.items():
        if len(perto) >= quantas:
            break
        if chave not in perto and procurado and procurado in chave:
            perto.append(chave)
    return [por_nua[chave] for chave in perto]


def com_sugestao(erro: str, alvo: Path) -> str:
    """A mensagem de erro com o "você quis dizer" grudado, quando há um."""
    perto = sugestoes(alvo)
    if not perto:
        return erro
    return f"{erro}. Existe ao lado: {', '.join(perto)}"
