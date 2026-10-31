"""Gráficos dos resultados de análise.

O PNG sai local, pelo matplotlib. O QuickChart, serviço de fora, só entra com
`SENTURY_QUICKCHART` ligado, porque recebe os dados do gráfico. Também monta o
formato do Chart.js para o gráfico desenhado na tela.
"""
import io
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..artifacts import plan_visualization
from ..external import quickchart
from .shape import tabela_e_resumo

logger = logging.getLogger(__name__)


async def generate_chart(tool: str, result: Any, tipo: Optional[str] = None) -> bytes:
    tabela, _ = tabela_e_resumo(tool, result)
    if not tabela:
        raise ValueError("nenhuma tabela disponivel neste resultado para gerar grafico")

    if tool == "correlate":
        rotulos, x, y = _pontos_correlate(tabela)
        if not x:
            raise ValueError("nenhum dado numerico disponivel neste resultado para gerar grafico")
        quickchart_config = _chart_js_scatter(x, y)
        montar_figura_local: Callable[[], Tuple[Any, Any]] = lambda: _figura_correlate(rotulos, x, y)
    else:
        visual = plan_visualization(tool=tool, table=tabela, tipo=tipo)
        if not visual["values"]:
            raise ValueError("nenhum dado numerico disponivel neste resultado para gerar grafico")
        quickchart_config = _chart_js_config(
            visual["title"],
            visual["display_labels"],
            visual["values"],
            visual["chart_type"],
            index_axis=visual["index_axis"],
        )
        montar_figura_local = lambda: _figura_padrao(
            visual["display_labels"],
            visual["values"],
            visual["chart_type"],
            index_axis=visual["index_axis"],
        )

    from ..config import settings

    # O QuickChart recebe os dados do gráfico: só com a pessoa tendo ligado.
    if getattr(settings, "SENTURY_QUICKCHART", False):
        try:
            return await quickchart.get_chart_png(quickchart_config)
        except Exception as exc:
            logger.warning("QuickChart indisponivel, gerando grafico localmente: %s", exc)
    return _render_local(tool, montar_figura_local)


def _render_local(tool: str, montar_figura: Callable[[], Tuple[Any, Any]]) -> bytes:
    fig, ax = montar_figura()
    titulo_limpo = tool.replace("_", " ").title()
    ax.set_title(titulo_limpo, fontsize=12, fontweight="bold", color="#1E293B", pad=15)
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=120)
    plt.close(fig)
    return buffer.getvalue()


# Cor SEMÂNTICA por rótulo: sentimento tem significado fixo, positivo = verde,
# indiferente = amarelo, negativo = vermelho. As categorias próprias de um setor
# (em CX: leal, neutro, detrator) vêm do pacote em `cores_de_rotulo`. Aplicado
# quando os rótulos batem; senão usa a paleta padrão.
_COR_DO_PAPEL = {
    "positivo": "rgba(34, 197, 94, 0.92)",   # verde
    "neutro": "rgba(234, 179, 8, 0.92)",     # amarelo
    "negativo": "rgba(239, 68, 68, 0.92)",   # vermelho
}
_TERMOS_GENERICOS = {
    "positivo": ("satisfeito", "feliz", "positivo"),
    "neutro": ("indiferente",),
    "negativo": ("insatisf", "negativo", "critico"),
}


def _cores_semanticas() -> List[tuple]:
    try:
        from ..domains.do_setor import cores_de_rotulo

        do_setor = cores_de_rotulo()
    except Exception:
        do_setor = {}
    return [
        (tuple(_TERMOS_GENERICOS[papel]) + tuple(do_setor.get(papel, ())), cor)
        for papel, cor in _COR_DO_PAPEL.items()
    ]


def _semantic_colors_for(rotulos: List[str]):
    """Devolve cores semânticas (verde/amarelo/vermelho) se TODOS os rótulos casarem
    com sentimento (ou com as categorias do setor); senão None (paleta padrão)."""
    tabela = _cores_semanticas()
    out = []
    for r in rotulos:
        low = str(r).lower()
        cor = next((c for toks, c in tabela if any(t in low for t in toks)), None)
        if cor is None:
            return None
        out.append(cor)
    return out


