"""O Conselho no turno: quando ele roda e sobre quais resultados.

Cinco pareceres sobre dado vazio viram cinco invenções coerentes entre si, por
isso o conselho só roda quando há resultado de análise com dado de verdade.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from ..domains.do_setor import entregas as _entregas_do_setor
from .classificacao import falhou
from .policy import ANALYSIS_TOOLS
from .state import AnalysisState

logger = logging.getLogger(__name__)


async def consultar(
    orq,
    user_message: str,
    state: AnalysisState,
    tool_results: List[Dict[str, Any]],
    telemetry: Dict[str, Any],
    decision_log: Dict[str, Any],
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """O Conselho, quando ele tem o que analisar.

    Caro: seis chamadas de LLM, perto de 40s. Por isso duas guardas
    deterministicas, e cada uma existe por um motivo diferente:

    - **Nao roda sobre dado vazio ou falho.** Cinco conselheiros opinando
      sem dado nao produzem cinco duvidas: produzem cinco invencoes
      coerentes entre si, que e a forma mais convincente de alucinacao.
    - **Nao roda quando o turno JA e a entrega** (um plano de acao, por
      exemplo). Ali o plano e a resposta; um conselho por cima vira
      comentario sobre o proprio trabalho.

    Devolve o contexto para o responder e a analise estruturada para a
    interface.
    """
    council_ctx = ""
    council_analysis = None
    # Quem ENTREGA um documento neste turno; nao cabe conselho sobre a
    # propria entrega. Quais ferramentas fazem isso e do setor.
    _entregam = {n for n, e in _entregas_do_setor().items() if e.get("arquivo")}
    plano_no_turno = any(str(tr.get("tool")) in _entregam for tr in tool_results)
    fontes = fontes_do_conselho(tool_results, state)
    pedido = decision_log.get("council_requested") and fontes

    if pedido and not plano_no_turno and tem_dado_para_o_conselho(fontes):
        inicio = time.time()
        council_analysis = await orq.council.analyze(user_message, fontes)
        telemetry["council_ms"] = int((time.time() - inicio) * 1000)
        council_llm = getattr(orq.council, "llm", None)
        decision_log["council_model"] = getattr(council_llm, "last_model", None)
        decision_log["council_reasoning_summary"] = getattr(
            council_llm, "last_reasoning_summary", None
        )
        resumo = {
            "trade_offs": council_analysis.get("trade_offs", []),
            "consensus_recommendation": council_analysis.get("consensus_recommendation", ""),
        }
        council_ctx = f"\n\n### Análise do Conselho:\n{json.dumps(resumo, ensure_ascii=False, indent=2)}"
    elif pedido:
        logger.info("Conselho PULADO: dados vazios/falhos ou turno de entrega (plano). Evita alucinação.")

    return council_ctx, council_analysis


def analises_do_turno(tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "")
        result = item.get("result")
        if falhou(result):
            continue
        if tool in ANALYSIS_TOOLS and tool != "executar_python" and result not in (None, [], {}):
            items.append({"tool": tool, "result": result})
    return items


def analises_da_sessao(state: AnalysisState) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for result_id in sorted((getattr(state, "results", {}) or {}).keys()):
        stored = (state.results or {}).get(result_id) or {}
        tool = str(stored.get("tool") or "")
        result = stored.get("summary")
        if falhou(result):
            continue
        if tool in ANALYSIS_TOOLS and tool != "executar_python" and result not in (None, [], {}):
            items.append({"tool": tool, "result": result})
    return items


def fontes_do_conselho(
    tool_results: List[Dict[str, Any]],
    state: AnalysisState,
) -> List[Dict[str, Any]]:
    """Merge this turn's evidence with prior grounded analyses for Council."""
    merged: List[Dict[str, Any]] = []
    seen = set()
    for item in analises_do_turno(tool_results) + analises_da_sessao(state):
        tool = str(item.get("tool") or "")
        fingerprint = f"{tool}:{json.dumps(item.get('result'), ensure_ascii=False, sort_keys=True, default=str)[:600]}"
        if fingerprint not in seen:
            seen.add(fingerprint)
            merged.append(item)
    return merged


def _tem_conteudo(valor: Any) -> bool:
    """Há algo além de casca vazia. Número conta, zero inclusive: é dado."""
    if valor is None:
        return False
    if isinstance(valor, str):
        return bool(valor.strip())
    if isinstance(valor, dict):
        return any(_tem_conteudo(v) for v in valor.values())
    if isinstance(valor, (list, tuple, set)):
        return any(_tem_conteudo(v) for v in valor)
    return True


def tem_dado_para_o_conselho(tool_results: List[Dict[str, Any]]) -> bool:
    """Algum resultado traz dado de verdade. Cinco pareceres sobre uma lista
    vazia inventam valores, metas e ferramentas coerentes entre si. A decisão
    olha a estrutura do resultado (a análise sem achado devolve `[]`), não o
    texto, que muda de língua e de frase."""
    for item in (tool_results or []):
        result = item.get("result") if isinstance(item, dict) else None
        if not falhou(result) and _tem_conteudo(result):
            return True
    return False
