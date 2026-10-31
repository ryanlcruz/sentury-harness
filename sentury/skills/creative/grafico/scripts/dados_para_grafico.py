"""Tabela para gráfico PNG com o visual do Sentury, desenhado na própria máquina.

    python dados_para_grafico.py vendas.csv vendas.png --x regiao --y total
    python dados_para_grafico.py dados.json evolucao.png --x mes --y receita --y custo --tipo linha
    python dados_para_grafico.py dados.csv fatias.png --x canal --y tickets --tipo rosca --titulo "Tickets por canal"

Entrada: CSV com cabeçalho, ou JSON com uma lista de objetos. Tipos: barra,
barra-horizontal, linha, rosca, dispersao. Precisa do matplotlib.
"""
from __future__ import annotations

import argparse
import csv
import re
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CORES = ["#6366F1", "#14B8A6", "#F59E0B", "#EF4444", "#A855F7", "#0EA5E9"]
TEXTO = "#1E293B"
GRADE = "#F1F5F9"
BORDA = "#CBD5E1"
TIPOS = ("barra", "barra-horizontal", "linha", "rosca", "dispersao")


def ler_linhas(caminho: Path) -> List[Dict[str, Any]]:
    texto = caminho.read_text(encoding="utf-8-sig")
    if caminho.suffix.lower() == ".json":
        dados = json.loads(texto)
        if isinstance(dados, dict):
            # Formatos comuns de resultado: {"dados": [...]}, {"tabela": [...]}.
            dados = next((v for v in dados.values() if isinstance(v, list)), [])
        return [d for d in dados if isinstance(d, dict)]
    return list(csv.DictReader(texto.splitlines()))


def numero(valor: Any) -> float:
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor or "").strip().replace("%", "").replace(" ", "")
    # 1.234,5 (pt-BR) e 1,234.5 (en) viram 1234.5; "1.240" sozinho é milhar.
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        return float(s.replace(".", ""))
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def desenhar(linhas: List[Dict[str, Any]], x: str, ys: List[str], tipo: str, titulo: str):
    faltam = [c for c in [x, *ys] if linhas and c not in linhas[0]]
    if faltam:
        raise SystemExit(f"coluna inexistente: {', '.join(faltam)}; as colunas são {', '.join(linhas[0])}")
    rotulos = [str(l.get(x, "")) for l in linhas]
    series = {y: [numero(l.get(y)) for l in linhas] for y in ys}

    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor="white")
    ax.set_facecolor("white")
    ax.set_axisbelow(True)
    if tipo == "rosca":
        y = ys[0]
        ax.pie(series[y], labels=rotulos, startangle=90, colors=(CORES * 10)[: len(rotulos)],
               wedgeprops={"width": 0.42, "edgecolor": "white"}, textprops={"color": TEXTO, "fontsize": 9})
        ax.axis("equal")
    elif tipo == "dispersao":
        ax.scatter(series[ys[0]], series[ys[1]] if len(ys) > 1 else [numero(r) for r in rotulos],
                   color=CORES[0], alpha=0.8)
    else:
        largura = 0.8 / len(ys)
        for i, y in enumerate(ys):
            cor = CORES[i % len(CORES)]
            posicoes = [p + i * largura - 0.4 + largura / 2 for p in range(len(rotulos))]
            if tipo == "linha":
                ax.plot(rotulos, series[y], marker="o", color=cor, linewidth=2.5, markersize=5, label=y)
            elif tipo == "barra-horizontal":
                ax.barh(posicoes, series[y], height=largura, color=cor, alpha=0.9, label=y)
                ax.set_yticks(range(len(rotulos)), rotulos)
            else:
                ax.bar(posicoes, series[y], width=largura, color=cor, alpha=0.9, label=y)
                ax.set_xticks(range(len(rotulos)), rotulos)
        if len(ys) > 1:
            ax.legend(frameon=False, fontsize=9)
    if tipo != "rosca":
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
        for lado in ("left", "bottom"):
            ax.spines[lado].set_color(BORDA)
        ax.grid(axis="x" if tipo == "barra-horizontal" else "y", linestyle="--", alpha=0.7, color=GRADE)
        ax.tick_params(axis="both", colors=TEXTO, labelsize=9)
        if tipo != "barra-horizontal" and max((len(r) for r in rotulos), default=0) > 6:
            ax.tick_params(axis="x", rotation=35)
    if titulo:
        ax.set_title(titulo, color=TEXTO, fontsize=12, fontweight="bold", loc="left")
    fig.tight_layout()
    return fig


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Desenha um gráfico PNG a partir de CSV ou JSON.")
    parser.add_argument("entrada", help="arquivo .csv ou .json")
    parser.add_argument("saida", help="caminho do PNG a gravar")
    parser.add_argument("--x", required=True, help="coluna dos rótulos (ou do eixo x)")
    parser.add_argument("--y", action="append", required=True, help="coluna dos valores; repita para mais séries")
    parser.add_argument("--tipo", choices=TIPOS, default="barra")
    parser.add_argument("--titulo", default="")
    args = parser.parse_args(argv)

    linhas = ler_linhas(Path(args.entrada))
    if not linhas:
        raise SystemExit("a entrada não tem linhas de dados")
    fig = desenhar(linhas, args.x, args.y, args.tipo, args.titulo)
    destino = Path(args.saida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=160)
    plt.close(fig)
    print(f"Gráfico gravado em {destino.resolve()} ({len(linhas)} pontos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
