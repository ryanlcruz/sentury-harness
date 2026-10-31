"""Exporta um resultado de análise para um relatório PDF, no estilo dos demais
documentos da Sentury. Resultados com campo `markdown` (planos de ação) são
renderizados FORMATADOS (títulos, listas, tabelas); os demais saem como
resumo + tabela.
Aplica estilos e formatação premium usando fpdf2."""
from typing import Any, List, Dict

from fpdf.fonts import FontFace

from .shape import tabela_e_resumo


def _desenho_do_pdf():
    """O desenho do PDF mora no script da skill `relatorio-pdf`: o agente o roda
    direto, e este export usa o mesmo, para os dois saírem iguais."""
    import importlib.util
    from pathlib import Path

    caminho = (Path(__file__).resolve().parents[1] / "skills" / "productivity" / "relatorio-pdf"
               / "scripts" / "markdown_para_pdf.py")
    spec = importlib.util.spec_from_file_location("sentury_markdown_para_pdf", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_desenho = _desenho_do_pdf()
SenturyPDF = _desenho.SenturyPDF
_latin1 = _desenho.latin1
_strip_inline = _desenho.sem_marcacao
_render_markdown = _desenho.desenhar_markdown
_render_markdown_table = _desenho.desenhar_tabela
markdown_para_pdf = _desenho.markdown_para_pdf


def export_pdf(tool: str, result: Any) -> bytes:
    # Determina o título
    titulo = tool.replace("_", " ").title()
    if isinstance(result, dict) and isinstance(result.get("markdown"), str):
        regiao = result.get("regiao")
        metodologia = result.get("metodologia")
        titulo = "Plano de Ação"
        if metodologia:
            titulo += f" — {str(metodologia).replace('_', ' ').title()}"
        if regiao:
            titulo += f" ({regiao})"
            
    pdf = SenturyPDF(titulo=titulo, orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)  # Margem inferior para não cortar a tabela
    pdf.add_page()

    # Resultado com markdown (plano de ação) -> documento formatado.
    if isinstance(result, dict) and isinstance(result.get("markdown"), str):
        _render_markdown(pdf, result["markdown"])
        return bytes(pdf.output())

    # Demais resultados: resumo (escalares) + tabela.
    tabela, resumo = tabela_e_resumo(tool, result)

    resumo_escalar = {
        k: v for k, v in resumo.items()
        if not isinstance(v, (dict, list)) and v is not None and k != "markdown"
    }
    if resumo_escalar:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(0, 7, _latin1("Resumo da Análise"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        
        # Caixa de resumo estilizada
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(51, 65, 85)
        for chave, valor in resumo_escalar.items():
            chave_limpa = chave.replace("_", " ").title()
            pdf.cell(0, 5, _latin1(f"  •  {chave_limpa}: {valor}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    if tabela:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(0, 7, _latin1("Dados Detalhados"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        
        # Renderiza tabela sem truncamento
        colunas = list(tabela[0].keys())
        largura_disponivel = pdf.w - pdf.l_margin - pdf.r_margin
        
        # Calcula larguras com pesos inteligentes
        pesos = []
        for col in colunas:
            col_lower = col.lower()
            if any(x in col_lower for x in ("comentario", "descricao", "causa_raiz", "motivo", "titulo", "observacao")):
                pesos.append(3.5)
            elif any(x in col_lower for x in ("id", "nps", "csat", "ces", "status", "prioridade", "periodo", "mes")):
                pesos.append(0.8)
            else:
                pesos.append(1.5)

        total_pesos = sum(pesos)
        larguras = [float((w / total_pesos) * largura_disponivel) for w in pesos]

        headings_style = FontFace(color=(255, 255, 255), fill_color=(30, 41, 59), emphasis="BOLD")
        with pdf.table(col_widths=larguras, borders_layout="NONE", line_height=6, cell_fill_color=(248, 250, 252), cell_fill_mode="ROWS", headings_style=headings_style) as t:
            # Cabeçalho
            row = t.row()
            for col in colunas:
                col_title = col.replace("_", " ").title()
                row.cell(_latin1(col_title))
            
            # Dados
            for linha in tabela:
                row = t.row()
                for col in colunas:
                    val = linha.get(col)
                    val_str = str(val if val is not None else "")
                    
                    # Formatação de exibição
                    col_lower = col.lower()
                    if isinstance(val, (int, float)):
                        align = "R"
                        if "pct" in col_lower or "taxa" in col_lower or "conclusao" in col_lower or "preenchimento" in col_lower or "sla" in col_lower:
                            val_str = f"{val:.1f}%" if abs(val) > 1.0 else f"{val*100:.1f}%"
                        elif "valor" in col_lower or "score" in col_lower or "nps" in col_lower or "csat" in col_lower or "ces" in col_lower or "horas" in col_lower:
                            val_str = f"{val:.2f}"
                    else:
                        align = "L"
                        
                    row.cell(_latin1(val_str), align=align)

    return bytes(pdf.output())


def export_pdf_multi(sources: List[Dict[str, Any]], title: str = "Analise integrada") -> bytes:
    pdf = SenturyPDF(titulo=title, orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(51, 65, 85)
    pdf.multi_cell(
        0,
        6,
        _latin1("Relatorio consolidado com multiplas fontes analiticas da conversa."),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)

    for idx, item in enumerate(sources, start=1):
        tool = str(item.get("tool") or f"fonte_{idx}")
        result = item.get("result")
        if idx > 1:
            pdf.add_page()

        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(30, 41, 59)
        pdf.multi_cell(0, 8, _latin1(tool.replace("_", " ").title()), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        if isinstance(result, dict) and isinstance(result.get("markdown"), str):
            _render_markdown(pdf, result["markdown"])
            continue

        tabela, resumo = tabela_e_resumo(tool, result)
        resumo_escalar = {
            k: v for k, v in resumo.items()
            if not isinstance(v, (dict, list)) and v is not None and k != "markdown"
        }
        if resumo_escalar:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(30, 41, 59)
            pdf.cell(0, 6, _latin1("Resumo"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(51, 65, 85)
            for chave, valor in resumo_escalar.items():
                pdf.multi_cell(
                    0,
                    5,
                    _latin1(f"- {chave.replace('_', ' ').title()}: {valor}"),
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            pdf.ln(2)

        if tabela:
            colunas = list(tabela[0].keys())
            largura_disponivel = pdf.w - pdf.l_margin - pdf.r_margin
            col_widths = [largura_disponivel / max(len(colunas), 1)] * len(colunas)
            headings_style = FontFace(color=(255, 255, 255), fill_color=(30, 41, 59), emphasis="BOLD")
            with pdf.table(
                col_widths=col_widths,
                borders_layout="NONE",
                line_height=6,
                cell_fill_color=(248, 250, 252),
                cell_fill_mode="ROWS",
                headings_style=headings_style,
            ) as table:
                header = table.row()
                for col in colunas:
                    header.cell(_latin1(col.replace("_", " ").title()))
                for linha in tabela[:40]:
                    row = table.row()
                    for col in colunas:
                        row.cell(_latin1(linha.get(col, "")))

    return bytes(pdf.output())