def _chart_js_config(
    title: str,
    rotulos: List[str],
    valores: List[float],
    chart_type: str,
    index_axis: str = "x",
) -> Dict[str, Any]:
    doughnut_colors = _semantic_colors_for(rotulos) or [
        "rgba(99, 102, 241, 0.92)",
        "rgba(20, 184, 166, 0.92)",
        "rgba(245, 158, 11, 0.92)",
        "rgba(239, 68, 68, 0.92)",
        "rgba(168, 85, 247, 0.92)",
        "rgba(14, 165, 233, 0.92)",
    ]
    semantic = _semantic_colors_for(rotulos)

    if chart_type == "doughnut":
        dataset = {
            "label": title,
            "data": valores,
            "backgroundColor": doughnut_colors[: len(valores)],
            "borderColor": "#ffffff",
            "borderWidth": 2,
        }
    elif semantic:
        # Barras de sentimento: cada barra na sua cor semântica.
        dataset = {
            "label": title,
            "data": valores,
            "backgroundColor": semantic,
            "borderColor": semantic,
            "borderWidth": 1,
        }
    else:
        dataset = {
            "label": title,
            "data": valores,
            "backgroundColor": "rgba(99, 102, 241, 0.2)" if chart_type == "line" else "rgba(99, 102, 241, 0.85)",
            "borderColor": "rgba(99, 102, 241, 1)",
            "borderWidth": 2,
            "fill": chart_type == "line",
            "tension": 0.3 if chart_type == "line" else 0,
        }

    return {
        "type": chart_type,
        "data": {"labels": rotulos, "datasets": [dataset]},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "indexAxis": index_axis,
            "plugins": {
                "title": {"display": True, "text": title},
                "legend": {"display": chart_type == "doughnut"},
            },
        },
    }


def _chart_js_scatter(x: List[float], y: List[float]) -> Dict[str, Any]:
    return {
        "type": "scatter",
        "data": {
            "datasets": [{
                "label": "Correlacao",
                "data": [{"x": xi, "y": yi} for xi, yi in zip(x, y)],
                "backgroundColor": "rgba(99, 102, 241, 0.8)",
                "borderColor": "rgba(99, 102, 241, 1)",
                "pointRadius": 6,
            }]
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {"title": {"display": True, "text": "Grafico de Correlacao"}},
            "scales": {
                "x": {"title": {"display": True, "text": "Metrica A"}},
                "y": {"title": {"display": True, "text": "Metrica B"}},
            },
        },
    }


def _figura_padrao(rotulos: List[str], valores: List[float], chart_type: str, index_axis: str = "x"):
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor="white")
    ax.set_facecolor("white")

    color_primary = "#6366F1"
    color_accent = "#14B8A6"
    color_text = "#1E293B"
    color_grid = "#F1F5F9"

    if chart_type == "line":
        ax.plot(
            rotulos,
            valores,
            marker="o",
            color=color_primary,
            linewidth=2.5,
            markersize=6,
            markerfacecolor=color_accent,
            markeredgecolor=color_accent,
        )
    elif chart_type == "doughnut":
        _sem = _semantic_colors_for(rotulos)
        _hex = [c.replace("rgba(34, 197, 94, 0.92)", "#22C55E").replace("rgba(234, 179, 8, 0.92)", "#EAB308").replace("rgba(239, 68, 68, 0.92)", "#EF4444") for c in _sem] if _sem else None
        ax.pie(
            valores,
            labels=rotulos,
            startangle=90,
            wedgeprops={"width": 0.42, "edgecolor": "white"},
            colors=_hex or ["#6366F1", "#14B8A6", "#F59E0B", "#EF4444", "#A855F7", "#0EA5E9"][: len(valores)],
        )
        ax.axis("equal")
        return fig, ax
    else:
        _sem = _semantic_colors_for(rotulos)
        _bar_hex = ["#22C55E" if "197, 94" in c else "#EAB308" if "179, 8" in c else "#EF4444" for c in _sem] if _sem else None
        _cor = _bar_hex if _bar_hex else color_primary
        if index_axis == "y":
            ax.barh(rotulos, valores, color=_cor, edgecolor=_cor, alpha=0.9, height=0.6)
        else:
            ax.bar(rotulos, valores, color=_cor, edgecolor=_cor, alpha=0.9, width=0.6)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CBD5E1")
    ax.spines["bottom"].set_color("#CBD5E1")

    ax.grid(axis="y", linestyle="--", alpha=0.7, color=color_grid)
    ax.tick_params(axis="both", colors=color_text, labelsize=9)
    ax.tick_params(axis="x", rotation=45)

    return fig, ax


_MEDIDAS_DO_PONTO = ("metric_a_valor", "metric_b_valor")


def _pontos_correlate(tabela: List[Dict[str, Any]]) -> Tuple[List[str], List[float], List[float]]:
    # O rotulo e o que identifica o ponto (o recorte e o periodo do setor), na ordem em que veio.
    rotulos = ["/".join(str(v) for k, v in p.items() if k not in _MEDIDAS_DO_PONTO and v not in (None, ""))
               for p in tabela]
    x = [float(p["metric_a_valor"]) for p in tabela]
    y = [float(p["metric_b_valor"]) for p in tabela]
    return rotulos, x, y


