"""A ferramenta `subagentes`: o modelo pede pareceres independentes sobre a
evidência que o turno já levantou e junta as respostas na mesma volta.

O coordenador vem do orquestrador, que é quem tem o provedor do turno.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_COORDENADOR: Optional[Any] = None


def registrar(coordenador: Any) -> None:
    global _COORDENADOR
    _COORDENADOR = coordenador


async def consultar(state: Any, argumentos: Dict[str, Any]) -> Dict[str, Any]:
    from ..harness.emissor import emitir

    pedido = " ".join(str(argumentos.get("pedido") or "").split())
    if not pedido:
        return {"ok": False, "erro": "diga em `pedido` o que os subagentes devem analisar"}
    if _COORDENADOR is None or not getattr(_COORDENADOR, "enabled", True):
        return {"ok": False, "erro": "os subagentes estão desligados nesta instalação (SENTURY_SUBAGENTS_BETA)"}
    papeis: List[str] = [str(p) for p in (argumentos.get("papeis") or []) if str(p).strip()]
    relatorio = await _COORDENADOR.consultar(
        pedido, state, papeis=papeis, quantos=int(argumentos.get("quantos") or 0), emit=emitir)
    pareceres = [{"papel": r.get("role"), "parecer": r.get("summary")}
                 for r in relatorio["results"] if r.get("status") == "completed" and r.get("summary")]
    falharam = [{"papel": r.get("role"), "motivo": r.get("status")}
                for r in relatorio["results"] if r.get("status") != "completed"]
    return {"ok": bool(pareceres), "pareceres": pareceres, "falharam": falharam, "relatorio": relatorio,
            **({} if pareceres else {"erro": "nenhum subagente devolveu parecer"})}
