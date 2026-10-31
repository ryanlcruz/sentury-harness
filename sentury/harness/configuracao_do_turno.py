"""Chamadas nativas e planos em texto passam pelo mesmo laço do turno."""
from __future__ import annotations

import time

from .passo_unico import ativo
from .classificacao import falhou, pendente
from ..llm.effort import active_effort
from .conselho_do_turno import analises_da_sessao, tem_dado_para_o_conselho


def conselho_pedido(mensagem, estado):
    return (
        "llm-council" in (getattr(estado, "funcoes_ativas", None) or [])
        or str(mensagem or "").lstrip().lower().startswith("[llm-council]")
    )


def modo_nativo(estado):
    """O modo do planejador nos dois caminhos: a função `plano` marcada ou o
    esforço escolhido, nunca palavra da mensagem."""
    if "plano" in (getattr(estado, "funcoes_ativas", None) or []):
        return "action_plan"
    return "deliberate" if active_effort() in {"high", "xhigh"} else "lightweight"


async def configurar(orquestrador, mensagem, estado, telemetria):
    """O turno não classifica o pedido antes do modelo: quem decide é o laço.
    A complexidade vem do esforço escolhido e serve de dica para a cadeia."""
    orquestrador.turno.passo_unico = ativo(orquestrador.planner)
    conselho = conselho_pedido(mensagem, estado)
    complexidade = {"low": "SIMPLE", "medium": "STANDARD", "high": "COMPLEX",
                    "xhigh": "CRITICAL"}.get(active_effort())
    telemetria["despacho"] = "passo_unico" if orquestrador.turno.passo_unico else "texto"
    return complexidade, conselho


def experiencia_observada(resultados):
    """Somente passos concluídos podem virar receita consultável."""
    return [{"tool": r["tool"]} for r in resultados
            if r.get("tool") and not r.get("is_error")
            and not falhou(r.get("result")) and not pendente(r.get("result"))]


def intencao_observada(passos):
    from ..tools.registry import TOOL_REGISTRY

    tipos = [TOOL_REGISTRY.get(p["tool"], {}).get("intencao") for p in passos]
    return next((t for t in reversed(tipos) if t), "ferramentas" if passos else "conversa")


async def primeira_volta(orq, mensagem, estado, contexto, conhecimento, complexidade, log, telemetria):
    if not orq.turno.passo_unico and log["council_requested"]:
        fontes = analises_da_sessao(estado)
        if tem_dado_para_o_conselho(fontes):
            log["planner_mode"] = "native_council"
            return [], False
        from ..domains.do_setor import analise_de_base
        base = analise_de_base()
        log["planner_mode"] = "native_council_grounding"
        return ([{"tool": base, "arguments": {}}] if base else []), False
    modo = modo_nativo(estado)
    log["planner_mode"] = modo
    inicio = time.perf_counter()
    plano = await orq._generate_plan(mensagem, estado, contexto, conhecimento, complexidade, planner_mode=modo)
    telemetria["planner_ms"] = round((time.perf_counter() - inicio) * 1000)
    log["capability_matches"] = list(orq.turno.capacidades_achadas)
    return plano, True
