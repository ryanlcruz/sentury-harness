"""Reúne o parecer opcional do conselho antes da resposta.

Ele avalia o que já foi observado e alimenta o contexto da resposta. Os
subagentes são uma ferramenta do laço (`tools/subagentes.py`).
Um turno sem pareceres pode terminar normalmente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from .conselho_do_turno import consultar


@dataclass
class Pareceres:
    """O que a fase produziu. `contexto` é o único texto que segue para o redator."""

    contexto: str = ""
    analise: Any = None
    # Passos a anexar na deliberação do turno (o que apareceu, não o que rodou).
    passos: List[Dict[str, Any]] = field(default_factory=list)
    # Quem entrega documento neste turno: decide se o plano vira anexo mais adiante.
    plano_no_turno: bool = False


async def colher(
    orquestrador: Any,
    *,
    user_message: str,
    state: Any,
    tool_results: List[Dict[str, Any]],
    telemetry: Dict[str, Any],
    decision_log: Dict[str, Any],
    progress_cb: Any,
    emit: Any,
) -> Pareceres:
    """Roda o conselho e devolve só o que a resposta precisa.

    O conselho é caro e tem duas guardas determinísticas que ficam onde estavam
    (dentro de `conselho_do_turno.consultar`): não roda sobre dado vazio ou falho, senão
    os conselheiros alucinam; e não roda quando o turno JÁ é a entrega: não cabe
    conselho sobre a própria entrega.
    """
    from ..domains.do_setor import entregas as _entregas_do_setor

    # Quais ferramentas entregam arquivo é declaração do SETOR, não do motor.
    entregam = {n for n, e in _entregas_do_setor().items() if e.get("arquivo")}
    out = Pareceres(
        plano_no_turno=any(str(tr.get("tool")) in entregam for tr in tool_results),
    )

    out.contexto, out.analise = await consultar(orquestrador,
        user_message, state, tool_results, telemetry, decision_log,
    )

    return out
