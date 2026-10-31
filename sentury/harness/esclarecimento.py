"""Quando o agente pergunta antes de agir, e quando a pergunta é descartada.

`perguntar_usuario` encerra o turno: com opções vira cartão clicável, sem opções
o texto da pergunta é a resposta. Perguntar custa um turno, por isso a pergunta
sai do plano em dois casos: na retomada de uma ação que a pessoa acabou de
autorizar, porque a autorização já diz o que fazer, e depois de perguntas
seguidas, porque a pessoa está respondendo agora.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from .pausa_do_turno import perguntas_seguidas

logger = logging.getLogger(__name__)


def _sem_pergunta(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [passo for passo in plan if passo.get("tool") != "perguntar_usuario"]


def _no_formato_interno(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`{pergunta, opcoes}`, que e o que o `tools.yaml` declara, vira `{questions}`,
    o formato do extrator."""
    saida = []
    for passo in plan:
        args = passo.get("arguments") if isinstance(passo, dict) else None
        if (passo.get("tool") == "perguntar_usuario" and isinstance(args, dict)
                and not isinstance(args.get("questions"), list) and str(args.get("pergunta") or "").strip()):
            opcoes = args.get("opcoes") or args.get("options") or []
            passo = {**passo, "arguments": {**args, "questions": [
                {"question": str(args["pergunta"]).strip(), "options": opcoes if isinstance(opcoes, list) else []},
            ]}}
        saida.append(passo)
    return saida


def _pergunta_aberta(plan: List[Dict[str, Any]]) -> str:
    for passo in plan:
        if isinstance(passo, dict) and passo.get("tool") == "perguntar_usuario":
            args = passo.get("arguments") or {}
            perguntas = args.get("questions") if isinstance(args.get("questions"), list) else []
            textos = [str(q.get("question") or "").strip() for q in perguntas if isinstance(q, dict)]
            # Com `questions` vazio, o texto que sobra e o `intro`: ele e a pergunta.
            return ("\n\n".join(x for x in textos if x) or str(args.get("pergunta") or "").strip()
                    or str(args.get("intro") or "").strip())
    return ""


def resolver(
    orquestrador: Any,
    plan: List[Dict[str, Any]],
    *,
    state: Any,
    user_message: str,
    retomar: Optional[Dict[str, Any]],
    max_perguntas_seguidas: int,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Devolve `(plano, pergunta)`. Pergunta `None` = o turno segue agindo."""
    plan = _no_formato_interno(plan)
    clarification = orquestrador._extract_clarification(plan)
    if not clarification:
        aberta = _pergunta_aberta(plan)
        if aberta and not retomar:
            # Sem opcoes nao ha folha para clicar: a pergunta e a resposta do
            # turno, e a pessoa responde no chat.
            orquestrador.turno.resposta_direta = aberta
            # No plano em texto o redator reescreveria o turno a partir dos
            # resultados e a pergunta se perderia; ela ja e o texto final.
            orquestrador.turno.resposta_conferida = aberta
            return [], None
        if any(isinstance(passo, dict) and passo.get("tool") == "perguntar_usuario" for passo in plan):
            # A pergunta nao tem executor fora daqui: sem texto para mostrar, o
            # modelo fica sabendo e responde com o que tem.
            if not aberta:
                state.history.append({"role": "system", "content": (
                    "A chamada de perguntar_usuario chegou sem texto de pergunta. Se precisa "
                    "de algo da pessoa, escreva a pergunta na resposta.")})
            return _sem_pergunta(plan), None
        return plan, None

    if retomar:
        logger.info(
            "Retomada: descartando perguntar_usuario; a autorizacao ja disse o que fazer."
        )
        return _sem_pergunta(plan), None

    if perguntas_seguidas(state) >= max_perguntas_seguidas:
        logger.info("Guard AskUserQuestion: bloqueada re-pergunta; agindo com o contexto.")
        plan = _sem_pergunta(plan)
        if not plan:
            # A pergunta foi barrada: o modelo fica sabendo e decide o que fazer
            # com o que já tem, em vez de o código escolher a ferramenta por ele.
            state.history.append({"role": "system", "priority": "HIGH", "content": (
                f"Você já perguntou {max_perguntas_seguidas} vezes seguidas sem agir. Não "
                "pergunte de novo: aja com o que a pessoa já disse e com o que está na "
                "conversa, ou diga na resposta o que falta para continuar.")})
        return plan, None

    return plan, clarification
