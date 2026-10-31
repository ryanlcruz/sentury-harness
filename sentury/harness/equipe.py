"""Vários residentes propostos no mesmo plano viram um cartão só.

Um `criar_agente` pausa o turno no cartão e o resto do plano não roda. Com três
agentes no plano, eram três idas e voltas, e uma recusa no meio parava as
outras. Aqui o primeiro pedido leva a equipe inteira; a pessoa marca quem entra
e cada marcado é aprovado com o próprio comando (`criar_agente <nome>`), o
mesmo que a ferramenta confere ao criar.

A equipe chega de dois jeitos: em `colegas` dentro da mesma chamada, que é o que
funciona com provedor que só entrega uma chamada por resposta, ou em várias
chamadas no mesmo plano.
"""
from __future__ import annotations

from typing import Any, Dict, List


def comando(argumentos: Dict[str, Any]) -> str:
    return f"criar_agente {str(argumentos.get('nome') or '').strip().lower()}"


def _residentes(argumentos: Dict[str, Any]) -> List[Dict[str, Any]]:
    """O residente da chamada e os `colegas` que vieram nela, cada um sem a lista."""
    argumentos = dict(argumentos or {})
    colegas = argumentos.pop("colegas", None) or []
    return [argumentos] + [dict(c) for c in colegas if isinstance(c, dict)]


def da_equipe(argumentos: Dict[str, Any], plano: List[Dict[str, Any]], indice: int) -> List[Dict[str, Any]]:
    """O residente que parou o turno, os colegas da mesma chamada e os outros
    `criar_agente` que vinham depois dele no plano, sem repetir nome."""
    chamadas = [argumentos] + [
        passo.get("arguments") or {} for passo in (plano or [])[indice + 1:]
        if isinstance(passo, dict) and passo.get("tool") == "criar_agente"
    ]
    membros, nomes = [], set()
    for args in (r for chamada in chamadas for r in _residentes(chamada)):
        nome = str((args or {}).get("nome") or "").strip().lower()
        if nome and nome not in nomes:
            nomes.add(nome)
            membros.append(dict(args))
    return membros


def aprovados(equipe: List[Dict[str, Any]], sessao: str) -> List[Dict[str, Any]]:
    """Quem a pessoa marcou no cartão: o comando dele já está liberado."""
    from ..exec.politica import avaliar

    saida = []
    for membro in equipe or []:
        try:
            decisao = avaliar(comando(membro), sessao, checar_alvo=False, na_hora=True, consumir=False)
        except Exception:
            continue
        if decisao.get("permitido"):
            saida.append(membro)
    return saida


def linha(aprovada: List[Dict[str, Any]], equipe: List[Dict[str, Any]]) -> str:
    """O fato para o modelo: quem a pessoa aprovou e quem ficou de fora."""
    nomes = ", ".join(str(m.get("nome")) for m in aprovada)
    fora = [str(m.get("nome")) for m in equipe if m not in aprovada]
    texto = f"A pessoa aprovou criar {nomes}; o harness cria agora, sem precisar de outra chamada."
    if fora:
        texto += f" Ficaram de fora porque ela desmarcou: {', '.join(fora)}. Não proponha de novo sem ela pedir."
    return texto
