from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


def _colunas_da_ferramenta() -> Dict[str, Tuple[str, str]]:
    """Consulta no setor ativo as colunas de gráfico de cada ferramenta."""
    try:
        from ..domains.do_setor import colunas_de_grafico

        return colunas_de_grafico()
    except Exception:
        return {}


def _forma_da_ferramenta(tool: str) -> str:
    """A forma que o setor ativo prefere para a saída da ferramenta, ou vazio."""
    try:
        from ..domains.do_setor import formas_de_grafico

        return formas_de_grafico().get(tool, "")
    except Exception:
        return ""


_MAX_CATEGORY_POINTS = 8
_MAX_LABEL_LENGTH = 28


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def _looks_like_time_label(value: str) -> bool:
    value = _normalize(str(value or ""))
    if re.match(r"^\d{4}-\d{2}$", value):
        return True
    if re.match(r"^\d{4}/\d{2}$", value):
        return True
    return value in {
        "jan", "fev", "mar", "abr", "mai", "jun",
        "jul", "ago", "set", "out", "nov", "dez",
        "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    }


def _pick_columns(tool: str, table: List[Dict[str, Any]]) -> Tuple[str, str]:
    if table:
        preferred = _colunas_da_ferramenta().get(tool)
        if preferred and preferred[0] in table[0] and preferred[1] in table[0]:
            return preferred

        first = table[0]
        x_key = next(iter(first.keys()))
        y_key = next((key for key, value in first.items() if key != x_key and _is_number(value)), x_key)
        return x_key, y_key

    preferred = _colunas_da_ferramenta().get(tool)
    if preferred:
        return preferred
    return "categoria", "valor"


def _aggregate_tail(labels: List[str], values: List[float], max_points: int = _MAX_CATEGORY_POINTS) -> Tuple[List[str], List[float], bool]:
    if len(labels) <= max_points:
        return labels, values, False

    ranked = sorted(zip(labels, values), key=lambda item: abs(item[1]), reverse=True)
    kept = ranked[: max_points - 1]
    remainder = ranked[max_points - 1 :]
    kept.append(("Outros", sum(value for _, value in remainder)))
    return [label for label, _ in kept], [value for _, value in kept], True


def _display_labels(labels: List[str], max_length: int = _MAX_LABEL_LENGTH) -> Tuple[List[str], bool]:
    display: List[str] = []
    truncated = False

    for label in labels:
        if len(label) > max_length:
            display.append(f"{label[: max_length - 3].rstrip()}...")
            truncated = True
        else:
            display.append(label)

    return display, truncated


def plan_visualization(
    tool: str,
    table: List[Dict[str, Any]],
    tipo: Optional[str] = None,
) -> Dict[str, Any]:
    x_key, y_key = _pick_columns(tool, table)
    labels = [str(row.get(x_key, "")) for row in table if _is_number(row.get(y_key))]
    values = [float(row.get(y_key)) for row in table if _is_number(row.get(y_key))]

    if tool == "correlate":
        display_labels, label_truncation_applied = _display_labels(labels)
        return {
            "chart_type": "scatter",
            "index_axis": "x",
            "x_key": "metric_a_valor",
            "y_key": "metric_b_valor",
            "labels": labels,
            "display_labels": display_labels,
            "full_labels": labels,
            "values": values,
            "is_percentage": False,
            "aggregation_applied": False,
            "label_truncation_applied": label_truncation_applied,
            "reason": "correlation_scatter",
            "title": "Grafico de Correlacao",
        }

    is_percentage = (
        y_key.endswith("pct")
        or y_key.startswith("pct")
        or "percent" in y_key
        or (2 <= len(values) <= 6 and values and abs(sum(values) - 100.0) <= 5.0)
    )
    has_time_axis = bool(labels) and all(_looks_like_time_label(label) for label in labels)
    long_labels = bool(labels) and max(len(label) for label in labels) >= 24
    # Partes de um todo: poucas categorias que somam perto de 100.
    partes_de_um_todo = 2 <= len(values) <= 6 and abs(sum(values) - 100.0) <= 5.0

    chart_type = "bar"
    index_axis = "x"
    reason = "default_bar"
    forma = _forma_da_ferramenta(tool)

    if tipo in {"doughnut", "pizza", "rosca"}:
        chart_type = "doughnut"
        reason = "explicit_doughnut"
    elif tipo == "linha" or has_time_axis or forma == "linha":
        chart_type = "line"
        reason = "time_series"
    elif is_percentage and 2 <= len(values) <= 6 and (partes_de_um_todo or forma == "rosca"):
        chart_type = "doughnut"
        reason = "small_percentage_distribution"
    elif long_labels or forma == "barra_horizontal":
        chart_type = "bar"
        index_axis = "y"
        reason = "long_labels_horizontal_bar"

    # Pizza e rosca exigem valores não negativos com soma positiva.
    # Para outros dados, séries temporais viram linha; demais casos, barras.
    if chart_type == "doughnut" and (not values or any(v < 0 for v in values) or sum(values) <= 0):
        if has_time_axis or forma == "linha":
            chart_type = "line"
            reason = "serie_temporal_negativa_para_linha"
        else:
            chart_type = "bar"
            index_axis = "x"
            reason = "doughnut_degradado_para_barras_valores_nao_positivos"

    aggregation_applied = False
    if chart_type == "bar" and not has_time_axis:
        labels, values, aggregation_applied = _aggregate_tail(labels, values)
        if aggregation_applied and reason == "default_bar":
            reason = "ranked_bar_with_others"

    display_labels, label_truncation_applied = _display_labels(labels)

    return {
        "chart_type": chart_type,
        "index_axis": index_axis,
        "x_key": x_key,
        "y_key": y_key,
        "labels": labels,
        "display_labels": display_labels,
        "full_labels": labels,
        "values": values,
        "is_percentage": is_percentage,
        "aggregation_applied": aggregation_applied,
        "label_truncation_applied": label_truncation_applied,
        "reason": reason,
        "title": tool.replace("_", " ").title(),
    }