def _figura_correlate(rotulos: List[str], x: List[float], y: List[float]):
    fig, ax = plt.subplots(figsize=(7, 5), facecolor="white")
    ax.set_facecolor("white")

    color_primary = "#6366F1"
    color_text = "#1E293B"
    color_grid = "#F1F5F9"

    ax.scatter(x, y, color=color_primary, alpha=0.8, s=80, edgecolors="white", linewidth=1.5)
    for rotulo, xi, yi in zip(rotulos, x, y):
        ax.annotate(rotulo, (xi, yi), fontsize=8, color="#475569", xytext=(5, 5), textcoords="offset points")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CBD5E1")
    ax.spines["bottom"].set_color("#CBD5E1")

    ax.grid(True, linestyle="--", alpha=0.7, color=color_grid)
    ax.tick_params(axis="both", colors=color_text, labelsize=9)
    ax.set_xlabel("Metrica A", fontsize=10, fontweight="bold", color=color_text)
    ax.set_ylabel("Metrica B", fontsize=10, fontweight="bold", color=color_text)
    return fig, ax


def generate_chart_data(tool: str, result: Any, tipo: Optional[str] = None) -> Dict[str, Any]:
    tabela, _ = tabela_e_resumo(tool, result)
    if not tabela:
        return {}

    if tool == "correlate":
        rotulos, x, y = _pontos_correlate(tabela)
        return {
            "type": "scatter",
            "data": {
                "datasets": [{
                    "label": "Correlacao",
                    "data": [{"x": xi, "y": yi, "label": rotulo} for xi, yi, rotulo in zip(x, y, rotulos)],
                    "backgroundColor": "rgba(99, 102, 241, 0.6)",
                    "borderColor": "rgba(99, 102, 241, 1)",
                    "pointRadius": 6,
                    "pointHoverRadius": 8,
                }]
            },
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "plugins": {"title": {"display": True, "text": "Grafico de Correlacao"}},
                "scales": {
                    "x": {"title": {"display": True, "text": "Metrica A"}},
                    "y": {"title": {"display": True, "text": "Metrica B"}},
                },
            },
        }

    visual = plan_visualization(tool=tool, table=tabela, tipo=tipo)
    chart_type = visual["chart_type"]
    dataset: Dict[str, Any] = {
        "label": visual["y_key"].upper() if visual["y_key"] else tool,
        "data": visual["values"],
        "backgroundColor": "rgba(99, 102, 241, 0.5)" if chart_type == "bar" else "rgba(99, 102, 241, 0.1)",
        "borderColor": "rgba(99, 102, 241, 1)",
        "borderWidth": 2,
        "fill": chart_type == "line",
        "tension": 0.3 if chart_type == "line" else 0,
    }
    semantic = _semantic_colors_for(visual["display_labels"])
    if chart_type == "doughnut":
        dataset["backgroundColor"] = (semantic or [
            "rgba(99, 102, 241, 0.92)",
            "rgba(20, 184, 166, 0.92)",
            "rgba(245, 158, 11, 0.92)",
            "rgba(239, 68, 68, 0.92)",
        ])[: len(visual["values"])]
        dataset["borderColor"] = "#ffffff"
    elif chart_type == "bar" and semantic:
        # Barras de sentimento → verde/amarelo/vermelho.
        dataset["backgroundColor"] = semantic
        dataset["borderColor"] = semantic

    options: Dict[str, Any] = {
        "responsive": True,
        "maintainAspectRatio": False,
        "indexAxis": visual["index_axis"],
        "plugins": {"title": {"display": True, "text": f"Analise: {tool}"}},
    }
    # Linha com dados negativos (ex.: NPS): o eixo deve CABER nos dados, não forçar
    # o zero no topo: senão a série fica espremida embaixo e parece "de cabeça
    # pra baixo". beginAtZero:false deixa o Chart.js ajustar ao intervalo real.
    if chart_type == "line":
        options["scales"] = {"y": {"beginAtZero": False}}

    return {
        "type": chart_type,
        "data": {"labels": visual["display_labels"], "datasets": [dataset]},
        "options": options,
        "meta": {
            "full_labels": visual["full_labels"],
            "aggregation_applied": visual["aggregation_applied"],
            "label_truncation_applied": visual["label_truncation_applied"],
            "reason": visual["reason"],
        },
    }
