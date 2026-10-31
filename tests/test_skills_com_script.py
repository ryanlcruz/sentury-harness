"""Skills que trazem script pronto: o agente escreve o conteúdo, o script desenha."""
import importlib.util
import json
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[1] / "sentury" / "skills"


def _script(caminho: str):
    arquivo = SKILLS / caminho
    spec = importlib.util.spec_from_file_location(arquivo.stem, arquivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_o_carregador_acha_as_tres_e_mostra_a_pasta():
    from sentury.skills.skill_loader import SkillLoader

    carregador = SkillLoader(SKILLS, com_setor=True)
    nomes = {e.name for e in carregador.scan_skills()}
    assert {"relatorio-pdf", "planilha", "grafico"} <= nomes
    bloco = carregador.load_skill("grafico").to_context_block()
    assert "Skill directory:" in bloco and "dados_para_grafico.py" in bloco


def test_markdown_vira_pdf_com_o_titulo_so_na_capa(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("# Vendas — setembro\n\n| Região | Total |\n|---|---|\n| Sul | 1.240 |\n", encoding="utf-8")
    saida = tmp_path / "r.pdf"
    assert _script("productivity/relatorio-pdf/scripts/markdown_para_pdf.py").main([str(md), str(saida)]) == 0
    assert saida.read_bytes().startswith(b"%PDF")

    import pdfplumber

    with pdfplumber.open(saida) as pdf:
        texto = pdf.pages[0].extract_text()
    assert texto.count("Vendas - setembro") == 1 and "1.240" in texto


def test_o_export_da_interface_usa_o_mesmo_desenho():
    from sentury.renderers import pdf

    modulo = _script("productivity/relatorio-pdf/scripts/markdown_para_pdf.py")
    assert pdf.SenturyPDF.__name__ == modulo.SenturyPDF.__name__
    assert pdf.markdown_para_pdf("# x\n\ntexto", "Plano").startswith(b"%PDF")


def test_planilha_grava_numero_brasileiro_como_numero(tmp_path):
    entrada = tmp_path / "v.json"
    entrada.write_text(json.dumps({"Setembro": [{"regiao": "Sul", "total": "1.240"},
                                                {"regiao": "Norte", "total": "2.310,5"}],
                                   "Outubro": [{"regiao": "Sul", "total": 900}]}), encoding="utf-8")
    saida = tmp_path / "v.xlsx"
    assert _script("productivity/planilha/scripts/tabela_para_xlsx.py").main([str(entrada), str(saida)]) == 0

    import openpyxl

    livro = openpyxl.load_workbook(saida)
    assert livro.sheetnames == ["Setembro", "Outubro"]
    folha = livro["Setembro"]
    assert [c.value for c in folha["B"]] == ["total", 1240, 2310.5]
    assert folha.freeze_panes == "A2" and folha.auto_filter.ref == "A1:B3"


@pytest.mark.parametrize("tipo", ["barra", "barra-horizontal", "linha", "rosca"])
def test_grafico_desenha_cada_tipo(tmp_path, tipo):
    entrada = tmp_path / "v.csv"
    entrada.write_text('regiao,vendas,meta\nSul,1.240,1100\nNorte,830,900\n', encoding="utf-8")
    saida = tmp_path / f"{tipo}.png"
    script = _script("creative/grafico/scripts/dados_para_grafico.py")
    assert script.main([str(entrada), str(saida), "--x", "regiao", "--y", "vendas", "--y", "meta",
                        "--tipo", tipo]) == 0
    assert saida.read_bytes()[:4] == b"\x89PNG"


def test_grafico_diz_qual_coluna_falta(tmp_path):
    entrada = tmp_path / "v.csv"
    entrada.write_text("regiao,vendas\nSul,10\n", encoding="utf-8")
    script = _script("creative/grafico/scripts/dados_para_grafico.py")
    with pytest.raises(SystemExit, match="coluna inexistente: total"):
        script.main([str(entrada), str(tmp_path / "x.png"), "--x", "regiao", "--y", "total"])
