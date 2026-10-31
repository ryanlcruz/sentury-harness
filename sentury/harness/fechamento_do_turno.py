"""O fechamento do turno: o que acontece depois do laço de ferramentas.

Recebe os valores que o laço produziu e devolve o resultado do turno. Toda
saída do turno passa por aqui, então o formato da resposta mora num lugar só.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict

from .bloco import plano_do_turno
from .loop_budget import StopReason
from .resposta_limpa import limpar as limpar_resposta
from .aprendizados import do_turno
from .contabilidade_do_turno import fechar_telemetria, registrar_o_que_ficou, registrar_traco
from .artefato_do_turno import plano_vira_card, recusar_artefato_sem_lastro

# Mídia que uma skill devolveu no resultado do sandbox.
_MEDIA_URL_RE = re.compile(r"https?://\S+?\.(?:gif|png|jpe?g)\b", re.IGNORECASE)


def _extract_media_url(tool_results):
    """Se uma skill de mídia devolveu uma URL de gif ou imagem no
    resultado do sandbox, retorna essa URL: para entregar a mídia limpa."""
    for tr in tool_results or []:
        res = tr.get("result")
        valores = []
        if isinstance(res, dict):
            for k in ("resultado", "saida"):
                v = res.get(k)
                if isinstance(v, str):
                    valores.append(v)
        elif isinstance(res, str):
            valores.append(res)
        for v in valores:
            m = _MEDIA_URL_RE.search(v)
            if m:
                return m.group(0)
    return None


async def fechar(
    orq: Any,
    *,
    state: Any,
    user_message: Any,
    start_time: Any,
    telemetry: Any,
    decision_log: Any,
    deliberation: Any,
    plan: Any,
    complexity: Any,
    tool_results: Any,
    exit_reason: Any,
    unresolved_tool_failure: Any,
    export_response: Any,
    attachment: Any,
    anexos_do_turno: Any,
    pre_turn_had_data: Any,
    compacted: Any,
    contexto_adicional: Any,
    rag_context: Any,
    turn_activated_skills: Any,
    repeticoes_puladas: Any,
    orcamento: Any,
    progress: Callable,
    emit: Callable,
    emit_reasoning: Callable,
) -> Dict[str, Any]:
    """Do motivo de parada à resposta montada: exportação, mídia, pareceres,
    resposta, conferências e o registro do turno."""
    # Saiu pela condição do while (a última volta pediu re-planejamento e o
    # teto acabou): é orçamento esgotado, não conclusão.
    if exit_reason is None:
        exit_reason = StopReason.BUDGET_EXHAUSTED
    if unresolved_tool_failure:
        exit_reason = StopReason.TOOL_FAILURE
    # Pular uma chamada repetida não muda uma conclusão válida para falha.
    # A contagem de pulos permanece na telemetria para auditoria.
    from .configuracao_do_turno import experiencia_observada, intencao_observada
    if orq.turno.passo_unico:
        plan = experiencia_observada(tool_results)
    intent = intencao_observada(plan)

    # Se for uma resposta de exportação determinística direta
    if export_response:
        had_attachment = attachment is not None
        attachment, export_response = recusar_artefato_sem_lastro(orq,
            state,
            attachment,
            export_response,
            tool_results,
            pre_turn_had_data=pre_turn_had_data,
        )
        if had_attachment and attachment is None:
            decision_log["harness_allowed"] = False
            decision_log["harness_reason"] = "Artefato rejeitado pela validacao deterministica de grounding."
        state.history.append({"role": "assistant", "content": export_response})
        registrar_traco(orq, state, user_message, export_response, decision_log, telemetry, tool_results, deliberation, intent, complexity, orcamento, exit_reason, repeticoes_puladas)
        # Salva na biblioteca de experiências se foi um fluxo bem-sucedido
        if len(plan) > 0:
            await orq.experience_library.save(intent, [p["tool"] for p in plan], success=True)
        fechar_telemetria(orq, telemetry, start_time)
        return {
            "message": export_response,
            "attachment": attachment,
            "attachments": anexos_do_turno if len(anexos_do_turno) > 1 else None,
            "harness": orq._decorate_harness(decision_log, user_message, attachment, export_response),
            "state": state.to_dict(),
            "learned": None,
            "telemetry": telemetry,
            "compacted": compacted, "compactacao": state.ultima_compactacao,
        }

    # Quando a saída pedida é mídia, entrega a URL sem texto analítico
    # ou oferta de plano que competiria com o próprio resultado.
    media_url = _extract_media_url(tool_results)
    if media_url:
        reply_text = f"![gif]({media_url})"
        state.history.append({"role": "assistant", "content": reply_text})
        if len(plan) > 0:
            await orq.experience_library.save(intent, [p["tool"] for p in plan], success=True, user_message=user_message)
        fechar_telemetria(orq, telemetry, start_time)
        return {
            "message": reply_text, "attachment": attachment,
            "attachments": anexos_do_turno if len(anexos_do_turno) > 1 else None,
            "harness": orq._decorate_harness(decision_log, user_message, attachment, reply_text), "state": state.to_dict(),
            "learned": None, "telemetry": telemetry, "compacted": compacted, "compactacao": state.ultima_compactacao,
        }

    # 7. Parecer de terceiros (conselho + subagentes): fase com nome e
    # porta propria em harness/pareceres.py. Ver a docstring de la sobre
    # por que o laco estava virando flag sobre flag no mesmo escopo.
    from .pareceres import colher as _colher_pareceres

    _pareceres = await _colher_pareceres(
        orq,
        user_message=user_message,
        state=state,
        tool_results=tool_results,
        telemetry=telemetry,
        decision_log=decision_log,
        progress_cb=progress,
        emit=emit,
    )
    council_ctx = _pareceres.contexto
    council_analysis = _pareceres.analise
    # O cartão de subagentes na tela lê o relatório da chamada da ferramenta.
    subagents_beta = next((tr["result"].get("relatorio") for tr in reversed(tool_results)
                           if tr.get("tool") == "subagentes" and isinstance(tr.get("result"), dict)), None)
    plano_no_turno = _pareceres.plano_no_turno
    deliberation["steps"].extend(_pareceres.passos)

    # 8. A resposta ao usuário.
    reply_text = await orq._escrever_resposta(
        user_message, state, council_analysis, tool_results, telemetry, decision_log, progress,
    )


    # Aplica as transformações finais ao anexo e ao texto em sequência.
    from .pos_resposta import aplicar as _pos_resposta

    attachment, reply_text = await _pos_resposta(
        orq,
        user_message=user_message,
        state=state,
        attachment=attachment,
        reply_text=reply_text,
        tool_results=tool_results,
        pre_turn_had_data=pre_turn_had_data,
    )

    # A pontuação usa o veredito de evidência da resposta já conferida.
    # Assim o roteador avalia a origem dos números, não uma autocrítica do modelo.
    reply_text = await orq._enforce_grounding(state, reply_text)
    orq._pontuar_resposta(user_message, reply_text, complexity, decision_log)
    # Remove marcas de arquivo que não pertencem ao texto da conversa.
    reply_text = limpar_resposta(reply_text)

    state.history.append({"role": "assistant", "content": reply_text})

    learned = await registrar_o_que_ficou(orq,
        user_message, state, plan, intent, telemetry, deliberation, start_time,
    )

    proactive_insight = await orq._insight_proativo(tool_results)
    attachment, reply_text, plan_question = plano_vira_card(orq,
        state, plano_no_turno, attachment, reply_text,
    )

    registrar_traco(orq,
        state, user_message, reply_text, decision_log, telemetry,
        tool_results, deliberation, intent, complexity,
        orcamento, exit_reason, repeticoes_puladas,
    )
    return {
        "message": reply_text,
        "attachment": attachment,
        "attachments": anexos_do_turno if len(anexos_do_turno) > 1 else None,
        "harness": orq._decorate_harness(decision_log, user_message, attachment, reply_text),
        "state": state.to_dict(),
        "learned": learned,
        "aprendizados": do_turno(tool_results, learned) or None,
        "council": council_analysis,
        # O workflow existia so em disco: portao, ciclo e telemetria sem
        # nenhuma tela. Ver harness/bloco.py.
        "plano": plano_do_turno(tool_results),
        "subagents_beta": subagents_beta,
        "proactive_insight": proactive_insight,
        "skill_activated": turn_activated_skills or None,
        "deliberation": deliberation if deliberation.get("steps") else None,
        "plan_question": plan_question,
        "telemetry": telemetry,
        "compacted": compacted, "compactacao": state.ultima_compactacao
    }
