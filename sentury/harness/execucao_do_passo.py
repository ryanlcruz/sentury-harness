"""A execução de um passo do plano: da decisão do harness ao resultado no histórico.

Cada passo passa pela política, roda a ferramenta e deixa a observação para o
modelo. A função diz ao laço como seguir: `SEGUIR` para o próximo passo, `PARAR`
para sair do plano e replanejar ou fechar, ou o resultado pronto do turno quando
um cartão de permissão precisa abrir.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Union

from ..llm.prompts import build_tool_result_instruction
from ..tools.catalog import execute_tool
from . import hooks
from . import caixa_do_turno
from .anexo_do_resultado import anexo_do_resultado
from .classificacao import falhou, recusado
from .continuation import registrar_bloqueio
from .conversa import marcar_chamada
from .narracao import tirar_fala
from .policy import ANALYSIS_TOOLS, SKILL_TOOLS, sentury_harness
from .repeticao import aviso_de_skill_carregada, skill_ja_carregada
from .repeticao import lembrete as lembrete_de_repeticao
from .resposta_limpa import avisar_do_card
from .resumo_de_ferramenta import previsualizar
from .pausa_do_turno import resultado_de_permissao
from .artefato_do_turno import (argumentos_de_exportacao, chaves_de_recorte, normalizar_passo_de_artefato,
                                recorte_foi_pedido)

logger = logging.getLogger(__name__)

SEGUIR = "seguir"
PARAR = "parar"


@dataclass
class EstadoDoPasso:
    """O que um passo pode mudar e o laço lê depois dele."""

    attachment: Any = None
    export_response: Any = None
    need_replanning: bool = False
    unresolved_tool_failure: Any = None
    repeticoes_puladas: int = 0
    max_loops: int = 2
    avisou_repeticao: bool = False
    # O plano inteiro: a pausa num `criar_agente` leva os outros da mesma equipe.
    plano: List[Dict[str, Any]] = field(default_factory=list)


async def executar(
    orq: Any, est: EstadoDoPasso, step: Dict[str, Any], step_idx: int, *,
    state: Any, user_message: str, telemetry: Dict[str, Any], decision_log: Dict[str, Any],
    deliberation: Dict[str, Any], tool_results: Any, anexos_do_turno: List[Dict[str, Any]],
    turn_activated_skills: List[str], loop_idx: int,
    ha_volta: Callable[[], bool], loop_livre: bool, orcamento: Any, repetidas: Any, rotas: Any,
    narrador: Any, canal: Any,
) -> Union[str, Dict[str, Any]]:
    """Roda um passo; devolve `SEGUIR`, `PARAR` ou o resultado do turno."""
    if ha_volta() and caixa_do_turno.aplicar(state):  # a pessoa corrigiu o rumo: replaneja já
        est.need_replanning = True
        return PARAR
    step = normalizar_passo_de_artefato(step, decision_log["artifact_plan"])
    if step is None:
        return SEGUIR
    tool = step["tool"]
    arguments = step.get("arguments", {})

    if tool == "export_html":
        arguments = dict(arguments)
        arguments.setdefault("request", user_message)
    # O id compartilha o índice de plan_update para atualizar
    # o passo correspondente na interface.
    _current_tid = f"p{loop_idx}s{step_idx}"
    step["__tid"] = _current_tid
    canal.emit({
        "type": "tool_start",
        "id": _current_tid,
        "tool": tool,
        "kind": orq._tool_kind(tool),
        # O que a acao significa, alem de como ela se desenha.
        "intent": orq._tool_intent(tool),
        "title": orq._tool_title(tool, arguments),
        "command": orq._tool_command(tool, arguments),
        # O passo diz o que vai fazer ANTES de fazer. Vem no mesmo
        # evento que anuncia a execucao, entao a tela mostra na
        # ordem certa sem precisar casar dois eventos.
        # A do passo, se o modelo escreveu uma; senao a da volta,
        # consumida aqui para nao repetir nos passos seguintes.
        "fala": narrador.proxima(step.get("fala")) or tirar_fala(orq),
    })
    canal.inicio_das_ferramentas[_current_tid] = time.time()
    # mantém compat com o canal antigo de string (fallback)
    canal.progress(orq._progress_label_for_tool(tool, arguments))




    rota_em_tentativa = rotas.preparar(orcamento, tool, arguments)
    # Evita repetir ferramenta e argumentos no mesmo turno, inclusive
    # para não duplicar efeitos colaterais; perguntas são exceção.
    _ja_rodou = repetidas.repetida(tool, arguments)
    if _ja_rodou is not None:
        logger.info("Loop guard: %s repetido (%dx); devolvendo a observacao.",
                    tool, _ja_rodou["vezes"])
        telemetry["skipped_repeated_calls"] = telemetry.get("skipped_repeated_calls", 0) + 1
        est.repeticoes_puladas += 1
        est.avisou_repeticao = True
        # O motivo mostrado deve refletir a repetição, não afirmar
        # que houve evidência nova.
        # A trilha precisa distinguir estagnação de conclusão normal.
        deliberation["stop_reason"] = (
            "o ultimo passo repetia o anterior; nada novo foi observado"
        )
        state.history.append({"role": "system", "content": lembrete_de_repeticao(
            tool, _ja_rodou["resultado"], _ja_rodou["vezes"])})
        # Fecha o passo na tela; senao o spinner fica preso.
        canal.emit({"type": "tool_complete", "id": _current_tid, "status": "skipped",
                       "duration_ms": canal.dur(_current_tid)})
        return SEGUIR

    # Validação determinística pelo Harness
    decision = sentury_harness.evaluate(state, tool, user_message, arguments)
    if not decision.allowed:
        fallback_arguments = argumentos_de_exportacao(state, tool, arguments, decision)
        if fallback_arguments is not None:
            logger.info(
                "Export com source invalido (%s). Reaproveitando ultimo resultado da sessao (%s).",
                arguments.get("source"),
                state.last_result_id,
            )
            arguments = fallback_arguments
            decision = sentury_harness.evaluate(state, tool, user_message, arguments)

        if decision.allowed:
            decision_log["harness_allowed"] = True
            if not decision_log.get("harness_reason", "").startswith("Fonte de grafico"):
                decision_log["harness_reason"] = decision.reason
        else:
            logger.warning("Ferramenta %s bloqueada pelo Harness: %s", tool, decision.reason)
            registrar_bloqueio(state, tool, decision, decision_log)
            est.need_replanning = loop_livre and ha_volta()
            return SEGUIR

    decision_log["proposed_tool"] = tool
    decision_log["harness_allowed"] = decision.allowed
    decision_log["harness_reason"] = decision.reason

    # Executa ferramentas de skill/skill (incluindo skills procedurais chamadas diretamente)
    is_direct_skill = tool in orq.procedural_skills
    pedida = tool if is_direct_skill else str((arguments or {}).get("nome") or "").strip().lower()
    if (is_direct_skill or tool == "executar_skill") and skill_ja_carregada(state.history, pedida):
        state.history.append({"role": "system", "content": aviso_de_skill_carregada(pedida)})
        canal.emit({"type": "tool_complete", "id": _current_tid, "status": "skipped",
                    "duration_ms": canal.dur(_current_tid)})
        return SEGUIR
    if tool in SKILL_TOOLS or is_direct_skill:
        if is_direct_skill:
            # O modelo chamou a skill pelo nome, como se fosse ferramenta: vira executar_skill(nome=...).
            skill_nome = tool
            modo, payload = await orq._handle_skill(state, "executar_skill", {"nome": skill_nome})
            est.need_replanning = True
        else:
            skill_nome = str((arguments or {}).get("nome") or "").strip()
            modo, payload = await orq._handle_skill(state, tool, arguments)
            if tool == "executar_skill":
                est.need_replanning = True
        # modo "continue" = a skill procedural CARREGOU no contexto (não foi
        # "não encontrei" nem replay legado). É o momento de exercer a
        # liberdade da camada 2→3: registramos p/ o card visível.
        if modo == "continue" and skill_nome and skill_nome not in turn_activated_skills:
            turn_activated_skills.append(skill_nome)
        if modo == "terminal":
            est.export_response = payload
            return PARAR
        return SEGUIR

    # Executa a ferramenta no catálogo; ação destrutiva para antes no cartão.
    from ..exec.politica import cartao_de_destrutiva

    try:
        result = cartao_de_destrutiva(tool, arguments, state.session_id)
        if result is None:
            result = await execute_tool(orq.store, state, tool, arguments, orq.knowledge, orq.memory,
                                        experience=orq.experience_library,
                                        sessions=orq.session_index)
        # Uma ação mutante que precisa de permissão pausa o turno.
        # A decisão do usuário governa a retomada desse mesmo passo.
        if isinstance(result, dict) and result.get("precisa_permissao"):
            pedido = {
                "chave": str(result.get("chave") or ""),
                "comando": str(result.get("comando") or ""),
                "motivo": str(result.get("motivo") or ""),
                # Candidatura e envio de dado: o cartao so oferece esta vez.
                "so_desta_vez": bool(result.get("so_desta_vez")),
                # O que "nesta conversa" cobre, quando é mais que este comando.
                "nesta_conversa": str(result.get("nesta_conversa") or ""),
                # Sem isto a retomada nao sabia o que reexecutar.
                "ferramenta": tool,
                "argumentos": arguments,
            }
            if tool == "criar_agente":
                from .equipe import da_equipe

                if len(equipe := da_equipe(arguments, est.plano, step_idx)) > 1:
                    pedido["equipe"] = equipe
                    pedido["comando"] = "criar_agente " + ", ".join(str(m["nome"]) for m in equipe)
            decision_log["proposed_tool"] = tool
            decision_log["harness_allowed"] = False
            decision_log["harness_reason"] = (
                f"Permissao pendente para '{pedido['chave']}'"
            )
            # O turno acaba aqui e a retomada abre um passo novo; sem fechar
            # este, ele fica girando como "rodando" na mensagem que pausou.
            canal.emit({"type": "tool_complete", "id": _current_tid, "status": "pending",
                        "duration_ms": canal.dur(_current_tid)})
            canal.emit({"type": "permissao", "permissao": pedido})
            return resultado_de_permissao(orq,
                state, user_message, pedido, decision_log, telemetry
            )
        if isinstance(result, dict) and isinstance(result.get("attachment"), dict):
            anexo = result["attachment"]
            anexos_do_turno.append(anexo)
            est.attachment = anexo
        tool_results.append({"tool": tool, "result": result})
        avisar_do_card(state, tool)
        # Uma leitura repetida sem informação nova conta como falta
        # de progresso, mesmo que a ferramenta tenha retornado sucesso.
        _novo = orcamento.observe_result(tool, result)
        orcamento.record_tool(failed=falhou(result), progressed=_novo)
        if not _novo:
            logger.info("Loop guard: %s devolveu o MESMO resultado de antes (releitura).", tool)
            telemetry["reread_no_progress"] = telemetry.get("reread_no_progress", 0) + 1
        deliberation["steps"].append({"tool": tool, "observation": orq._observe_result(tool, result)})
        if falhou(result):
            est.unresolved_tool_failure = (tool, result)
            rotas.falhou(tool, arguments, result)
            canal.emit({"type": "tool_complete", "id": _current_tid,
                           "status": "rejected" if recusado(result) else "error",
                           "duration_ms": canal.dur(_current_tid),
                           "resumo": previsualizar(result)})
            instruction = build_tool_result_instruction(tool, result)
            state.history.append(marcar_chamada({"role": "system", "content": instruction}, step, tool, arguments))
            decision_log["harness_allowed"] = False
            decision_log["harness_reason"] = f"Ferramenta {tool} retornou erro."
            if loop_idx < est.max_loops:
                est.need_replanning = True
            return PARAR
        canal.emit({"type": "tool_complete", "id": _current_tid, "status": "ok",
               "duration_ms": canal.dur(_current_tid),
               "resumo": previsualizar(result)})
        rotas.concluiu(orcamento, rota_em_tentativa, telemetry)
        est.unresolved_tool_failure = None
        # E este resultado que volta se a chamada se repetir.
        repetidas.registrar(tool, arguments, result)
        deliberation["stop_reason"] = None

        # Hooks dependem da conclusão da ferramenta, não da decisão
        # do modelo; assim ações obrigatórias acompanham cada edição.
        hooks.depois_da_ferramenta(state, tool, result)

        # Salva os filtros aplicados com sucesso
        if tool in ANALYSIS_TOOLS:
            for f_key in chaves_de_recorte():
                val = arguments.get(f_key)
                if val:
                    # So persiste o recorte que o usuario PEDIU:
                    # herdado de novo, prenderia a conversa num
                    # filtro que ninguem escolheu.
                    if recorte_foi_pedido(f_key, user_message):
                        state.filtros[f_key] = val

        # O resultado vira o que o usuario ve (harness/anexo_do_resultado.py):
        # entrega que encerra o turno, anexo que o modelo ainda confere, ou nada.
        _rumo, _anexo, _resposta = await anexo_do_resultado(
            tool, arguments, result, state, anexos_do_turno,
            orq._validate_and_fix_html_attachment)
        if _rumo == "seguir":
            return SEGUIR
        if _rumo in ("parar", "anexar"):
            est.attachment = _anexo
        if _rumo == "anexar" and (not isinstance(result, dict) or "png_bytes" in result):
            result = {"arquivo": (_anexo or {}).get("caminho"), "conferir_o_arquivo": _resposta}
        if _rumo == "parar":
            est.export_response = _resposta
            return PARAR
        if _rumo == "encerrar":
            # Os passos que vieram junto ainda rodam; só a volta ao modelo deixa de acontecer.
            est.export_response = _resposta

        # Adiciona o resultado no histórico da sessão
        instruction = build_tool_result_instruction(tool, result, sessao=state.session_id)
        if tool in ANALYSIS_TOOLS and state.last_result_id:
            instruction = f"ID DO RESULTADO NA SESSÃO: '{state.last_result_id}'\n" + instruction
        state.history.append(marcar_chamada({"role": "system", "content": instruction}, step, tool, arguments))
        # Uma ref só existe depois da observação que a criou. Se o
        # planner listou navegar + clicar no mesmo plano, a segunda
        # ação usaria uma ref imaginada; volte ao modelo agora. Idem com `parar_sequencia`.
        if tool == "browser" or (isinstance(result, dict) and result.get("parar_sequencia")):
            est.need_replanning = True
            return PARAR

    except Exception as exc:
        logger.warning("Falha ao executar ferramenta %s: %s", tool, exc)
        canal.emit({"type": "tool_complete", "id": _current_tid, "status": "error",
                           "duration_ms": canal.dur(_current_tid),
                           "resumo": f"{type(exc).__name__}: {exc}"[:400]})
        result = {"erro": str(exc)}
        tool_results.append({"tool": tool, "result": result})
        est.unresolved_tool_failure = (tool, result)
        rotas.falhou(tool, arguments, result)
        instruction = build_tool_result_instruction(tool, result)
        state.history.append(marcar_chamada({"role": "system", "content": instruction}, step, tool, arguments))
        decision_log["harness_allowed"] = False
        decision_log["harness_reason"] = f"Ferramenta {tool} falhou com excecao."
        if loop_idx < est.max_loops:
            est.need_replanning = True
        return PARAR
    return SEGUIR
