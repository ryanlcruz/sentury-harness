"""O que o turno registra depois que a resposta já está escrita: traço,
memória, experiência, telemetria e custo. Nada aqui muda a resposta.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..config import settings
from ..llm.effort import effort_state as _effort_state
from ..memory.user_memory import detect_recurring_interest
from .fatias import da_ultima_chamada as fatias_da_ultima_chamada
from .state import AnalysisState


def registrar_traco(
    orq,
    state: AnalysisState,
    user_message: str,
    reply_text: str,
    decision_log: Dict[str, Any],
    telemetry: Dict[str, Any],
    tool_results: Any,
    deliberation: Dict[str, Any],
    intent: str,
    complexity: Optional[str],
    _budget: Any,
    exit_reason: Any,
    repeticoes_puladas: int,
) -> None:
    """O relatório do turno: traço para a tela de Traces e `loop_stats`.

    À prova de falha de proposito: observabilidade que derruba o turno que
    ela observa é pior que observabilidade nenhuma.
    """
    try:
        from robinbandit.sentury import active_ultra_tier

        from ..observability import record_turn_trace

        record_turn_trace(
            session_id=state.session_id,
            user_id=state.user_id,
            user_message=user_message,
            reply=reply_text,
            decision_log=decision_log,
            telemetry=telemetry,
            tool_results=tool_results,
            deliberation=deliberation,
            mode=active_ultra_tier() or "auto",
            intent=intent,
            complexity=complexity,
        )
    except Exception:
        pass

    # O esforco tem que ser lido AQUI: o contextvar e limpo no finally do
    # handle_message, entao quem ler depois do turno (a eval, a telemetria)
    # so veria None.
    _esf = _effort_state()
    decision_log["loop_stats"] = {
        "loops": _budget.loops,
        "elapsed_ms": round(_budget.elapsed_ms),
        # `exit_reason` e a constante auditavel (StopReason); `stop_reason`
        # continua sendo a frase que aparece na Deliberacao pro usuario.
        "exit_reason": exit_reason,
        "stop_reason": deliberation.get("stop_reason"),
        "repeated_calls_skipped": repeticoes_puladas,
        "tool_calls": _budget.tool_calls,
        "reread_no_progress": telemetry.get("reread_no_progress", 0),
        "route_switches": telemetry.get("route_switches", 0),
        "grounding": orq.turno.grounding or None,
        "effort_base": _esf.base if _esf else None,
        "effort_active": _esf.active if _esf else None,
    }


async def registrar_o_que_ficou(
    orq,
    user_message: str,
    state: AnalysisState,
    plan: List[Dict[str, Any]],
    intent: str,
    telemetry: Dict[str, Any],
    deliberation: Dict[str, Any],
    start_time: float,
) -> Optional[str]:
    """O que fica depois que a resposta ja esta escrita.

    Quatro registros que nao decidem nada do turno: memoria de longo prazo,
    experiencia, telemetria e o fecho da deliberacao. Estavam no meio do
    fluxo principal e pareciam parte dele; sao contabilidade.

    Devolve o fato aprendido, quando houve, porque a interface mostra isso
    ao usuario ("guardei que voce prefere X").
    """
    # O que a pessoa ensina, o modelo guarda pela ferramenta `memoria`; aqui
    # fica só o interesse que se repete nos recortes que ela mesma escolheu.
    learned = None
    if orq.memory and settings.SENTURY_AUTOLEARN:
        fato = detect_recurring_interest(state.history, state.results)
        if fato and await orq.memory.remember(state.user_id, fato, sessao=state.session_id):
            learned = fato

    # O fluxo que deu certo vira procedimento consultavel depois.
    if len(plan) > 0:
        await orq.experience_library.save(
            intent, [p["tool"] for p in plan], success=True, user_message=user_message
        )

    telemetry["context_messages"] = len(state.history)
    telemetry["context_chars"] = orq.context_budget_manager.calculate_usage(state.history)
    telemetry["context_status"] = orq.context_budget_manager.get_status(telemetry["context_chars"])
    if len(state.history) > orq.context_budget_manager.limit_messages:
        telemetry["context_status"] = "COMPACT"
    telemetry["limit_messages"] = orq.context_budget_manager.limit_messages
    telemetry["limit_chars"] = orq.context_budget_manager.limit_chars

    fechar_telemetria(orq, telemetry, start_time)
    from .encerramento import recusas_do_turno
    telemetry["recusas"] = recusas_do_turno()

    # O texto interno de reasoning nunca integra o payload publico.
    deliberation["status"] = "concluded"
    # Preserva o motivo específico de parada registrado pelo laço.
    # A conclusão genérica só vale quando nenhum passo explicou a saída.
    if not deliberation.get("stop_reason"):
        deliberation["stop_reason"] = (
            "evidência suficiente para responder" if deliberation["steps"]
            else "resposta direta (sem necessidade de ferramenta)"
        )
    return learned


def fechar_telemetria(orq, telemetry: Dict[str, Any], start_time: float) -> None:
    """Tempo, modelo, tokens e custo do turno, iguais em toda saída."""
    telemetry["total_ms"] = int((time.time() - start_time) * 1000)
    from .encerramento import identificar_modelo
    identificar_modelo(orq, telemetry)
    telemetry["tokens"] = uso_do_turno()
    telemetry["json_repairs"] = orq.turno.reparos_json
    telemetry["custo_usd"] = custo_do_turno(telemetry.get("model"), telemetry["tokens"])
    telemetry["fatias"] = fatias_da_ultima_chamada()


def uso_do_turno() -> Optional[Dict[str, int]]:
    """Tokens somados de todas as chamadas deste turno, quando o provedor
    informa. Sem numero real nao se estima nada."""
    try:
        from robinbandit.chain import contagem_do_turno
        uso = contagem_do_turno()
    except Exception:
        return None
    if not uso or not uso.get("total"):
        return None
    return dict(uso)


def custo_do_turno(modelo, uso):
    """O que o provedor cobrou, quando ele informa; senao, a estimativa pelo preco publicado."""
    if isinstance(uso, dict) and uso.get("custo_usd") is not None:
        return round(float(uso["custo_usd"]), 6)
    try:
        from robinbandit.chain import custo_estimado
        from robinbandit.model_catalog import precos_conhecidos
        return custo_estimado(modelo, uso, precos_conhecidos())
    except Exception:
        return None
