"""O artefato do turno: o passo que exporta, o plano que vira card, o HTML que
não aparece duas vezes e o artefato numérico que não sai sem dado de origem.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..domains.do_setor import dimensoes as _dimensoes_do_setor
from ..domains.do_setor import entregas as _entregas_do_setor
from .policy import ANALYSIS_TOOLS, EXPORT_TOOLS
from .state import AnalysisState


def plano_vira_card(
    orq,
    state: AnalysisState,
    plano_no_turno: bool,
    attachment: Optional[Dict[str, Any]],
    reply_text: str,
) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """O plano de acao sai da bolha e vira anexo.

    A bolha fica com a introducao; a pergunta final aparece DEPOIS do card,
    em `plan_question`. Sem isso o plano apareceria inteiro nos dois
    lugares.
    """
    if not (plano_no_turno and not attachment and reply_text):
        return attachment, reply_text, None

    # Quando o modelo REESCREVEU o esqueleto, o documento chega como texto
    # da resposta: e o nome e o titulo do card tem que ser os mesmos que o
    # caminho sem reescrita usa, senao o mesmo plano baixa com dois nomes
    # diferentes dependendo do provedor que atendeu.
    entrega = next(
        (e for e in _entregas_do_setor().values() if e.get("arquivo")), {},
    )
    intro, body, question = separar_plano(reply_text)
    attachment = {
        "type": "markdown",
        "filename": entrega.get("arquivo") or "documento.md",
        "mime_type": "text/markdown",
        "content": body or reply_text,
        "title": entrega.get("titulo") or "Documento",
    }
    if not body:
        return attachment, reply_text, None

    reply_text = intro or (
        "Pronto, montei o plano de ação. Dá pra baixar em .md, exportar em PDF "
        "ou enviar pro Tasks."
    )
    # O historico ja recebeu o texto INTEIRO. Sem corrigir aqui, reabrir a
    # conversa reconstroi a bolha com o plano completo E mostra o card
    # embaixo: o plano duplicado. O conteudo segue no contexto do modelo
    # pelo esqueleto (mensagem system) e em `results`.
    for msg in reversed(state.history):
        if msg.get("role") == "assistant":
            msg["content"] = reply_text
            break
    return attachment, reply_text, question or None


def normalizar_passo_de_artefato(
    step: Dict[str, Any],
    artifact_plan: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Traduz helpers de artefato que um planner pode citar como se fossem
    tools para a única entrada segura: ``executar_python`` no sandbox.

    ``save_svg_diagram`` é uma função pré-carregada no sandbox, não uma tool
    do Harness. Sem esta adaptação, um plano correto no conteúdo acabava
    bloqueado como "ferramenta desconhecida" antes de produzir o SVG.
    """
    if not isinstance(step, dict):
        return None

    tool = str(step.get("tool") or "").strip()
    arguments = step.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}
    from ..llm.tool_schemas import acao_no_nome

    com_acao, argumentos_com_acao = acao_no_nome(tool, arguments)
    if com_acao != tool:  # `computador.ver` é `computador` com `acao: ver`
        return {**step, "tool": com_acao, "arguments": argumentos_com_acao}

    if tool == "save_svg_diagram":
        raw_boxes = arguments.get("boxes") or arguments.get("nodes") or []
        raw_arrows = arguments.get("arrows") or arguments.get("connections") or []
        if not isinstance(raw_boxes, list) or not raw_boxes:
            return None

        boxes: List[Dict[str, Any]] = []
        for index, raw_box in enumerate(raw_boxes[:12], start=1):
            raw_box = raw_box if isinstance(raw_box, dict) else {"text": raw_box}
            text = str(raw_box.get("text") or raw_box.get("label") or "").strip()
            if not text:
                continue
            entry: Dict[str, Any] = {
                "id": str(raw_box.get("id") or f"N{index}")[:32],
                "text": text[:160],
                "color": str(raw_box.get("color") or "blue")[:16],
            }
            if raw_box.get("level") is not None:
                try:
                    entry["level"] = max(0, min(8, int(raw_box["level"])))
                except (TypeError, ValueError):
                    pass
            boxes.append(entry)
        if not boxes:
            return None

        box_ids = {box["id"] for box in boxes}
        arrows: List[Dict[str, str]] = []
        for raw_arrow in raw_arrows[:20] if isinstance(raw_arrows, list) else []:
            if not isinstance(raw_arrow, dict):
                continue
            source = str(raw_arrow.get("from") or raw_arrow.get("source") or "")[:32]
            target = str(raw_arrow.get("to") or raw_arrow.get("target") or "")[:32]
            if source in box_ids and target in box_ids and source != target:
                arrows.append({"from": source, "to": target})

        layout = str(arguments.get("layout") or artifact_plan.get("layout_hint") or "flow")
        if layout not in {"flow", "tree", "star", "funnel"}:
            layout = "flow"
        title = str(arguments.get("title") or "Diagrama Sentury")[:96]
        filename = str(arguments.get("filename") or "diagrama-sentury.svg")
        code = (
            f"boxes = {boxes!r}\n"
            f"arrows = {arrows!r}\n"
            f"save_svg_diagram({filename!r}, boxes, arrows, layout={layout!r}, title={title!r})"
        )
        return {
            "action": "tool_call",
            "tool": "executar_python",
            "arguments": {"codigo": code},
        }

    if tool == "save_svg":
        svg_content = str(arguments.get("svg_content") or arguments.get("content") or "").strip()
        if not svg_content:
            return None
        filename = str(arguments.get("filename") or "artefato-sentury.svg")
        return {
            "action": "tool_call",
            "tool": "executar_python",
            "arguments": {"codigo": f"save_svg({filename!r}, {svg_content!r})"},
        }

    if tool in {"save_html", "save_html_dashboard"}:
        html_content = str(
            arguments.get("html_content")
            or arguments.get("html")
            or arguments.get("content")
            or ""
        ).strip()
        if not html_content:
            return None
        filename = str(arguments.get("filename") or "artefato-sentury.html")
        return {
            "action": "tool_call",
            "tool": "executar_python",
            "arguments": {"codigo": f"save_html({filename!r}, {html_content!r})"},
        }

    normalizado = {"action": "tool_call", "tool": tool, "arguments": arguments}
    if isinstance(step, dict) and step.get("id"):
        # Preserva o id do provedor para ligar chamada e resultado.
        normalizado["id"] = step["id"]
    return normalizado


