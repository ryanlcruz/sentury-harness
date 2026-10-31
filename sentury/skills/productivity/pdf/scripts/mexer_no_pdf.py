"""Operações em PDF que já existe, sem escrever código de PDF.

    python mexer_no_pdf.py info contrato.pdf
    python mexer_no_pdf.py texto contrato.pdf [--paginas 1-3] [--saida texto.txt]
    python mexer_no_pdf.py juntar saida.pdf a.pdf b.pdf c.pdf
    python mexer_no_pdf.py separar contrato.pdf pasta/ [--a-cada 1]
    python mexer_no_pdf.py paginas contrato.pdf "1-3,5" saida.pdf
    python mexer_no_pdf.py girar contrato.pdf 90 saida.pdf [--paginas 2]
    python mexer_no_pdf.py campos formulario.pdf
    python mexer_no_pdf.py preencher formulario.pdf valores.json saida.pdf

Página conta a partir de 1, como a pessoa vê no leitor. Precisa do pypdf.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject


def paginas_pedidas(espec: str, total: int) -> List[int]:
    """'1-3,5' vira [0, 1, 2, 4]. Vazio é o documento inteiro."""
    if not espec:
        return list(range(total))
    indices: List[int] = []
    for parte in espec.replace(" ", "").split(","):
        if not parte:
            continue
        inicio, _, fim = parte.partition("-")
        de, ate = int(inicio), int(fim or inicio)
        if de < 1 or ate > total or de > ate:
            raise ValueError(f"página {parte} fora do documento (1 a {total})")
        indices.extend(range(de - 1, ate))
    return indices


def info(args) -> int:
    leitor = PdfReader(str(args.arquivo))
    meta = leitor.metadata or {}
    print(json.dumps({
        "paginas": len(leitor.pages),
        "protegido": leitor.is_encrypted,
        "titulo": meta.get("/Title"),
        "autor": meta.get("/Author"),
        "campos_de_formulario": len(leitor.get_fields() or {}),
    }, ensure_ascii=False, indent=2))
    return 0


def texto(args) -> int:
    leitor = PdfReader(str(args.arquivo))
    partes = []
    for i in paginas_pedidas(args.paginas, len(leitor.pages)):
        partes.append(f"--- página {i + 1} ---\n{leitor.pages[i].extract_text() or ''}")
    saida = "\n\n".join(partes)
    if args.saida:
        Path(args.saida).write_text(saida, encoding="utf-8")
        print(f"{args.saida} ({len(partes)} páginas)")
    else:
        print(saida)
    return 0


def juntar(args) -> int:
    escritor = PdfWriter()
    for arquivo in args.arquivos:
        escritor.append(str(arquivo))
    escritor.write(str(args.saida))
    print(f"{args.saida} ({len(escritor.pages)} páginas)")
    return 0


def separar(args) -> int:
    leitor = PdfReader(str(args.arquivo))
    pasta = Path(args.pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    total, passo = len(leitor.pages), max(1, args.a_cada)
    criados = []
    for inicio in range(0, total, passo):
        escritor = PdfWriter()
        for i in range(inicio, min(inicio + passo, total)):
            escritor.add_page(leitor.pages[i])
        destino = pasta / f"{args.arquivo.stem}-{inicio + 1:03d}.pdf"
        escritor.write(str(destino))
        criados.append(destino.name)
    print(f"{len(criados)} arquivos em {pasta}")
    return 0


def paginas(args) -> int:
    leitor = PdfReader(str(args.arquivo))
    escritor = PdfWriter()
    for i in paginas_pedidas(args.espec, len(leitor.pages)):
        escritor.add_page(leitor.pages[i])
    escritor.write(str(args.saida))
    print(f"{args.saida} ({len(escritor.pages)} páginas)")
    return 0


def girar(args) -> int:
    if args.graus % 90:
        raise ValueError("o giro é de 90 em 90 graus")
    leitor = PdfReader(str(args.arquivo))
    escritor = PdfWriter()
    alvo = set(paginas_pedidas(args.paginas, len(leitor.pages)))
    for i, pagina in enumerate(leitor.pages):
        if i in alvo:
            pagina.rotate(args.graus)
        escritor.add_page(pagina)
    escritor.write(str(args.saida))
    print(f"{args.saida} ({len(alvo)} páginas giradas)")
    return 0


def campos(args) -> int:
    leitor = PdfReader(str(args.arquivo))
    dados = {nome: (campo.get("/V") if isinstance(campo, dict) else None)
             for nome, campo in (leitor.get_fields() or {}).items()}
    print(json.dumps(dados, ensure_ascii=False, indent=2, default=str))
    return 0


def preencher(args) -> int:
    valores = json.loads(Path(args.valores).read_text(encoding="utf-8-sig"))
    leitor = PdfReader(str(args.arquivo))
    existentes = set((leitor.get_fields() or {}).keys())
    desconhecidos = sorted(set(valores) - existentes)
    if desconhecidos:
        raise ValueError(f"campos que o formulário não tem: {', '.join(desconhecidos)}")
    escritor = PdfWriter()
    escritor.append(leitor)
    # Formulário gerado por ferramenta simples vem sem fonte padrão (/DR, /DA)
    # e o pypdf quebra ao desenhar o valor; uma fonte base resolve.
    formulario = escritor._root_object.get("/AcroForm")
    if formulario is not None:
        formulario = formulario.get_object()
        if "/DR" not in formulario:
            helvetica = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            })
            formulario[NameObject("/DR")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/Helv"): helvetica}),
            })
        if "/DA" not in formulario:
            formulario[NameObject("/DA")] = TextStringObject("/Helv 0 Tf 0 g")
    for pagina in escritor.pages:
        escritor.update_page_form_field_values(pagina, valores, auto_regenerate=False)
    escritor.set_need_appearances_writer(True)
    escritor.write(str(args.saida))
    print(f"{args.saida} ({len(valores)} campos preenchidos)")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="acao", required=True)

    p = sub.add_parser("info"); p.add_argument("arquivo", type=Path); p.set_defaults(fn=info)
    p = sub.add_parser("texto"); p.add_argument("arquivo", type=Path)
    p.add_argument("--paginas", default=""); p.add_argument("--saida", default=""); p.set_defaults(fn=texto)
    p = sub.add_parser("juntar"); p.add_argument("saida", type=Path)
    p.add_argument("arquivos", type=Path, nargs="+"); p.set_defaults(fn=juntar)
    p = sub.add_parser("separar"); p.add_argument("arquivo", type=Path); p.add_argument("pasta")
    p.add_argument("--a-cada", type=int, default=1); p.set_defaults(fn=separar)
    p = sub.add_parser("paginas"); p.add_argument("arquivo", type=Path); p.add_argument("espec")
    p.add_argument("saida", type=Path); p.set_defaults(fn=paginas)
    p = sub.add_parser("girar"); p.add_argument("arquivo", type=Path); p.add_argument("graus", type=int)
    p.add_argument("saida", type=Path); p.add_argument("--paginas", default=""); p.set_defaults(fn=girar)
    p = sub.add_parser("campos"); p.add_argument("arquivo", type=Path); p.set_defaults(fn=campos)
    p = sub.add_parser("preencher"); p.add_argument("arquivo", type=Path); p.add_argument("valores")
    p.add_argument("saida", type=Path); p.set_defaults(fn=preencher)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, ValueError) as exc:
        print(f"Não deu: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
