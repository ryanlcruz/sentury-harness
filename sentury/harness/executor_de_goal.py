"""Quem continua o goal sozinho, turno apos turno, ate cumprir ou parar.

Uma tarefa asyncio por goal ativo. A cada volta: relê o goal (a pessoa pode ter
pausado pela tela), confere o limite, conta o turno e roda um turno com a
mensagem de continuacao. O turno em si e do `main` (`configurar(rodar)`), que
ja sabe carregar a conversa, aplicar o modo e gravar.

Para sozinho, com o motivo no goal, quando:

- o agente declara cumprido (o goal sai de `ativo`: a pessoa confirma);
- o turno pede autorizacao ou faz uma pergunta: sem resposta, o proximo turno
  so repetiria o pedido;
- o limite de turnos ou de horas estoura;
- `MAX_FALHAS` turnos seguidos falham (provedor fora, cota);
- `MAX_SEM_PROGRESSO` turnos seguidos nao rodam ferramenta nem marcam marco:
  o agente esta so conversando consigo mesmo, e isso queima cota a noite toda.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Dict, Optional

from ..memory import goals as _goals

logger = logging.getLogger(__name__)

Rodar = Callable[[_goals.Goal, str], Awaitable[Dict[str, Any]]]

MAX_FALHAS = 3
MAX_SEM_PROGRESSO = 3

_TAREFAS: Dict[str, asyncio.Task] = {}
_RODAR: Optional[Rodar] = None


def _intervalo() -> float:
    try:
        return max(0.0, float(os.environ.get("SENTURY_GOAL_INTERVALO_SEG", "2")))
    except ValueError:
        return 2.0


def configurar(rodar: Optional[Rodar]) -> None:
    global _RODAR
    _RODAR = rodar


def rodando(goal_id: str) -> bool:
    tarefa = _TAREFAS.get(goal_id)
    return bool(tarefa and not tarefa.done())


def iniciar(goal_id: str) -> bool:
    """Liga o laco do goal. Idempotente: um goal nunca tem dois lacos."""
    if _RODAR is None or rodando(goal_id):
        return False
    _TAREFAS[goal_id] = asyncio.get_running_loop().create_task(_laco(goal_id))
    return True


def rearmar() -> int:
    """No startup: o goal que estava ativo quando o servidor caiu continua."""
    return sum(iniciar(g.id) for g in _goals.listar(estados=(_goals.ATIVO,)))


async def parar_todos() -> None:
    tarefas = [t for t in _TAREFAS.values() if not t.done()]
    for tarefa in tarefas:
        tarefa.cancel()
    await asyncio.gather(*tarefas, return_exceptions=True)
    _TAREFAS.clear()


def _pausar(goal_id: str, motivo: str, por: str) -> None:
    try:
        _goals.pausar(goal_id, motivo, por=por)
    except _goals.GoalInvalido:
        pass  # a pessoa pausou ou encerrou enquanto o turno rodava


def _feitos(goal: _goals.Goal) -> int:
    return sum(1 for m in goal.marcos if m.get("feito"))


def _falhou(resultado: Any) -> bool:
    return not isinstance(resultado, dict) or bool(resultado.get("falhou"))


def _por_que_parar(resultado: Dict[str, Any]) -> Optional[tuple]:
    permissao = resultado.get("permissao")
    if permissao:
        alvo = (permissao.get("comando") or permissao.get("ferramenta") or "") \
            if isinstance(permissao, dict) else ""
        return f"precisa da sua autorização: {alvo}".strip().rstrip(":"), "permissao"
    if resultado.get("clarification"):
        return "o agente fez uma pergunta: responda na conversa e continue o goal", "pergunta"
    return None


async def _laco(goal_id: str) -> None:
    falhas = sem_progresso = 0
    try:
        while True:
            goal = _goals.carregar(goal_id)
            if goal is None or goal.estado != _goals.ATIVO:
                return
            motivo = _goals.limite_estourado(goal)
            if motivo:
                _pausar(goal_id, motivo, "limite")
                return
            goal = _goals.contar_turno(goal_id)
            antes = _feitos(goal)
            try:
                resultado = await _RODAR(goal, _goals.mensagem_de_continuacao(goal))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Goal %s: o turno falhou: %s", goal_id, exc)
                resultado = {"falhou": True, "erro": str(exc)[:200]}

            depois = _goals.carregar(goal_id)
            if depois is None or depois.estado != _goals.ATIVO:
                return  # declarou cumprido, ou a pessoa pausou/encerrou

            if _falhou(resultado):
                falhas += 1
                if falhas >= MAX_FALHAS:
                    detalhe = str(resultado.get("erro") or "") if isinstance(resultado, dict) else ""
                    _pausar(goal_id, f"{MAX_FALHAS} turnos seguidos falharam"
                            + (f": {detalhe}" if detalhe else ""), "falha")
                    return
            else:
                falhas = 0
                parar = _por_que_parar(resultado)
                if parar:
                    _pausar(goal_id, *parar)
                    return
                ferramentas = (resultado.get("harness") or {}).get("ferramentas") or []
                # `goal ver` sozinho nao e progresso: e o agente olhando o placar.
                agiu = any(f != "goal" for f in ferramentas)
                sem_progresso = 0 if agiu or _feitos(depois) > antes else sem_progresso + 1
                if sem_progresso >= MAX_SEM_PROGRESSO:
                    _pausar(goal_id, f"{MAX_SEM_PROGRESSO} turnos seguidos sem agir: o agente "
                            "pode estar travado; veja a última resposta", "parado")
                    return
            await asyncio.sleep(_intervalo())
    finally:
        tarefa = _TAREFAS.get(goal_id)
        if tarefa is asyncio.current_task():
            _TAREFAS.pop(goal_id, None)


__all__ = ["MAX_FALHAS", "MAX_SEM_PROGRESSO", "configurar", "iniciar", "parar_todos",
           "rearmar", "rodando"]
