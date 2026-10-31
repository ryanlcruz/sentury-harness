"""O plano de entrega descreve o que o turno produziu, não o que o pedido parece pedir.

Ler o pedido atrás de "pdf", "dashboard" ou "funil" só reconhece quem escreve
em português, com a grafia certa, e ainda trata menção como pedido. Quem
escolhe o formato é o modelo; o plano sai do anexo que de fato voltou da
ferramenta, e sem anexo a entrega é o texto da resposta.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from .contracts import ArtifactPlan

# tipo do anexo: (natureza, formato, gerador, conferência)
_POR_TIPO: Dict[str, Tuple[str, str, str, str]] = {
    "html": ("document", "html", "save_html", "html_preview"),
    "pptx": ("presentation", "pptx", "save_pptx", "pptx_structure"),
    "xlsx": ("spreadsheet", "xlsx", "export_xlsx", "binary_export"),
    "csv": ("spreadsheet", "csv", "export_csv", "binary_export"),
    "pdf": ("document", "pdf", "export_pdf", "binary_export"),
    "excalidraw": ("diagram", "excalidraw", "save_excalidraw", "excalidraw_json"),
    "svg": ("diagram", "svg", "save_svg_diagram", "svg_preview"),
    "chart_json": ("analysis", "chart", "generate_chart", "chart_payload"),
    "png": ("image", "png", "generate_chart", "binary_export"),
}

_TEXTO: ArtifactPlan = {
    "artifact_kind": "narrative",
    "preferred_format": "markdown",
    "generator": "inline_markdown",
    "validator": "none",
    "delivery_mode": "inline",
}


def plan_artifact_request(attachment: Optional[dict] = None) -> ArtifactPlan:
    tipo = str((attachment or {}).get("type") or "").lower().strip()
    conhecido = _POR_TIPO.get(tipo)
    if not conhecido:
        return dict(_TEXTO)  # type: ignore[return-value]
    natureza, formato, gerador, conferencia = conhecido
    return {
        "artifact_kind": natureza,
        "preferred_format": formato,
        "generator": gerador,
        "validator": conferencia,
        "delivery_mode": "attachment",
    }


def build_artifact_prompt() -> str:
    """Contrato de entrega: o formato é escolha do modelo, a prova é o resultado."""
    return (
        "### Entrega de artefatos\n"
        "- Interprete o pedido e o contexto em qualquer idioma, incluindo negacoes. "
        "Mencionar um formato ou pedir explicacao sobre ele nao e pedir sua geracao.\n"
        "- Voce decide se precisa de artefato, qual formato e quais ferramentas. "
        "Nao escale uma resposta simples para grafico, arquivo ou dashboard sem necessidade.\n"
        "- Quando criar/exportar, emita a chamada da ferramenta disponivel; "
        "nao afirme ter criado/anexado nada sem resultado real. "
        "Dados numericos devem vir de fontes ou resultados observados, nunca inventados.\n"
        "- Pergunte apenas quando faltar informacao indispensavel que nao possa "
        "obter pelas ferramentas; caso contrario prossiga.\n"
        "- Para HTML autoral ou diagramas, use `executar_python`: "
        "`save_html(nome, conteudo_html)` e `save_svg_diagram(..., layout='flow')` "
        "sao helpers pre-carregados, nao nomes de ferramentas. Escolha o layout "
        "adequado (flow, tree ou funnel). HTML pode ter CSS e JavaScript local/inline, "
        "mas deve funcionar offline, sem fetch, rede externa, iframes ou bibliotecas CDN.\n"
        "- Para uma pagina, apresentacao ou grafico com cuidado visual, o catalogo de "
        "skills tem as de design; carregue a que servir antes de escrever o codigo.\n"
        "- Codigo pedido apenas para LER vai em ```python normal e nao e executado. "
        "Uma cerca ```python run declara execucao; prefira a chamada da ferramenta.\n"
        "- Preserve os contratos de /chat e attachment; respeite formatos e "
        "editabilidade solicitados, sem depender de palavras em portugues.\n"
    )
