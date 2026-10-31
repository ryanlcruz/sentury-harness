from __future__ import annotations

from html import escape
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .chart import generate_chart_data
from .shape import tabela_e_resumo

def _titulo_da_ferramenta(tool: str) -> str:
    """Titulo do painel: o do setor ativo, com o nome da ferramenta de reserva.

    Mora no setor para o generalista nao carregar titulos de um setor que ele
    nao tem, e para um setor novo poder nomear os paineis dele.
    """
    try:
        from ..domains.do_setor import titulos_de_painel

        do_setor = titulos_de_painel()
    except Exception:
        do_setor = {}
    return do_setor.get(tool) or str(tool).replace("_", " ").title()


def _recortes_a_pular() -> set:
    """Chaves que sao RECORTE, nao numero: nao entram no resumo do painel.

    Eram seis nomes fixos (`regiao`, `filial`, `unidade_negocio`) que sao
    dimensoes de um setor. As do setor ativo vem do pacote; o periodo e do
    motor e fica aqui.
    """
    base = {"periodo_inicio", "periodo_fim", "categoria"}
    try:
        from ..domains.do_setor import dimensoes

        return base | set(dimensoes().keys())
    except Exception:
        return base


def export_html_dashboard(
    tool: str,
    result: Any,
    *,
    presentation_style: str = "dashboard",
    request: str = "",
) -> bytes:
    table, summary = tabela_e_resumo(tool, result)
    chart_data = generate_chart_data(tool, result)
    title = _titulo_da_ferramenta(tool)
    cards = _collect_cards(summary)
    table_columns, table_rows = _normalize_table(table)
    presentation_style = _select_presentation_style(presentation_style, tool)
    artifact_copy = _presentation_copy(presentation_style, title)

    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Sentury</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f3ea;
      --panel: #fffdf8;
      --ink: #111111;
      --muted: #665f54;
      --line: #d9cfbd;
      --accent: #f2c300;
      --accent-deep: #8a6a00;
      --shadow: 0 18px 40px rgba(17, 17, 17, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      background:
        radial-gradient(1100px 460px at 82% -8%, rgba(242, 195, 0, 0.12), transparent 60%),
        radial-gradient(900px 500px at -6% 6%, rgba(138, 106, 0, 0.06), transparent 55%),
        var(--bg);
      color: var(--ink);
      -webkit-font-smoothing: antialiased;
    }}
    .shell {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 32px 24px 40px;
    }}
    .hero {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-end;
      margin-bottom: 24px;
    }}
    .eyebrow {{
      margin: 0 0 8px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--accent-deep);
    }}
    h1 {{
      margin: 0;
      font-size: 34px;
      line-height: 1.05;
    }}
    .subtitle {{
      margin: 10px 0 0;
      max-width: 720px;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.5;
    }}
    .stamp {{
      min-width: 220px;
      padding: 16px 18px;
      border: 1px solid var(--line);
      border-left: 4px solid var(--accent);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.72);
      box-shadow: var(--shadow);
    }}
    .stamp strong {{
      display: block;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--accent-deep);
      margin-bottom: 6px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }}
    .card {{
      min-height: 118px;
      padding: 18px;
      border: 1px solid var(--line);
      border-top: 4px solid var(--accent);
      border-radius: 16px;
      background: linear-gradient(180deg, #fffef9 0%, var(--panel) 100%);
      box-shadow: var(--shadow);
      transition: transform 0.18s ease, box-shadow 0.18s ease;
    }}
    .card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 22px 46px rgba(17, 17, 17, 0.12);
    }}
    .card-label {{
      margin: 0 0 10px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .card-value {{
      margin: 0;
      font-size: 30px;
      line-height: 1.1;
      font-weight: 800;
      color: var(--ink);
      word-break: break-word;
      font-variant-numeric: tabular-nums;
      letter-spacing: -0.01em;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
      gap: 18px;
      align-items: start;
    }}
    .panel {{
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }}
    .panel h2 {{
      margin: 0 0 14px;
      font-size: 17px;
    }}
    .chart-wrap {{
      position: relative;
      min-height: 320px;
    }}
    .chart-wrap svg {{
      display: block;
      width: 100%;
      height: auto;
      min-height: 280px;
    }}
    .table-wrap {{
      overflow: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      padding: 11px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #f3ecdb;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--accent-deep);
    }}
    tbody tr:nth-child(even) td {{
      background: rgba(242, 195, 0, 0.06);
    }}
    .empty {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}
    .meta {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
    }}
    @media (max-width: 960px) {{
      .grid {{
        grid-template-columns: 1fr;
      }}
      .shell {{
        padding: 20px 16px 28px;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero hero--{presentation_style}">
      <div>
        <p class="eyebrow">Sentury</p>
        <h1>{escape(artifact_copy['title'])}</h1>
        <p class="subtitle">{escape(artifact_copy['subtitle'])}</p>
      </div>
      <aside class="stamp">
        <strong>{escape(artifact_copy['stamp_title'])}</strong>
        <span>{escape(artifact_copy['stamp_text'])}</span>
      </aside>
    </section>
    {_render_cards(cards)}
    <section class="grid grid--{presentation_style}">
      <article class="panel">
        <h2>{escape(artifact_copy['visual_title'])}</h2>
        {_render_chart(chart_data)}
      </article>
      <article class="panel">
        <h2>{escape(artifact_copy['table_title'])}</h2>
        {_render_table(table_columns, table_rows)}
      </article>
    </section>
  </div>
</body>
</html>"""
    return html.encode("utf-8")


def export_html_multi_dashboard(
    items: List[Dict[str, Any]],
    *,
    presentation_style: str = "dashboard",
    request: str = "",
) -> bytes:
    """Renderiza um HTML deterministico que cruza varias analises da sessao.

    Este caminho existe para pedidos como "cruze NPS, taxa de resposta e
    comentarios": a entrega precisa contar uma historia unica, nao apenas mostrar
    o ultimo resultado gerado.
    """
    sections = _normalize_multi_sections(items)
    if not sections:
        return export_html_dashboard("resultado", {}, presentation_style=presentation_style, request=request)
    if len(sections) == 1:
        section = sections[0]
        return export_html_dashboard(
            section["tool"],
            section["result"],
            presentation_style=presentation_style,
            request=request,
        )

    title = _multi_title(request, sections)
    subtitle = _multi_subtitle(request, sections)
    cards = _collect_multi_cards(sections)
    insight_html = _render_cross_reading(sections)
    section_html = "".join(_render_multi_section(section) for section in sections)

    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Sentury</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f3ea;
      --panel: #fffdf8;
      --ink: #111111;
      --muted: #665f54;
      --line: #d9cfbd;
      --soft: #f1eadb;
      --accent: #f2c300;
      --accent-deep: #7a5d00;
      --risk: #c43d34;
      --ok: #2f7f55;
      --shadow: 0 18px 42px rgba(17, 17, 17, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      background:
        radial-gradient(900px 420px at 86% -10%, rgba(242, 195, 0, 0.14), transparent 62%),
        linear-gradient(180deg, #faf8f1 0%, var(--bg) 100%);
      color: var(--ink);
      -webkit-font-smoothing: antialiased;
    }}
    .shell {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 36px 24px 48px;
    }}
    .eyebrow {{
      margin: 0 0 10px;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--accent-deep);
    }}
    h1 {{
      margin: 0;
      font-size: clamp(30px, 5vw, 54px);
      line-height: 0.98;
      letter-spacing: 0;
    }}
    .subtitle {{
      margin: 16px 0 0;
      max-width: 780px;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.55;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
      gap: 24px;
      align-items: end;
      margin-bottom: 24px;
    }}
    .stamp {{
      padding: 18px;
      border: 1px solid var(--line);
      border-left: 5px solid var(--accent);
      border-radius: 16px;
      background: rgba(255, 253, 248, 0.86);
      box-shadow: var(--shadow);
    }}
    .stamp strong {{
      display: block;
      margin-bottom: 8px;
      font-size: 12px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--accent-deep);
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 14px;
      margin: 24px 0;
    }}
    .card {{
      min-height: 112px;
      padding: 16px;
      border: 1px solid var(--line);
      border-top: 4px solid var(--accent);
      border-radius: 14px;
      background: linear-gradient(180deg, #fffef9 0%, var(--panel) 100%);
      box-shadow: var(--shadow);
    }}
    .card-label {{
      margin: 0 0 9px;
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .card-value {{
      margin: 0;
      font-size: 28px;
      line-height: 1.08;
      font-weight: 900;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
      word-break: break-word;
    }}
    .insight {{
      display: grid;
      grid-template-columns: minmax(0, 0.86fr) minmax(280px, 0.54fr);
      gap: 16px;
      margin: 0 0 20px;
    }}
    .panel {{
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }}
    .panel--accent {{
      border-left: 5px solid var(--accent);
    }}
    .panel h2, .panel h3 {{
      margin: 0 0 12px;
      font-size: 18px;
    }}
    .panel p, .panel li {{
      color: #34312a;
      line-height: 1.52;
    }}
    .signal-list {{
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 10px;
    }}
    .signal-list li {{
      padding: 12px 12px 12px 15px;
      border-left: 4px solid var(--accent);
      border-radius: 10px;
      background: #fff9e5;
    }}
    .sections {{
      display: grid;
      gap: 18px;
    }}
    .section-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 0.8fr);
      gap: 16px;
      align-items: start;
    }}
    .chart-wrap {{
      min-height: 300px;
    }}
    .chart-wrap svg {{
      display: block;
      width: 100%;
      height: auto;
      min-height: 280px;
    }}
    .table-wrap {{
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 12px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      background: #fffdf8;
    }}
    th, td {{
      padding: 10px 11px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #f3ecdb;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--accent-deep);
    }}
    tbody tr:nth-child(even) td {{
      background: rgba(242, 195, 0, 0.06);
    }}
    .comment {{
      margin: 0 0 10px;
      padding: 12px 14px;
      border-left: 4px solid var(--risk);
      border-radius: 10px;
      background: #fff6f2;
      color: #3d332d;
    }}
    .empty, .meta {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    .meta {{
      margin-top: 12px;
    }}
    @media (max-width: 940px) {{
      .shell {{ padding: 22px 14px 32px; }}
      .hero, .insight, .section-grid {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 34px; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div>
        <p class="eyebrow">Sentury</p>
        <h1>{escape(title)}</h1>
        <p class="subtitle">{escape(subtitle)}</p>
      </div>
      <aside class="stamp">
        <strong>Entrega cruzada</strong>
        <span>{escape(str(len(sections)))} fontes analiticas consolidadas em uma leitura visual unica.</span>
      </aside>
    </section>
    {_render_cards(cards)}
    {insight_html}
    <section class="sections">{section_html}</section>
  </main>
</body>
</html>"""
    return html.encode("utf-8")


def _normalize_multi_sections(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    seen = set()
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").strip()
        result = item.get("result")
        if not tool or result in (None, [], {}):
            continue
        signature = (tool, str(item.get("result_id") or index))
        if signature in seen:
            continue
        seen.add(signature)
        table, summary = tabela_e_resumo(tool, result)
        chart = generate_chart_data(tool, result)
        sections.append({
            "tool": tool,
            "result": result,
            "table": table,
            "summary": summary or {},
            "chart": chart,
            "title": _section_title(tool),
        })
    return sections


def _multi_title(request: str, sections: List[Dict[str, Any]]) -> str:
    return "Leitura cruzada"


def _multi_subtitle(request: str, sections: List[Dict[str, Any]]) -> str:
    if request:
        return "Artefato montado a partir das fontes da conversa para responder: " + request.strip()
    return "Analises da sessao consolidadas em um artefato visual para decisao rapida."


def _section_title(tool: str) -> str:
    try:
        from ..domains.do_setor import titulos_de_secao

        do_setor = titulos_de_secao()
    except Exception:
        do_setor = {}
    return do_setor.get(tool) or _titulo_da_ferramenta(tool)


def _collect_multi_cards(sections: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    preferred = [
        ("analyze_nps", "volume"),
        ("analyze_nps", "nps"),
        ("analyze_nps", "pct_em_risco"),
        ("analyze_survey_completion", "taxa_conclusao"),
        ("analyze_survey_completion", "abandonados"),
        ("analyze_sentiment", "volume"),
    ]
    cards: List[Tuple[str, str]] = []
    by_tool = {section["tool"]: section for section in sections}
    for tool, key in preferred:
        section = by_tool.get(tool)
        if not section:
            continue
        value = section["summary"].get(key)
        if value is None:
            continue
        cards.append((_multi_card_label(tool, key), _format_value(key, value)))
    if len(cards) < 6:
        for section in sections:
            for label, value in _collect_cards(section["summary"]):
                if len(cards) >= 6:
                    break
                item = (label, value)
                if item not in cards:
                    cards.append(item)
            if len(cards) >= 6:
                break
    return cards[:6]


def _multi_card_label(tool: str, key: str) -> str:
    if tool == "analyze_survey_completion" and key == "taxa_conclusao":
        return "Conclusao"
    if tool == "analyze_survey_completion" and key == "abandonados":
        return "Abandono"
    if tool == "analyze_sentiment" and key == "volume":
        return "Comentarios"
    return _labelize(key)


def _render_cross_reading(sections: List[Dict[str, Any]]) -> str:
    signals = _cross_signals(sections)
    comments = _negative_comments(sections)
    signal_items = "".join(f"<li>{escape(signal)}</li>" for signal in signals)
    comment_items = "".join(f"<p class=\"comment\">{escape(comment)}</p>" for comment in comments[:3])
    if not comment_items:
        comment_items = "<p class=\"empty\">Sem comentarios textuais destacados nesta leitura.</p>"
    return (
        "<section class=\"insight\">"
        "<article class=\"panel panel--accent\">"
        "<h2>Leitura cruzada</h2>"
        f"<ul class=\"signal-list\">{signal_items}</ul>"
        "</article>"
        "<article class=\"panel\">"
        "<h2>Voz do cliente</h2>"
        f"{comment_items}"
        "</article>"
        "</section>"
    )


def _cross_signals(sections: List[Dict[str, Any]]) -> List[str]:
    by_tool = {section["tool"]: section for section in sections}
    signals: List[str] = []
    nps = by_tool.get("analyze_nps", {}).get("summary", {})
    completion = by_tool.get("analyze_survey_completion", {}).get("summary", {})
    sentiment = by_tool.get("analyze_sentiment", {}).get("summary", {})
    root = by_tool.get("root_cause")

    if nps:
        signals.append(
            "NPS consolidado em "
            + _format_value("nps", nps.get("nps"))
            + ", com "
            + _format_value("pct_em_risco", nps.get("pct_em_risco"))
            + " dos clientes em risco."
        )
    if completion:
        signals.append(
            "A pesquisa converte "
            + _format_value("taxa_conclusao", completion.get("taxa_conclusao"))
            + "; o maior ponto de abandono aparece em "
            + str(completion.get("bloco_mais_critico") or "bloco nao informado")
            + "."
        )
    sentiment_section = by_tool.get("analyze_sentiment")
    sentiment_result = sentiment_section.get("result") if sentiment_section else None
    dist = sentiment_result.get("distribuicao_sentimento") if isinstance(sentiment_result, dict) else None
    if isinstance(dist, dict) and dist:
        negativo = dist.get("Negativo") or dist.get("negativo")
        if negativo is not None:
            signals.append(
                "Comentarios negativos representam "
                + _format_value("pct_negativo", negativo)
                + " da voz aberta analisada."
            )
    if root:
        rows = root.get("table") or []
        if rows:
            worst = _row_with_min(rows, "nps") or rows[0]
            region = worst.get("regiao") or "regiao critica"
            cause = worst.get("causa") or worst.get("problema") or "causa operacional nao detalhada"
            signals.append(f"Maior alavanca: {region} aparece como foco critico; causa: {cause}.")
    if not signals:
        signals.append("As fontes da conversa foram consolidadas em uma leitura unica para evitar respostas soltas.")
    return signals[:5]


def _negative_comments(sections: List[Dict[str, Any]]) -> List[str]:
    for section in sections:
        if section["tool"] != "analyze_sentiment":
            continue
        result = section.get("result")
        examples = result.get("exemplos_comentarios") if isinstance(result, dict) else None
        if isinstance(examples, dict):
            comments = examples.get("Negativo") or examples.get("negativo") or []
            return [str(item) for item in comments if str(item).strip()]
    return []


def _row_with_min(rows: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    best = None
    best_value = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            value = row.get(key)
            if hasattr(value, "item"):
                value = value.item()
            value = float(value)
        except (TypeError, ValueError):
            continue
        if best_value is None or value < best_value:
            best = row
            best_value = value
    return best


def _render_multi_section(section: Dict[str, Any]) -> str:
    columns, rows = _normalize_table(section["table"])
    chart_html = _render_chart(section["chart"])
    table_html = _render_table(columns, rows)
    return (
        "<article class=\"panel\">"
        f"<h2>{escape(section['title'])}</h2>"
        "<div class=\"section-grid\">"
        f"<div>{chart_html}</div>"
        f"<div>{table_html}</div>"
        "</div>"
        "</article>"
    )


def _select_presentation_style(style: str, tool: str) -> str:
    """O estilo vem do parâmetro que o modelo escolheu; o pedido não é lido."""
    escolhido = str(style or "").strip().lower()
    if escolhido in {"dashboard", "report", "timeline"}:
        return escolhido
    return "brief"


def _presentation_copy(style: str, title: str) -> Dict[str, str]:
    if style == "report":
        return {
            "title": title.replace("Painel", "Relatório"),
            "subtitle": "Relatório analítico montado a partir do resultado atual da conversa, pronto para leitura e compartilhamento.",
            "stamp_title": "Leitura executiva",
            "stamp_text": "Indicadores, visualização e tabela em um documento compacto.",
            "visual_title": "Evolução e distribuição",
            "table_title": "Dados de apoio",
        }
    if style == "timeline":
        return {
            "title": title.replace("Painel", "Linha do tempo"),
            "subtitle": "Sequência analítica organizada para acompanhar a evolução do indicador e seus pontos de atenção.",
            "stamp_title": "Visão temporal",
            "stamp_text": "Leitura rápida do comportamento do indicador no período.",
            "visual_title": "Linha do tempo",
            "table_title": "Marcos do período",
        }
    if style == "brief":
        subject = title.replace("Painel de ", "", 1).replace("Painel por ", "", 1)
        return {
            "title": f"Leitura de {subject}",
            "subtitle": "Resumo visual focado no que este resultado revela, sem transformar toda análise em um dashboard genérico.",
            "stamp_title": "Insight operacional",
            "stamp_text": "Uma entrega compacta para entender o sinal e decidir o próximo passo.",
            "visual_title": "O sinal nos dados",
            "table_title": "Base da leitura",
        }
    return {
        "title": title,
        "subtitle": "Painel gerado a partir do último resultado analítico da conversa. Ele combina indicadores, visualização e tabela operacional em um artefato único.",
        "stamp_title": "Entrega analítica",
        "stamp_text": "Mini dashboard pronto para leitura rápida, follow-ups e exportação.",
        "visual_title": "Visualização",
        "table_title": "Tabela de apoio",
    }


def _collect_cards(summary: Dict[str, Any]) -> List[Tuple[str, str]]:
    cards: List[Tuple[str, str]] = []
    for key, value in (summary or {}).items():
        if key in _recortes_a_pular() or value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)):
            if not value:
                continue
            continue
        cards.append((_labelize(key), _format_value(key, value)))
    return cards[:6]


def _normalize_table(table: List[Dict[str, Any]]) -> Tuple[List[str], List[List[str]]]:
    if not table:
        return [], []
    columns = list(table[0].keys())
    rows: List[List[str]] = []
    for row in table[:12]:
        rows.append([_format_value(column, row.get(column)) for column in columns])
    return columns, rows


def _labelize(key: str) -> str:
    """Rotulo de uma coluna: o do setor, ou a chave legivel."""
    try:
        from ..domains.do_setor import rotulos_de_coluna

        do_setor = rotulos_de_coluna()
    except Exception:
        do_setor = {}
    return do_setor.get(key) or key.replace("_", " ").strip().title()


def _format_value(key: str, value: Any) -> str:
    if value is None:
        return "-"
    if hasattr(value, "item") and callable(getattr(value, "item", None)):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, bool):
        return "Sim" if value else "Nao"
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        if any(token in key for token in ("pct", "taxa")):
            return f"{value:.1f}%".replace(".", ",")
        return f"{value:.1f}".replace(".", ",")
    return str(value)


def _render_cards(cards: Iterable[Tuple[str, str]]) -> str:
    cards = list(cards)
    if not cards:
        return ""
    items = []
    for label, value in cards:
        items.append(
            "<article class=\"card\">"
            f"<p class=\"card-label\">{escape(label)}</p>"
            f"<p class=\"card-value\">{escape(value)}</p>"
            "</article>"
        )
    return f"<section class=\"cards\">{''.join(items)}</section>"


def _render_chart(chart_payload: Dict[str, Any]) -> str:
    if not chart_payload:
        return "<p class=\"empty\">Este resultado nao trouxe uma serie adequada para grafico, entao o painel ficou focado nos indicadores e na tabela.</p>"
    return (
        "<div class=\"chart-wrap\">"
        f"{_render_chart_svg(chart_payload)}"
        "<p class=\"meta\">Grafico selecionado automaticamente pela camada de visualizacao do Sentury.</p>"
        "</div>"
    )


def _render_chart_svg(payload: Dict[str, Any]) -> str:
    """Renderiza um gráfico SVG estático para que o HTML funcione igualmente em
    preview sandbox, painel lateral e nova aba, sem CDN ou JavaScript."""
    data = payload.get("data") or {}
    datasets = data.get("datasets") or []
    dataset = datasets[0] if datasets else {}
    chart_type = str(payload.get("type") or "bar").lower()
    labels = [str(value) for value in (data.get("labels") or [])]
    raw_values = dataset.get("data") or []
    values = []
    for value in raw_values:
        if isinstance(value, dict):
            value = value.get("y")
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue

    if not values:
        return "<p class=\"empty\">Não há pontos numéricos suficientes para desenhar este gráfico.</p>"

    if len(labels) != len(values):
        labels = labels[:len(values)] or [str(index + 1) for index in range(len(values))]

    width, height = 760, 330
    left, right, top, bottom = 62, 28, 36, 62
    plot_w, plot_h = width - left - right, height - top - bottom
    title = str(((payload.get("options") or {}).get("plugins") or {}).get("title", {}).get("text") or dataset.get("label") or "Indicador")
    grid = []
    elements = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" xmlns="http://www.w3.org/2000/svg">',
        '<rect width="100%" height="100%" rx="12" fill="#fffdf8"/>',
        f'<text x="{left}" y="22" font-size="14" font-weight="700" fill="#191714">{escape(title)}</text>',
    ]

    if chart_type == "line":
        minimum, maximum = min(values), max(values)
        padding = max((maximum - minimum) * 0.12, 1)
        minimum -= padding
        maximum += padding
        for step in range(5):
            y = top + plot_h * step / 4
            value = maximum - (maximum - minimum) * step / 4
            grid.append(f'<path d="M{left} {y:.1f}H{width - right}" stroke="#e3dccd" stroke-width="1"/>')
            grid.append(f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#6f6555">{value:.1f}</text>')
        points = []
        for index, value in enumerate(values):
            x = left + plot_w * index / max(1, len(values) - 1)
            y = top + (maximum - value) / max(1e-9, maximum - minimum) * plot_h
            points.append((x, y))
        path = " ".join((f"M{x:.1f},{y:.1f}" if index == 0 else f"L{x:.1f},{y:.1f}") for index, (x, y) in enumerate(points))
        elements.extend(grid)
        elements.append(f'<path d="{path}" fill="none" stroke="#2c5ee8" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        for index, ((x, y), label) in enumerate(zip(points, labels)):
            elements.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#f5c400" stroke="#2c5ee8" stroke-width="2"/>')
            elements.append(f'<text x="{x:.1f}" y="{height - 28}" text-anchor="middle" font-size="10" fill="#6f6555">{escape(_short_label(label))}</text>')
    else:
        maximum = max(max(values), 0)
        minimum = min(min(values), 0)
        span = max(maximum - minimum, 1)
        baseline = top + maximum / span * plot_h
        for step in range(5):
            y = top + plot_h * step / 4
            grid.append(f'<path d="M{left} {y:.1f}H{width - right}" stroke="#e3dccd" stroke-width="1"/>')
        elements.extend(grid)
        gap = max(8, plot_w / max(1, len(values)) * 0.16)
        bar_w = max(12, (plot_w - gap * (len(values) + 1)) / max(1, len(values)))
        for index, (value, label) in enumerate(zip(values, labels)):
            x = left + gap + index * (bar_w + gap)
            y_value = top + (maximum - value) / span * plot_h
            y = min(baseline, y_value)
            bar_h = max(abs(baseline - y_value), 2)
            color = "#c53b32" if value < 0 else "#2d7a54"
            elements.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="4" fill="{color}"/>')
            elements.append(f'<text x="{x + bar_w / 2:.1f}" y="{height - 28}" text-anchor="middle" font-size="10" fill="#6f6555">{escape(_short_label(label))}</text>')
            elements.append(f'<text x="{x + bar_w / 2:.1f}" y="{max(30, y - 6):.1f}" text-anchor="middle" font-size="10" font-weight="700" fill="#34312a">{value:.1f}</text>')

    elements.append("</svg>")
    return "".join(elements)


def _short_label(value: str, limit: int = 12) -> str:
    value = str(value)
    return value if len(value) <= limit else f"{value[:limit - 1]}…"


def _render_table(columns: List[str], rows: List[List[str]]) -> str:
    if not columns or not rows:
        return "<p class=\"empty\">Nao ha linhas tabulares suficientes para montar a grade deste painel.</p>"

    head = "".join(f"<th>{escape(_labelize(column))}</th>" for column in columns)
    body_rows = []
    for row in rows:
        body_rows.append("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in row) + "</tr>")

    return (
        "<div class=\"table-wrap\">"
        "<table>"
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</div>"
    )
