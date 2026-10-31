"""O turno que para antes de agir: para pedir autorização ou para perguntar.

Nos dois casos a resposta da pessoa vem no turno seguinte, que retoma a partir
do que fica guardado aqui (a tarefa pendente ou a nota do que foi perguntado).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .state import AnalysisState


def perguntas_seguidas(state: AnalysisState) -> int:
    """Quantas vezes seguidas ele já perguntou sem agir no meio."""
    seguidas = 0
    for msg in reversed(state.history):
        conteudo = str(msg.get("content") or "")
        if msg.get("role") == "system":
            if "[ESCLARECIMENTO PENDENTE]" in conteudo:
                seguidas += 1
            elif "RESULTADO DA FERRAMENTA" in conteudo:
                break  # agiu no meio: a contagem recomeça
    return seguidas


def autorizacao_pendente(
    orq, plan: List[Dict[str, Any]], state: AnalysisState
) -> Optional[Dict[str, Any]]:
    """O primeiro passo do plano que precisa de autorização, se houver.

    Só olha o que dá para saber sem executar nada: quando o alvo depende do
    resultado de um passo anterior, a pergunta continua acontecendo na hora.
    """
    from ..exec.politica import comando_a_autorizar
    from ..residentes.escopo import pode_usar
    from ..exec.politica import avaliar
    from .gravacao_do_turno import EM_REPLAY, aprovado_na_gravacao

    sessao = str(getattr(state, "session_id", "") or "")
    for step in plan:
        if not isinstance(step, dict):
            continue
        ferramenta = str(step.get("tool") or "")
        # Fora do manifesto do residente a policy recusa no passo: não se pergunta.
        if not pode_usar(ferramenta):
            continue
        comando = comando_a_autorizar(ferramenta, step.get("arguments") or {})
        if not comando or aprovado_na_gravacao(ferramenta, step.get("arguments") or {}):
            continue
        try:
            decisao = avaliar(comando, sessao, consumir=False)
        except Exception:
            continue
        # No replay, ação sem resultado gravado não rodou na produção: o cartão
        # abriu lá, mesmo que a permissão desta máquina hoje deixe passar.
        if decisao.get("precisa_perguntar") or (EM_REPLAY.get() and decisao.get("permitido")):
            return {
                "chave": str(decisao.get("chave") or ""),
                "comando": comando,
                "motivo": str(decisao.get("motivo") or ""),
                "so_desta_vez": bool(decisao.get("so_desta_vez")),
                "ferramenta": ferramenta,
                # sem isto a retomada reexecutava a ferramenta sem argumento
                "argumentos": step.get("arguments") or {},
            }
    return None


def resultado_de_permissao(
    orq,
    state: AnalysisState,
    user_message: str,
    permissao: Dict[str, Any],
    decision_log: Dict[str, Any],
    telemetry: Dict[str, Any],
) -> Dict[str, Any]:
    """Turno que para para perguntar. Nao guardamos a pergunta no historico
    como se fosse resposta: o proximo turno reexecuta com a decisao tomada."""
    # Curto de propósito: o detalhe e as opções estão na folha logo abaixo,
    # e repetir aqui só faz o usuário ler a mesma coisa duas vezes.
    # O `comando` traz operacao E alvo ("acessar_pasta C:/..."), que e o
    # que a pessoa precisa ler para decidir. A ferramenta sozinha era
    # nome interno: "acessar_pasta precisa da sua autorizacao" nao diz
    # de qual pasta se trata.
    alvo = str(permissao.get("comando") or "").strip()
    if not alvo:
        alvo = str(permissao.get("ferramenta") or permissao.get("tool") or "").strip()
    texto = (f"Parei aqui: `{alvo}` precisa da sua autorização." if alvo
             else "Parei aqui: isso precisa da sua autorização.")
    # O que retomar quando a resposta vier: o turno seguinte le isto em
    # vez de depender de o modelo reler a mensagem original.
    from .retomada import guardar as _guardar_pendencia

    pedido = (decision_log or {}).get("pedido_retomado") or user_message
    state.tarefa_pendente = _guardar_pendencia(pedido, permissao, alvo)
    return {
        "message": texto,
        "attachment": None,
        "harness": {
            **decision_log,
            "events": [{"stage": "permission_required", "status": "waiting"}],
        },
        "state": state.to_dict(),
        "learned": None,
        "council": None,
        "subagents_beta": None,
        "proactive_insight": None,
        "skill_activated": None,
        "deliberation": None,
        "plan_question": None,
        "permissao": permissao,
        "telemetry": telemetry,
    }


def resultado_de_pergunta(orq, state: AnalysisState, user_message: str,
                                clarification: Dict[str, Any], decision_log: Dict[str, Any],
                                telemetry: Dict[str, Any]) -> Dict[str, Any]:
    """Monta o retorno de um turno de esclarecimento (AskUserQuestion): a
    mensagem visível é só o intro; as opções vão no campo `clarification` pro
    frontend renderizar como botões. Guarda no histórico o intro (assistente)
    e uma nota de sistema com o que foi perguntado, pra o próximo turno
    interpretar a resposta curta do usuário."""
    intro = clarification["intro"]
    # Nota de contexto (role system): o Planner do próximo turno enxerga o que
    # foi perguntado; o usuário não vê isso como bolha.
    resumo_perguntas = "; ".join(
        f"{q['question']} [{', '.join(o['label'] for o in q['options'])}]"
        for q in clarification["questions"]
    )
    state.history.append({"role": "assistant", "content": intro})
    state.history.append({
        "role": "system",
        "clarification": clarification,
        "content": (
            "[ESCLARECIMENTO PENDENTE] Você perguntou à pessoa antes de agir: "
            f"{resumo_perguntas}. A próxima mensagem dela é a resposta: use-a para montar "
            "o plano, porque perguntar de novo a mesma coisa a faz repetir o que já disse."
        ),
    })

    telemetry["context_messages"] = len(state.history)
    telemetry["context_chars"] = orq.context_budget_manager.calculate_usage(state.history)
    telemetry["context_status"] = orq.context_budget_manager.get_status(telemetry["context_chars"])
    telemetry["limit_messages"] = orq.context_budget_manager.limit_messages
    telemetry["limit_chars"] = orq.context_budget_manager.limit_chars

    return {
        "message": intro,
        "attachment": None,
        "clarification": clarification,
        "harness": orq._decorate_harness(decision_log, user_message, None, intro),
        "state": state.to_dict(),
        "learned": None,
        "telemetry": telemetry,
        "compacted": False,
    }
