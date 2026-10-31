"""O laço do turno: planeja, executa os passos e decide se dá mais uma volta.

O estado que atravessa as voltas mora em `Laco`. O passo recebe o mesmo objeto
e o muda direto, então nada é copiado de ida e volta entre o laço e o passo.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import settings
from . import caixa_do_turno
from .bloco import entradas_do_plano, id_do_passo
from .execucao_do_passo import PARAR, EstadoDoPasso, executar as executar_passo
from .gravacao_do_turno import ExecutadasNoTurno
from .grounding import havia_dado_de_fora
from .loop_budget import BudgetTracker, StopReason, orcamento_do_turno
from .narracao import Narrador, apos_planejar, limpar as limpar_fala
from .policy import SKILL_TOOLS
from .repeticao import Repetidas
from .resposta_direta import AVISO_CHAMADA_EM_TEXTO
from .rotas import RastreadorDeRota
from .pausa_do_turno import autorizacao_pendente, resultado_de_pergunta, resultado_de_permissao
from .artefato_do_turno import recusar_artefato_sem_lastro

logger = logging.getLogger(__name__)


@dataclass
class Laco(EstadoDoPasso):
    """O que vale para o turno inteiro, além do que cada passo muda."""

    loop_idx: int = 0
    # Com o laço livre quem para é o orçamento (ferramentas, tokens, tempo,
    # falhas, não-progresso); `max_loops` fica só como disjuntor.
    livre: bool = False
    avisou_chamada: bool = False
    exit_reason: Optional[str] = None
    tool_results: Any = None
    # Sem resultado com origem conhecida, artefato numérico não sai como se
    # viesse de uma análise desta sessão.
    pre_turn_had_data: bool = False
    # O anexo principal fica em `attachment`; a lista guarda as entregas múltiplas.
    anexos_do_turno: List[Dict[str, Any]] = field(default_factory=list)
    turn_activated_skills: List[str] = field(default_factory=list)
    # A trilha liga objetivo, passos e motivo de parada à resposta entregue.
    deliberation: Dict[str, Any] = field(default_factory=dict)
    orcamento: Any = None
    repetidas: Any = None
    rotas: Any = None
    narrador: Any = None

    def ha_volta(self) -> bool:
        return self.loop_idx < self.max_loops and not (self.livre and self.orcamento.exhausted())


def novo(orq: Any, state: Any, user_message: str, aberto: Any) -> Laco:
    livre = bool(getattr(settings, "SENTURY_AGENT_LOOP", False))
    orcamento = orcamento_do_turno(settings, getattr(state, "funcoes_ativas", None))  # computador e navegador vão longe
    return Laco(
        livre=livre,
        max_loops=orcamento.max_loops if livre else 2,
        tool_results=ExecutadasNoTurno(aberto.decision_log["ferramentas"]),
        pre_turn_had_data=bool(getattr(state, "last_result_id", None))
        or havia_dado_de_fora(state, orq._GROUNDING_TOOLS),
        # llm-council é skill nativa: o card visual fica, sem despejar o SKILL.md no modelo.
        turn_activated_skills=["llm-council"] if aberto.council_requested else [],
        deliberation={"objective": orq._derive_objective(user_message), "steps": [],
                      "status": "investigating", "stop_reason": None},
        orcamento=BudgetTracker(budget=orcamento),
        repetidas=Repetidas(),
        rotas=RastreadorDeRota(),
        narrador=Narrador(),
    )


async def _planejar(orq: Any, laco: Laco, state: Any, user_message: str, aberto: Any,
                    telemetry: Dict[str, Any], canal: Any) -> List[Dict[str, Any]]:
    if laco.loop_idx == 1:
        from .configuracao_do_turno import primeira_volta

        plano, planejou = await primeira_volta(
            orq, user_message, state, aberto.contexto_adicional, aberto.rag_context, aberto.complexity,
            aberto.decision_log, telemetry,
        )
        if planejou:
            apos_planejar(orq, aberto.decision_log, laco.narrador, canal.emit_reasoning)
    else:
        logger.info("Re-planejando com o resultado na mão (iteração %d)...", laco.loop_idx)
        plano = await orq._generate_plan(user_message, state, aberto.contexto_adicional, aberto.rag_context,
                                         aberto.complexity, is_replanning=True)
        apos_planejar(orq, aberto.decision_log, laco.narrador, canal.emit_reasoning)
    # Uma skill procedural entra no contexto antes do plano final; fora isso, a
    # primeira volta retoma a chamada que estava bloqueada e acabou de ser
    # aprovada. Nada aqui interpreta intenção pelo texto do pedido.
    ativa_skill = any(
        isinstance(passo, dict) and str(passo.get("tool") or "") in (SKILL_TOOLS | set(orq.procedural_skills))
        for passo in (plano or [])
    )
    if not ativa_skill and laco.loop_idx == 1:
        plano = orq._injetar_passo_retomado(plano, aberto.retomar_passo)
    return plano


async def _sem_plano(orq: Any, laco: Laco, state: Any, user_message: str, aberto: Any,
                     telemetry: Dict[str, Any]) -> bool:
    """O modelo respondeu sem chamar nada. Devolve se vale mais uma volta."""
    ainda_ha = laco.loop_idx < laco.max_loops
    if orq.turno.chamada_em_texto and not laco.avisou_chamada and ainda_ha:
        laco.avisou_chamada = True
        state.history.append({"role": "system", "content": AVISO_CHAMADA_EM_TEXTO})
        return True
    if ainda_ha and (rota_pendente := laco.rotas.aviso_se_parou()):
        state.history.append({"role": "system", "content": rota_pendente})
        return True
    from .afirmacao_de_arquivo import conferir_fechamento

    if laco.ha_volta() and await conferir_fechamento(
            orq, state, user_message, aberto.contexto_adicional, aberto.rag_context, aberto.complexity,
            laco.attachment, laco.tool_results, aberto.decision_log, telemetry):
        return True
    return laco.ha_volta() and caixa_do_turno.aplicar(state)  # orientação chegou enquanto planejava


def _antes_de_executar(orq: Any, laco: Laco, state: Any, user_message: str, aberto: Any,
                       telemetry: Dict[str, Any], canal: Any) -> Optional[Dict[str, Any]]:
    """Pergunta ou permissão que param o turno antes do primeiro passo."""
    from .esclarecimento import resolver as resolver_pergunta
    from .orchestrator import MAX_PERGUNTAS_SEGUIDAS

    decision_log = aberto.decision_log
    # Falta contexto essencial: a pergunta vai à interface como opções clicáveis.
    # Perguntar custa um turno; as exceções moram em harness/esclarecimento.py.
    laco.plano, pergunta = resolver_pergunta(
        orq, laco.plano, state=state, user_message=user_message,
        retomar=aberto.retomar_passo, max_perguntas_seguidas=MAX_PERGUNTAS_SEGUIDAS,
    )
    if pergunta:
        decision_log["proposed_tool"] = "perguntar_usuario"
        decision_log["harness_allowed"] = True
        decision_log["harness_reason"] = "Esclarecimento: faltava contexto essencial; perguntando antes de agir."
        canal.emit({"type": "clarification", "clarification": pergunta})
        return resultado_de_pergunta(orq, state, user_message, pergunta, decision_log, telemetry)
    if not laco.plano:
        return None
    # O checklist ao vivo, todos os passos `pending`. Ver harness/bloco.py.
    entradas = entradas_do_plano(laco.plano, laco.loop_idx, orq._tool_title, limpar_fala)
    if entradas:
        canal.emit({"type": "plan_update", "entries": entradas})
    # A aprovação se decide antes do primeiro passo: pausar no meio descartaria
    # o trabalho já feito no mesmo plano.
    pendente = autorizacao_pendente(orq, laco.plano, state)
    if pendente:
        decision_log["proposed_tool"] = pendente.get("ferramenta") or ""
        decision_log["harness_allowed"] = False
        decision_log["harness_reason"] = (
            f"Permissao pendente para '{pendente.get('chave') or pendente.get('ferramenta')}'"
        )
        canal.emit({"type": "permissao", "permissao": pendente,
                    "id": id_do_passo(laco.plano, pendente.get("ferramenta"), laco.loop_idx)})
        return resultado_de_permissao(orq, state, user_message, pendente, decision_log, telemetry)
    return None


def _depois_dos_passos(orq: Any, laco: Laco, state: Any, rodou_agora: bool, puladas_no_inicio: int) -> None:
    """Decide se o modelo vê o resultado de novo e confere o anexo do turno."""
    # Volta só de repetições conta como não-progresso: sem isto um modelo preso
    # no mesmo plano replaneja até o teto.
    if not rodou_agora and laco.repeticoes_puladas > puladas_no_inicio:
        laco.orcamento.volta_sem_efeito()
    # Rodou ferramenta (ou levou o lembrete de repetição): o modelo decide de
    # novo vendo o resultado. Sem isto ele decide tudo antes de existir dado.
    if (laco.livre and not laco.export_response and not laco.need_replanning
            and (rodou_agora or laco.avisou_repeticao) and not laco.orcamento.exhausted()):
        laco.need_replanning = True
    if not laco.export_response and laco.ha_volta() and caixa_do_turno.aplicar(state):  # orientação: mais uma volta
        laco.need_replanning = True
    if laco.export_response and laco.attachment:
        validado = laco.attachment
        laco.attachment, resposta = recusar_artefato_sem_lastro(orq,
            state, laco.attachment, laco.export_response, laco.tool_results,
            pre_turn_had_data=laco.pre_turn_had_data,
        )
        if laco.attachment is None:
            laco.anexos_do_turno[:] = [a for a in laco.anexos_do_turno if a != validado]
            laco.export_response = None
            laco.need_replanning = True
        else:
            laco.export_response = resposta


async def rodar(orq: Any, laco: Laco, *, state: Any, user_message: str, aberto: Any,
                telemetry: Dict[str, Any], canal: Any) -> Optional[Dict[str, Any]]:
    """Roda as voltas. Devolve o resultado quando o turno para no meio (pergunta,
    permissão, passo que encerra); `None` quando o laço fecha e falta o fechamento."""
    while laco.ha_volta():
        laco.loop_idx += 1
        laco.orcamento.record_iteration()
        laco.need_replanning = False
        laco.avisou_repeticao = False
        # `tool_results` acumula entre voltas: comparar com o início diz "rodou agora".
        resultados_no_inicio = len(laco.tool_results)
        puladas_no_inicio = laco.repeticoes_puladas

        laco.plano = await _planejar(orq, laco, state, user_message, aberto, telemetry, canal)
        if not laco.plano:
            if await _sem_plano(orq, laco, state, user_message, aberto, telemetry):
                laco.need_replanning = True
                continue
            laco.exit_reason = StopReason.COMPLETED
            break

        parada = _antes_de_executar(orq, laco, state, user_message, aberto, telemetry, canal)
        if parada is not None:
            return parada
        if not laco.plano:
            break

        inicio = time.time()
        for indice, passo in enumerate(laco.plano):
            rumo = await executar_passo(
                orq, laco, passo, indice, state=state, user_message=user_message, telemetry=telemetry,
                decision_log=aberto.decision_log, deliberation=laco.deliberation, tool_results=laco.tool_results,
                anexos_do_turno=laco.anexos_do_turno, turn_activated_skills=laco.turn_activated_skills,
                loop_idx=laco.loop_idx, ha_volta=laco.ha_volta,
                loop_livre=laco.livre, orcamento=laco.orcamento, repetidas=laco.repetidas, rotas=laco.rotas,
                narrador=laco.narrador, canal=canal,
            )
            if isinstance(rumo, dict):
                return rumo
            if rumo == PARAR:
                break
        telemetry["execution_ms"] = int((time.time() - inicio) * 1000)

        _depois_dos_passos(orq, laco, state, len(laco.tool_results) > resultados_no_inicio, puladas_no_inicio)
        if laco.export_response:
            laco.exit_reason = StopReason.TOOL_FAILURE if laco.unresolved_tool_failure else StopReason.COMPLETED
            break
        if laco.need_replanning:
            continue
        laco.exit_reason = StopReason.COMPLETED
        break
    return None


__all__ = ["Laco", "novo", "rodar"]
