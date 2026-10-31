"""Quanto cada agente já gastou hoje, e se ainda pode trabalhar.

O dia conta a partir da meia-noite local da HQ. A conta sai das tarefas em
disco: não há contador separado para dessincronizar.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

from . import tarefas as _t
from .manifesto import Manifesto


def inicio_do_dia(agora: Optional[float] = None) -> float:
    local = time.localtime(agora if agora is not None else time.time())
    return time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))


def uso_de_hoje(nome: str, agora: Optional[float] = None) -> Dict[str, float]:
    desde = inicio_do_dia(agora)
    custo = turnos = sem_custo = 0.0
    for tarefa in _t.listar(nome):
        if max(tarefa.iniciada_em, tarefa.criada_em) < desde or not tarefa.tentativas:
            continue
        custo += tarefa.custo_usd
        turnos += tarefa.tentativas
        sem_custo += tarefa.turnos_sem_custo
    # O limite em US$ não enxerga os turnos sem custo; o de turnos enxerga todos.
    return {"usd": round(custo, 6), "turnos": turnos, "turnos_sem_custo": sem_custo}


def corte(agente: Manifesto, agora: Optional[float] = None) -> Optional[str]:
    """None quando pode trabalhar; senão o motivo, para a tarefa e para a tela."""
    uso = uso_de_hoje(agente.nome, agora)
    teto_usd = float(agente.orcamento.get("usd_por_dia") or 0)
    teto_turnos = float(agente.orcamento.get("turnos_por_dia") or 0)
    if teto_usd and uso["usd"] >= teto_usd:
        return f"o orçamento de hoje acabou (US$ {uso['usd']:.2f} de {teto_usd:.2f})"
    if teto_turnos and uso["turnos"] >= teto_turnos:
        return f"os turnos de hoje acabaram ({int(uso['turnos'])} de {int(teto_turnos)})"
    return None
