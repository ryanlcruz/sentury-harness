"""Quanto um texto novo se parece com os que já estão guardados, sem modelo.

Compara pelo radical das palavras (as cinco primeiras letras aproximam flexões
e línguas próximas: diagramas, diagrams). Cada radical pesa pelo quanto é raro
no acervo, então palavra que aparece em quase tudo ("usar", "dados") quase não
conta, sem lista de palavras de uma língua. Uma palavra só em comum é
coincidência (contrato, controlar): pede pelo menos duas.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple


def radicais(texto: str) -> set:
    from ..skills.skill_discovery import _tokens

    return {t[:5] for t in _tokens(texto) if len(t) > 2}


def semelhantes(novo: str, acervo: Dict[str, str], *, corte: float = 0.25, minimo_comuns: int = 2,
                limite: int = 3) -> List[Tuple[str, float]]:
    """Os nomes do acervo parecidos com `novo`, do mais parecido ao menos."""
    if not acervo:
        return []
    textos = {nome: radicais(texto) for nome, texto in acervo.items()}
    total = len(textos)
    frequencia: Dict[str, int] = {}
    for palavras in textos.values():
        for p in palavras:
            frequencia[p] = frequencia.get(p, 0) + 1

    def peso(p: str) -> float:
        return math.log((total + 1) / (frequencia.get(p, 0) + 1)) + 1.0

    nova = radicais(novo)
    achados = []
    for nome, palavras in textos.items():
        comuns = palavras & nova
        menor = min(sum(peso(p) for p in palavras), sum(peso(p) for p in nova))
        if len(comuns) < minimo_comuns or not menor:
            continue
        nota = sum(peso(p) for p in comuns) / menor
        if nota >= corte:
            achados.append((nome, round(nota, 2)))
    achados.sort(key=lambda a: a[1], reverse=True)
    return achados[:limite]


def parecidas(texto: str, acervo: Dict[str, str], limite: int, minimo_comuns: int = 2) -> List[str]:
    """Pelo sentido quando há modelo de embeddings escolhido; pelas palavras quando não
    há ou ele falhou, para a lembrança não sumir do turno por causa do provedor."""
    from . import embeddings

    por_sentido = embeddings.semelhantes(texto, acervo, limite=limite)
    if por_sentido is not None:
        return [nome for nome, _ in por_sentido]
    return [nome for nome, _ in semelhantes(texto, acervo, limite=limite, minimo_comuns=minimo_comuns)]
