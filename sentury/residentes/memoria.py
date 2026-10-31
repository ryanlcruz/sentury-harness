"""A memória do residente como acervo: toda nota fica guardada no `memoria.md`, e o
turno recebe só o que cabe. Pequena, ela vai inteira; grande, vão as notas mais
recentes e as antigas parecidas com o pedido, pelo mesmo caminho das decisões
(sentido com embeddings, palavras sem eles). O resto continua achável por `buscar`.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import registro

TETO_NO_TURNO = 4_000
QUANTAS_RECENTES = 5
QUANTAS_PARECIDAS = 5
QUANTAS_AO_LER = 20


def notas(nome: str) -> List[str]:
    """As notas na ordem em que foram anotadas, cada uma com a data na frente."""
    return [l.strip() for l in registro.ler_memoria(nome).split("\n") if l.strip()]


def _corpo(nota: str) -> str:
    return nota.split(": ", 1)[-1]


def _acervo(lista: List[str]) -> Dict[str, str]:
    return {str(i): _corpo(n) for i, n in enumerate(lista)}


def para_o_turno(nome: str, pedido: str = "") -> str:
    todas = notas(nome)
    if sum(len(n) + 1 for n in todas) <= TETO_NO_TURNO:
        return "\n".join(todas)
    from ..memory.semelhanca import parecidas

    antigas = todas[:-QUANTAS_RECENTES]
    escolhidas = parecidas(pedido, _acervo(antigas), QUANTAS_PARECIDAS) if str(pedido or "").strip() else []
    # Na ordem em que foram anotadas, para a nota mais nova sobre um assunto vir depois da velha.
    linhas = [antigas[i] for i in sorted(int(c) for c in escolhidas)] + todas[-QUANTAS_RECENTES:]
    fora = len(todas) - len(linhas)
    linhas.append(f"(Mais {fora} notas antigas ficaram guardadas fora deste resumo; "
                  "`memoria_do_agente` com `buscar` acha as de um assunto.)")
    return "\n".join(linhas)


def buscar(nome: str, termo: str, limite: int = 5) -> List[str]:
    todas = notas(nome)
    if not str(termo or "").strip():
        return todas[-limite:]
    from ..memory.semelhanca import parecidas

    return [todas[int(c)] for c in parecidas(termo, _acervo(todas), limite, minimo_comuns=1)]


def anotar(nome: str, nota: str) -> Optional[str]:
    """Anota; a nota que diz o mesmo que uma já guardada troca a antiga. Devolve a
    nota trocada, ou None quando somou uma nova."""
    from ..memory import embeddings

    todas = notas(nome)
    igual = embeddings.repetida(" ".join(str(nota or "").split()), _acervo(todas))
    trocada = todas[int(igual)] if igual is not None else None
    registro.anotar_memoria(nome, nota, substitui=_corpo(trocada) if trocada else "")
    return trocada
