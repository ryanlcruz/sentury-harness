"""Quando o Sentury para para aprender, e com que ferramentas.

A revisão é um turno do próprio Sentury sobre uma cópia da conversa: o mesmo
sistema e a mesma mesa de ferramentas do turno, para o provedor reaproveitar o
cache, e uma pausa no lugar do pedido. Só as ferramentas declaradas com
`aprendizado` no `tools.yaml` respondem; a política recusa o resto.

A cadência conta voltas: cada ferramenta que rodou é uma, e o turno só de
conversa conta como uma, porque é nele que a pessoa costuma corrigir o jeito
de fazer ou contar uma decisão. Quando o próprio turno já guardou algo, a
contagem recomeça.
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

_NA_REVISAO: contextvars.ContextVar[Optional[frozenset]] = contextvars.ContextVar(
    "ferramentas_da_revisao", default=None)
_PERGUNTA = Path(__file__).resolve().parent.parent / "context" / "base" / "REVISAO_DO_APRENDIZADO.md"
_SOBREPOSTAS = _PERGUNTA.with_name("REVISAO_SOBREPOSTAS.md")


def ferramentas_da_revisao() -> Optional[frozenset]:
    """None fora da revisão: aí vale a mesa inteira."""
    return _NA_REVISAO.get()


def _declaradas(*valores: str) -> frozenset:
    from ..tools.registry import TOOL_REGISTRY

    return frozenset(n for n, m in TOOL_REGISTRY.items() if m.get("aprendizado") in valores)


@contextmanager
def em_revisao() -> Iterator[frozenset]:
    permitidas = _declaradas("escreve", "consulta")
    token = _NA_REVISAO.set(permitidas)
    try:
        yield permitidas
    finally:
        _NA_REVISAO.reset(token)


def a_cada() -> int:
    from ..config import settings

    return max(0, int(getattr(settings, "SENTURY_APRENDER_A_CADA", 10) or 0))


def contar(state: Any, resultado: Dict[str, Any]) -> None:
    """Soma as voltas do turno, ou recomeça se ele já aprendeu."""
    ferramentas = list(((resultado or {}).get("harness") or {}).get("ferramentas") or [])
    if set(ferramentas) & _declaradas("escreve"):
        state.voltas_desde_revisao = 0
        return
    state.voltas_desde_revisao = int(getattr(state, "voltas_desde_revisao", 0) or 0) + max(1, len(ferramentas))


def chegou_a_vez(state: Any) -> bool:
    from ..config import settings

    limite = a_cada()
    if not settings.SENTURY_AUTOLEARN or not limite:
        return False
    if int(getattr(state, "voltas_desde_revisao", 0) or 0) < limite:
        return False
    state.voltas_desde_revisao = 0
    return True


def pergunta() -> str:
    """A pausa, e o aviso de skills sobrepostas quando há: o harness avisa, a
    revisão decide se junta."""
    texto = _PERGUNTA.read_text(encoding="utf-8").strip()
    try:
        from ..skills.escrita import sobrepostas

        pares = sobrepostas()
    except Exception:
        logger.debug("Sobreposição de skills não conferida", exc_info=True)
        pares = []
    if not pares:
        return texto
    from ..skills.escrita import texto_da_skill

    # O texto das duas vai junto: comparar não pode custar voltas de carregar.
    blocos = []
    for par in pares:
        a, b = par["skills"]
        blocos.append(f"### {a} e {b} (semelhança {par['semelhanca']})\n\n"
                      f"`{a}`:\n{texto_da_skill(a)}\n\n`{b}`:\n{texto_da_skill(b)}")
    return texto + "\n\n" + _SOBREPOSTAS.read_text(encoding="utf-8").strip().format(pares="\n\n".join(blocos))


async def revisar(orquestrador: Any, state: Any) -> Dict[str, Any]:
    """Roda a pausa sobre uma cópia da conversa; a conversa real não muda."""
    from .state import AnalysisState

    copia = AnalysisState.from_dict(state.to_dict())
    copia.session_id = f"{state.session_id}:revisao"
    copia.tarefa_pendente = None
    antes = len(copia.history)
    with em_revisao():
        resultado = await orquestrador.handle_message(copia, pergunta())
    ferramentas = list(((resultado or {}).get("harness") or {}).get("ferramentas") or [])
    # O que as ferramentas responderam na pausa: é por aqui que se vê por que
    # uma escrita não pegou.
    respostas = [str(m.get("content") or "")[:400] for m in copia.history[antes:]
                 if m.get("role") == "system" and m.get("chamada")]
    logger.info("Revisão do aprendizado em %s: %s", state.session_id, ferramentas or "nada a guardar")
    return {"ferramentas": ferramentas, "mensagem": str((resultado or {}).get("message") or ""),
            "respostas": respostas}