def recorte_foi_pedido(dimensao: str, user_message: str) -> bool:
    """Se o usuario citou o recorte nesta mensagem.

    Dimensao que o setor nao declara passa direto: periodo nao tem lista de
    valores, e exigir uma faria o filtro de data parar de funcionar.
    """
    valores = _dimensoes_do_setor().get(dimensao)
    if valores is None:
        return True
    baixa = str(user_message or "").lower()
    return any(v.lower() in baixa for v in valores)


# Periodo vale para qualquer setor; as outras dimensoes sao as que o setor declara.
_RECORTES_DE_PERIODO = ("periodo_inicio", "periodo_fim")


def chaves_de_recorte() -> tuple:
    """Os argumentos de analise que a conversa guarda como filtro."""
    return tuple(_dimensoes_do_setor()) + _RECORTES_DE_PERIODO


def estrategia_visual(
    artifact_plan: Dict[str, Any],
    attachment: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    attachment = attachment or {}
    attachment_type = str(attachment.get("type") or "").lower().strip()
    preferred_format = str(artifact_plan.get("preferred_format") or "").lower().strip()

    if attachment_type == "chart_json":
        chart_data = attachment.get("chart_data") or {}
        options = chart_data.get("options") or {}
        return {
            "surface": "chart_inline",
            "chart_type": chart_data.get("type") or "bar",
            "index_axis": options.get("indexAxis", "x"),
            "artifact_kind": artifact_plan.get("artifact_kind"),
        }

    if attachment_type == "html":
        return {
            "surface": "dashboard_html",
            "artifact_kind": artifact_plan.get("artifact_kind"),
        }

    if attachment_type == "svg":
        return {
            "surface": "diagram_svg",
            "artifact_kind": artifact_plan.get("artifact_kind"),
            "layout_hint": artifact_plan.get("layout_hint"),
        }

    return {
        "surface": preferred_format or "inline",
        "artifact_kind": artifact_plan.get("artifact_kind"),
    }


def argumentos_de_exportacao(
    state: AnalysisState,
    tool: str,
    arguments: Dict[str, Any],
    decision: Any,
) -> Optional[Dict[str, Any]]:
    if tool not in EXPORT_TOOLS:
        return None

    source = str((arguments or {}).get("source") or "").strip()
    if not source or not state.last_result_id:
        return None

    if re.fullmatch(r"resultado_\d+", source, re.IGNORECASE):
        return None

    reason = str(getattr(decision, "reason", "") or "").lower()
    if "fonte de export" not in reason:
        return None

    adjusted = dict(arguments or {})
    adjusted.pop("source", None)
    return adjusted


def ultima_analise(tool_results: List[Dict[str, Any]]) -> Tuple[Optional[str], Any]:
    for item in reversed(tool_results or []):
        tool = str(item.get("tool") or "")
        if tool in ANALYSIS_TOOLS and tool != "executar_python":
            return tool, item.get("result")
    return None, None


def tirar_html_repetido(reply_text: str, attachment: Optional[Dict[str, Any]]) -> str:
    """Se o HTML virou attachment (card), remove o bloco de código do MESMO HTML
    da mensagem: senão o front renderiza DOIS previews (o inline + o card)."""
    if not attachment or not reply_text:
        return reply_text
    if "html" not in str(attachment.get("type") or "").lower():
        return reply_text

    _HTML_TAGS = r"<!doctype|<html|<head|<body|<div|<section|<main|<article|<header|<table|<style|<h[1-6]\b"

    def _drop(m):
        block = m.group(0)
        return "" if re.search(_HTML_TAGS, block, re.IGNORECASE) else block

    # 1. blocos ```...``` FECHADOS contendo HTML → fora.
    cleaned = re.sub(r"```[a-zA-Z]*\s*.*?```", _drop, reply_text, flags=re.DOTALL)
    # 2. documento HTML completo cru (com ou sem fence de abertura órfão antes).
    cleaned = re.sub(r"```html\b\s*(?=<)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<!doctype html.*?</html\s*>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    # 3. fragmento ESTRUTURAL cru (<div>/<section>/<main>/<table>… até o último '>').
    #    O attachment JÁ é esse HTML: qualquer span estrutural grande na mensagem é
    #    a duplicata (fence truncado pelo flash, ou HTML solto sem doctype).
    frag = re.search(r"<(?:div|section|main|article|header|table|h[1-6])\b.*>", cleaned,
                     re.IGNORECASE | re.DOTALL)
    if frag and len(frag.group(0)) > 25:
        cleaned = cleaned[:frag.start()] + cleaned[frag.end():]
    # 4. marcadores de fence órfãos de html e <style> soltos que sobraram.
    cleaned = re.sub(r"```html\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<style\b.*?</style>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or "Pronto — o HTML está no card abaixo. Dá pra abrir em tela cheia e baixar."


def recusar_artefato_sem_lastro(
    orq, state: AnalysisState, attachment: Optional[Dict[str, Any]],
    reply_text: str, tool_results: List[Dict[str, Any]], *, pre_turn_had_data: bool,
):
    from .recusa_de_artefato import julgar

    return julgar(state, attachment, reply_text, tool_results,
                  pre_turn_had_data=pre_turn_had_data,
                  grounding_tools=orq._GROUNDING_TOOLS)


def separar_plano(text: str):
    """Separa a mensagem do plano em (intro, plano, pergunta_final): o intro vai
    na bolha, o plano no card (sem duplicar o texto inteiro), e a pergunta final
    DEPOIS do card."""
    t = (text or "").strip()
    lines = t.split("\n")
    def _is_hr(l): return l.strip() in ("---", "***", "___")
    # O corpo do plano começa no PRIMEIRO elemento estruturado: não só num `#`.
    # O Insight (> [!INSIGHT]), os Indicadores (**...**) e o "Onde atacar" (**...**/
    # lista) vêm ANTES do `### Passo a passo` e não são heading; sem isso eles
    # vazavam pra bolha em vez de ir pro card. Intro = só a prosa de abertura.
    def _is_plan_start(l):
        s = l.lstrip()
        return (s.startswith(("#", ">", "**", "- ", "* ", "|"))
                or bool(re.match(r"^\d+[.)]\s", s)))
    h = next((i for i, l in enumerate(lines) if _is_plan_start(l)), None)
    if h is None:
        return t, "", ""
    intro = "\n".join(l for l in lines[:h] if not _is_hr(l)).strip()
    body = "\n".join(l for l in lines[h:] if not _is_hr(l)).strip()
    question = ""
    parts = body.rsplit("\n\n", 1)
    if len(parts) == 2:
        tail = parts[1].strip()
        if tail.endswith("?") and not tail.lstrip().startswith(("#", "-", "*", "|", ">")):
            body, question = parts[0].strip(), tail
    return intro, body, question
