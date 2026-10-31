"""Markdown pronto para PDF com o visual do Sentury, sem chamar modelo.

    python markdown_para_pdf.py relatorio.md relatorio.pdf --titulo "Vendas de setembro"
    python markdown_para_pdf.py - saida.pdf < relatorio.md

Entende títulos (#, ##, ###), listas com - ou *, tabelas markdown e parágrafos.
Negrito, itálico e código inline viram texto simples. Precisa do fpdf2.

O mesmo desenho é o do botão "Exportar PDF" da interface, que importa este
arquivo: os dois caminhos saem iguais.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List

from fpdf import FPDF
from fpdf.fonts import FontFace

_EMOJI = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\ufe0f"  # seletor de apresentação
    "\u200d"  # junção de símbolos
    "]+",
    flags=re.UNICODE,
)

# As fontes embutidas do fpdf só têm latin-1: o travessão virava "?" no PDF.
_TROCAS = {
    "—": "-", "–": "-", "―": "-", "“": '"', "”": '"', "„": '"',
    "‘": "'", "’": "'", "…": "...", "•": "-", "→": "->", "≈": "~",
    " ": " ",
}


def latin1(texto: Any) -> str:
    s = str(texto)
    for de, para in _TROCAS.items():
        s = s.replace(de, para)
    s = _EMOJI.sub("", s)
    return s.encode("latin-1", "replace").decode("latin-1")


def sem_marcacao(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    s = re.sub(r"_(.+?)_", r"\1", s)
    return s


class SenturyPDF(FPDF):
    def __init__(self, titulo: str = "Relatório", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.titulo_relatorio = titulo

    def header(self):
        self.set_fill_color(79, 70, 229)
        self.rect(0, 0, self.w, 4, "F")
        if self.page_no() == 1:
            self.set_y(8)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(99, 102, 241)
            self.cell(0, 5, latin1("SENTURY"), new_x="LMARGIN", new_y="NEXT")
            self.set_font("Helvetica", "B", 18)
            self.set_text_color(30, 41, 59)
            self.multi_cell(0, 10, latin1(self.titulo_relatorio), new_x="LMARGIN", new_y="NEXT")
            self.set_font("Helvetica", "", 8)
            self.set_text_color(148, 163, 184)
            self.cell(0, 4, latin1(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}"),
                      new_x="LMARGIN", new_y="NEXT")
            self.ln(6)
        else:
            self.set_y(8)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(148, 163, 184)
            self.cell(0, 5, latin1(f"SENTURY  •  {self.titulo_relatorio.upper()}"), new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(226, 232, 240)
            self.line(self.l_margin, 14, self.w - self.r_margin, 14)
            self.set_y(16)

    def footer(self):
        self.set_y(-15)
        self.set_draw_color(226, 232, 240)
        self.line(self.l_margin, self.h - 16, self.w - self.r_margin, self.h - 16)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(148, 163, 184)
        self.cell(0, 10, latin1("Documento gerado automaticamente pelo Sentury."), align="L")
        self.set_font("Helvetica", "", 8)
        self.cell(0, 10, latin1(f"Página {self.page_no()}/{{nb}}"), align="R")


def desenhar_markdown(pdf: FPDF, md: str) -> None:
    linhas = md.split("\n")
    i = 0
    while i < len(linhas):
        linha = linhas[i].rstrip()
        if not linha.strip():
            pdf.ln(2)
            i += 1
            continue
        if linha.lstrip().startswith("|"):
            tabela = []
            while i < len(linhas) and linhas[i].strip().startswith("|"):
                tabela.append(linhas[i].rstrip())
                i += 1
            desenhar_tabela(pdf, tabela)
            continue
        titulo = re.match(r"^(#{1,6})\s+(.*)", linha)
        if titulo:
            pdf.ln(3)
            if len(titulo.group(1)) <= 2:
                pdf.set_font("Helvetica", "B", 14)
                pdf.set_text_color(30, 41, 59)
            else:
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(71, 85, 105)
            pdf.multi_cell(0, 7, latin1(sem_marcacao(titulo.group(2))), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
            i += 1
            continue
        item = re.match(r"^\s*[-*]\s+(.*)", linha)
        if item:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(51, 65, 85)
            pdf.cell(5, 6, latin1("•"))
            pdf.multi_cell(0, 6, latin1(sem_marcacao(item.group(1))), new_x="LMARGIN", new_y="NEXT")
            i += 1
            continue
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(51, 65, 85)
        pdf.multi_cell(0, 6, latin1(sem_marcacao(linha)), new_x="LMARGIN", new_y="NEXT")
        i += 1


def desenhar_tabela(pdf: FPDF, linhas_tabela: List[str]) -> None:
    linhas = []
    for linha in linhas_tabela:
        celulas = [c.strip() for c in linha.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in celulas if c):
            continue
        linhas.append(celulas)
    if not linhas:
        return
    cabecalho, dados = linhas[0], linhas[1:]
    # A fonte do título anterior vazava para as células: tabela inteira em negrito.
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(51, 65, 85)
    largura = (pdf.w - pdf.l_margin - pdf.r_margin) / len(cabecalho)
    estilo = FontFace(color=(255, 255, 255), fill_color=(30, 41, 59), emphasis="BOLD")
    with pdf.table(col_widths=[largura] * len(cabecalho), borders_layout="NONE", line_height=6,
                   cell_fill_color=(248, 250, 252), cell_fill_mode="ROWS", headings_style=estilo) as t:
        linha_pdf = t.row()
        for coluna in cabecalho:
            linha_pdf.cell(latin1(sem_marcacao(coluna)))
        for registro in dados:
            linha_pdf = t.row()
            for coluna in registro:
                valor = sem_marcacao(coluna)
                # Número e porcentagem alinham à direita, como numa planilha.
                alinha = "R" if re.match(r"^-?\d+([.,]\d+)?%?$", valor.strip()) else "L"
                linha_pdf.cell(latin1(valor), align=alinha)
    pdf.ln(2)


def markdown_para_pdf(md: str, titulo: str = "Relatório") -> bytes:
    pdf = SenturyPDF(titulo=titulo)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    desenhar_markdown(pdf, md)
    return bytes(pdf.output())


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Converte markdown em PDF com o visual do Sentury.")
    parser.add_argument("entrada", help="arquivo .md, ou - para ler da entrada padrão")
    parser.add_argument("saida", help="caminho do PDF a gravar")
    parser.add_argument("--titulo", default="", help="título da capa; sem ele, usa o primeiro # do texto")
    args = parser.parse_args(argv)

    md = sys.stdin.read() if args.entrada == "-" else Path(args.entrada).read_text(encoding="utf-8")
    titulo = args.titulo
    if not titulo:
        primeiro = re.search(r"^#\s+(.+)\n?", md, re.MULTILINE)
        titulo = sem_marcacao(primeiro.group(1)).strip() if primeiro else "Relatório"
        if primeiro:
            # O título já está na capa; repetido no corpo, aparecia duas vezes.
            md = md[:primeiro.start()] + md[primeiro.end():]
    destino = Path(args.saida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(markdown_para_pdf(md, titulo))
    print(f"PDF gravado em {destino.resolve()} ({destino.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
