"""A abertura do turno: tudo o que roda uma vez antes do laço de ferramentas.

Comando de barra e saudação terminam o turno aqui. Nos outros casos sai um
`AberturaDoTurno` com o que o laço lê: a complexidade, o registro de decisão,
o contexto recuperado e o passo a retomar, quando a pessoa acabou de aprovar um.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from ..artifacts import empty_validation_result, plan_artifact_request

logger = logging.getLogger(__name__)


@dataclass
class AberturaDoTurno:
    compacted: Any
    complexity: Optional[str]
    decision_log: Dict[str, Any]
    contexto_adicional: Any
    rag_context: Any
    retomar_passo: Optional[Dict[str, Any]]
    council_requested: bool = False


def _marcar_troca_de_setor(state: Any) -> None:
    """Anota no histórico quando o setor mudou no meio da conversa.

    Sem isto a persona trocava em silêncio: o que está acima foi conversado
    com outro vocabulário e outras ferramentas, e o modelo lia tudo como se
    fosse do setor de agora.
    """
    try:
        from ..domains import get_active_domain
        from ..domains.escolha import caminho

        ativo = get_active_domain().name
        anterior = ""
        for msg in reversed(state.history):
            if msg.get("role") == "system" and "[SETOR]" in str(msg.get("content") or ""):
                anterior = str(msg["content"]).split("[SETOR]", 1)[1].strip().split()[0]
                break
        if not anterior:
            # Primeira mensagem da conversa não é troca: é o começo.
            if state.history:
                state.history.append({
                    "role": "system",
                    "content": f"[SETOR] {ativo}",
                })
            return
        if anterior == ativo:
            return
        state.history.append({
            "role": "system",
            "content": (
                f"[SETOR] {ativo} — o setor mudou de '{anterior}' para '{ativo}' agora. "
                f"O que está acima nesta conversa foi tratado no setor '{anterior}', com "
                "outro vocabulário e outras ferramentas. Não trate aqueles números e termos "
                "como se fossem deste setor, e não prometa análise que só existia lá."
            ),
        })
        logger.info("Setor mudou de '%s' para '%s' no meio da conversa.", anterior, ativo)
    except Exception as exc:
        logger.debug("Nao consegui marcar a troca de setor: %s", exc)


async def abrir(
    orq: Any, state: Any, user_message: str, *, telemetry: Dict[str, Any],
    start_time: float, canal: Any,
) -> Union[AberturaDoTurno, Dict[str, Any]]:
    """O resultado pronto quando o turno termina aqui; senão, o que o laço lê."""
    # Comandos de barra têm execução direta e não consomem uma chamada de modelo.
    from .comando_de_barra import responder as _comando_de_barra
    de_barra = await _comando_de_barra(orq, state, user_message)
    if de_barra is not None:
        return de_barra

    _marcar_troca_de_setor(state)

    # O orçamento de contexto é aplicado antes de formar o próximo pedido.
    compacted = await orq.context_budget_manager.manage(state, progress_cb=canal.emit)

    from .antecedentes import extrair

    orq._chave_antecedentes = (id(state), user_message)
    orq._antecedentes_do_turno = extrair(state)
    init_is_follow_up, init_relevant_results = orq._detect_follow_up_and_extract_context(user_message, state)
    telemetry["antecedentes_disponiveis"] = init_is_follow_up
    telemetry["context_injected_count"] = len(init_relevant_results)

    from .configuracao_do_turno import configurar
    complexity, council_requested = await configurar(orq, user_message, state, telemetry)

    state.history.append({"role": "user", "content": user_message, "priority": "NORMAL"})
    from .aviso_de_sensivel import detectar, nota_para_o_modelo  # avisa, nao redige
    if _sensivel := detectar(user_message):
        state.history.append({"role": "system", "content": nota_para_o_modelo(_sensivel), "priority": "HIGH"})

    # Uma ação aprovada retoma antes do planejamento para executar o mesmo
    # passo bloqueado, com os argumentos que o usuário autorizou. Sem aprovação,
    # a mensagem nova é outro pedido, e o modelo só fica sabendo que o passo não rodou.
    from .retomada import aprovada, linha_de_contexto, linha_sem_aprovacao

    _pendente = getattr(state, "tarefa_pendente", None)
    if isinstance(_pendente, dict) and _pendente.get("pedido"):
        _sessao = str(getattr(state, "session_id", "") or "")
        if _pendente.get("equipe"):
            # Cartão de equipe: cada marcado foi aprovado com o próprio comando.
            from .equipe import aprovados, linha

            _membros = aprovados(_pendente["equipe"], _sessao)
            _texto = linha(_membros, _pendente["equipe"]) if _membros else linha_sem_aprovacao(_pendente)
            _retomar_passo = {**_pendente, "equipe": _membros} if _membros else None
        else:
            _liberada = aprovada(_pendente, _sessao)
            _texto = linha_de_contexto(_pendente) if _liberada else linha_sem_aprovacao(_pendente)
            _retomar_passo = dict(_pendente) if _liberada and _pendente.get("ferramenta") else None
        state.history.append({"role": "system", "content": _texto, "priority": "HIGH"})
        state.tarefa_pendente = None
    else:
        _retomar_passo = None


    decision_log: Dict[str, Any] = {
        "proposed_tool": None,
        "harness_allowed": True,
        "harness_reason": "Executado via pipeline determinístico",
        "planner_model": None,
        "planner_reasoning_summary": None,
        "responder_model": None,
        "responder_reasoning_summary": None,
        "events": [],
        "council_requested": council_requested,
        "ferramentas": [],  # o que rodou no turno
        "dado_sensivel": _sensivel,  # para a tela poder marcar a mensagem
        "artifact_plan": plan_artifact_request(),
        "artifact_validation": empty_validation_result(),
        # se a retomada bloquear de novo, o pedido guardado continua o original
        "pedido_retomado": (_retomar_passo or {}).get("pedido"),
        "planner_mode": None,
    }

    # O contexto recuperado fica disponível antes de escolher ferramentas.
    contexto_adicional = await orq._contexto_do_turno(state, decision_log)

    # Experiência e conhecimento chegam pelas ferramentas de consulta, quando o
    # modelo pede; a abertura não busca nada por conta própria.
    return AberturaDoTurno(
        compacted=compacted, complexity=complexity, decision_log=decision_log,
        contexto_adicional=contexto_adicional, rag_context="",
        retomar_passo=_retomar_passo, council_requested=council_requested,
    )
