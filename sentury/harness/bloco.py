"""O que amarra um evento ao bloco de execução que o produziu.

O `id` do passo (`p1s0`) é emitido no `plan_update` e repetido no `tool_start`,
e é o que faz o front atualizar a linha certa em vez de criar outra. Quando um
evento nasce ao lado da execução (uma pergunta de permissão, por exemplo) ele
precisa carregar esse mesmo id, senão vira uma caixa solta na tela: com dois
pedidos ao mesmo tempo, ninguém sabe qual comando está aprovando.

O store compara o id da chamada com a fila de permissão e marca o bloco como
pendente, sem depender de um estado global de aprovação.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def id_do_passo(plano: List[Dict[str, Any]], ferramenta: Any, volta: int) -> Optional[str]:
    """O id do primeiro passo desta volta que usa essa ferramenta.

    Devolve None quando não acha, e None é honesto: melhor a caixa aparecer
    solta do que grudada no bloco errado.
    """
    alvo = str(ferramenta or "").strip()
    if not alvo:
        return None
    for i, passo in enumerate(plano):
        if isinstance(passo, dict) and str(passo.get("tool") or "") == alvo:
            return f"p{volta}s{i}"
    return None


# As ferramentas que mexem no plano. Quando uma delas roda, o turno passa a ter
# um workflow para mostrar: e ate agora ele so existia em disco.
FERRAMENTAS_DE_PLANO = (
    "criar_plano", "ver_plano", "status_da_tarefa", "criar_workflow", "ver_workflow",
)


def plano_do_turno(resultados: Any) -> Optional[Dict[str, Any]]:
    """O plano tocado neste turno, pronto para virar card.

    Le do disco em vez de remontar do resultado da ferramenta: o disco e a
    verdade, e `status_da_tarefa` devolve so a tarefa marcada: quem le a tela
    quer o plano inteiro, com o que travou e o que emperrou.
    """
    nome = ""
    tipo = "plano"
    agendamento_id = ""
    aprovado = False
    for registro in resultados or []:
        if not isinstance(registro, dict):
            continue
        ferramenta = str(registro.get("tool") or "")
        if ferramenta not in FERRAMENTAS_DE_PLANO:
            continue
        saida = registro.get("result")
        if isinstance(saida, dict):
            if ferramenta in ("criar_workflow", "ver_workflow") or saida.get("workflow"):
                nome = str(saida.get("workflow") or nome)
                tipo = "workflow"
                agenda = saida.get("agendamento")
                if isinstance(agenda, dict):
                    agendamento_id = str(agenda.get("id") or agendamento_id)
                    aprovado = bool(agenda.get("active"))
            else:
                nome = str(saida.get("plano") or nome)
                tipo = "plano"
    if not nome:
        return None
    try:
        if tipo == "workflow":
            from ..memory import workflow as _workflow

            resumo = _workflow.resumo(nome)
            if not resumo.get("ok"):
                return None
            tarefas = [
                {
                    "id": str(i),
                    "titulo": re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", str(titulo)),
                    "feito": False,
                    "estado": "pendente",
                    "opcional": False,
                    "gate": False,
                    "tentativas": 0,
                }
                for i, titulo in enumerate(resumo.get("passos") or [], 1)
            ]
            return {
                "ok": True,
                "tipo": "workflow",
                "plano": resumo["workflow"],
                "gatilho": resumo.get("gatilho") or "",
                "agendamento_id": agendamento_id or None,
                "aprovado": aprovado,
                "tarefas": tarefas,
                "faltam": len(tarefas),
                "proxima": tarefas[0] if tarefas else None,
                "estado": "ativo" if aprovado else "proposto",
                "travado_por": None,
                "contexto": resumo.get("porque") or "",
                "telemetria": {
                    "tentativas": resumo.get("total_de_execucoes") or 0,
                    "sessoes": 0,
                    "emperradas": [],
                },
            }

        from ..memory import plano as _plano

        resumo = _plano.resumo(nome)
        if not resumo.get("ok"):
            return None
        resumo["telemetria"] = _plano.telemetria(nome)
        resumo["tipo"] = "plano"
        return resumo
    except Exception:
        logger.debug("Nao consegui montar o plano do turno", exc_info=True)
        return None


# Nao viram linha no checklist: um pergunta, o outro liga esforco. Nenhum dos
# dois "roda" no sentido que o usuario acompanha.
SEM_LINHA_NO_CHECKLIST = ("perguntar_usuario",)


def entradas_do_plano(plano: List[Dict[str, Any]], volta: int, titulo, fala) -> List[Dict[str, Any]]:
    """O plano inteiro como checklist ao vivo, todos os passos `pending`.

    Os ids saem daqui e sao repetidos no `tool_start`, no `tool_complete` e na
    permissao: e isso que faz a tela atualizar a linha certa em vez de criar
    outra a cada evento.
    """
    return [
        {
            "id": f"p{volta}s{i}",
            "title": titulo(passo.get("tool"), passo.get("arguments") or {}),
            "fala": fala(passo.get("fala")),
            "status": "pending",
        }
        for i, passo in enumerate(plano)
        if isinstance(passo, dict) and passo.get("tool") not in SEM_LINHA_NO_CHECKLIST
    ]
