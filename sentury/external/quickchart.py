"""Cliente do QuickChart.io (https://quickchart.io), serviço público e sem
chave que renderiza um gráfico Chart.js no servidor e devolve um PNG. O
`renderers/chart.py` só o usa com `SENTURY_QUICKCHART` ligado, porque os dados
do gráfico saem da máquina; sem ele, o gráfico é desenhado localmente. Este
módulo levanta exceção em falha: quem chama decide o plano B."""
import json
from typing import Any, Dict
from urllib.parse import quote

import httpx

_URL = "https://quickchart.io/chart"


async def get_chart_png(config: Dict[str, Any], width: int = 800, height: int = 450) -> bytes:
    url = f"{_URL}?width={width}&height={height}&c={quote(json.dumps(config))}"
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        if not resp.content:
            raise ValueError("QuickChart devolveu corpo vazio")
        return resp.content
