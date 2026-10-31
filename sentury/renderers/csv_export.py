"""Exporta um resultado de análise para CSV: usa a tabela quando disponível,
senão cai para os campos-resumo como uma tabela campo/valor."""
import io
from typing import Any

import pandas as pd

from .shape import tabela_e_resumo


def export_csv(tool: str, result: Any) -> bytes:
    tabela, resumo = tabela_e_resumo(tool, result)

    if tabela:
        df = pd.DataFrame(tabela)
    else:
        resumo_escalar = {k: v for k, v in resumo.items() if not isinstance(v, (dict, list))}
        df = pd.DataFrame(list(resumo_escalar.items()), columns=["campo", "valor"])

    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def export_csv_multi(sources: list[dict[str, Any]]) -> bytes:
    frames = []
    for item in sources:
        tool = str(item.get("tool") or "fonte")
        result = item.get("result")
        tabela, resumo = tabela_e_resumo(tool, result)
        if tabela:
            df = pd.DataFrame(tabela)
        else:
            resumo_escalar = {
                k: v for k, v in resumo.items()
                if not isinstance(v, (dict, list)) and v is not None and k != "markdown"
            }
            df = pd.DataFrame(list(resumo_escalar.items()), columns=["campo", "valor"])
        if df.empty:
            df = pd.DataFrame([{"status": "sem dados exportaveis"}])
        df.insert(0, "fonte", tool)
        frames.append(df)

    merged = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    buffer = io.StringIO()
    merged.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")
