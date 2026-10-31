"""Helpers de skill do sandbox: fazem o trabalho real (Pillow, pyfiglet,
python-pptx, SVG, arquivo Excalidraw) no processo do backend: Python puro,
então funcionam igual em local/Render/VPS. E a entrega limpa de mídia (gif)."""
import os
import pathlib
import re
import zipfile

import pytest

import sentury.exec.python_exec as python_exec
from sentury.exec.python_exec import (
    _ascii_banner_helper,
    _meme_helper,
    _render_ascii_table_helper,
    _save_excalidraw_helper,
    _save_pptx_helper,
    _save_svg_diagram_helper,
)
from sentury.harness.fechamento_do_turno import _extract_media_url


def _saida(nome):
    """Onde o helper grava de verdade.

    Era o diretorio do teste, porque `_SANDBOX_ROOT` era `Path.cwd()`: a raiz
    do repositorio quando o servidor sobe de la. Agora o sandbox grava no
    rascunho do agente, e o teste pergunta ao sandbox onde ele gravou em vez de
    supor a pasta de codigo."""
    return str(pathlib.Path(python_exec._SANDBOX_ROOT) / nome)


def _cleanup(*paths):
    for p in paths:
        alvo = _saida(p)
        if os.path.exists(alvo):
            os.remove(alvo)


def test_meme_helper_cria_png():
    r = _meme_helper("Medida em queda", "ninguem surpreso", "t_meme")
    assert "sucesso" in r
    assert os.path.exists(_saida("t_meme.png")) and os.path.getsize(_saida("t_meme.png")) > 1000
    _cleanup("t_meme.png")


def test_ascii_banner():
    out = _ascii_banner_helper("Medida", "slant")
    assert isinstance(out, str) and len(out.strip()) > 0
    assert "\n" in out  # arte multi-linha


def test_ascii_banner_fallback_sem_pyfiglet(monkeypatch):
    monkeypatch.setattr(python_exec, "_load_optional_module", lambda name: None if name == "pyfiglet" else python_exec.optional_import(name))
    out = _ascii_banner_helper("Medida", "slant")
    assert "MEDIDA" in out.upper()
    assert "\n" in out


def test_ascii_table_helper_renders_box_table_with_alignment():
    out = _render_ascii_table_helper(
        ["Regiao", "Medida"],
        [["Alfa", -32.5], ["Beta", 12.0]],
    )
    lines = out.splitlines()
    assert lines[0].startswith("+") and lines[0].endswith("+")
    assert "| Regiao " in out
    assert "| Alfa " in out
    assert "| -32.5 " in out
    assert any(line.startswith("|") and "Alfa" in line for line in lines)


def test_ascii_table_helper_wraps_long_cells():
    out = _render_ascii_table_helper(
        ["Canal", "Comentario"],
        [["WhatsApp", "Fila estourada no Alfa com espera acima do toleravel"]],
        max_cell_width=14,
    )
    assert "WhatsApp" in out
    assert "Fila estourada" in out or "Fila" in out
    assert out.count("\n") >= 5


def test_pptx_helper():
    r = _save_pptx_helper("t_deck", [{"title": "Diag", "bullets": ["a", "b"]}])
    assert "sucesso" in r and os.path.exists(_saida("t_deck.pptx"))
    _cleanup("t_deck.pptx")


def test_pptx_helper_fallback_sem_python_pptx(monkeypatch):
    monkeypatch.setattr(
        python_exec,
        "_load_optional_module",
        lambda name: None if name.startswith("pptx") else python_exec.optional_import(name),
    )
    monkeypatch.setattr(python_exec, "_find_local_pptx_template", lambda: None)
    r = _save_pptx_helper("t_deck_fallback", [{"title": "Diag", "bullets": ["a", "b"]}])
    assert "sucesso" in r and os.path.exists(_saida("t_deck_fallback.pptx"))
    with zipfile.ZipFile(_saida("t_deck_fallback.pptx")) as archive:
        names = set(archive.namelist())
    assert "[Content_Types].xml" in names
    assert "ppt/presentation.xml" in names
    _cleanup("t_deck_fallback.pptx")


def test_svg_diagram_helper():
    r = _save_svg_diagram_helper("t_svg", [{"id": "a", "text": "X", "x": 40, "y": 40}], [])
    assert os.path.exists(_saida("t_svg.svg"))
    with open(_saida("t_svg.svg"), encoding="utf-8") as f:
        assert "<svg" in f.read()
    _cleanup("t_svg.svg")


def test_excalidraw_helper():
    r = _save_excalidraw_helper("t_exc", [{"id": "a", "text": "Medida", "color": "red", "x": 10, "y": 10}])
    assert os.path.exists(_saida("t_exc.excalidraw"))
    _cleanup("t_exc.excalidraw")


# --- Entrega limpa de mídia (gif) ---

def test_extract_media_url_from_gif_result():
    tool_results = [{"tool": "executar_python", "result": {"resultado": "https://media.tenor.com/abc/x.gif"}}]
    assert _extract_media_url(tool_results) == "https://media.tenor.com/abc/x.gif"


def test_extract_media_url_none_for_analysis():
    tool_results = [{"tool": "consultar_medida", "result": {"medida": -32.5, "volume": 3000}}]
    assert _extract_media_url(tool_results) is None


def test_extract_media_url_from_saida():
    tool_results = [{"tool": "executar_python", "result": {"saida": "http://x.com/a.png", "resultado": None}}]
    assert _extract_media_url(tool_results) == "http://x.com/a.png"


# --- SVG livre (rico) + sanitização ---
def test_save_svg_free_sanitiza():
    from sentury.exec.python_exec import _save_svg_helper
    mal = '<svg viewBox="0 0 100 100"><script>alert(1)</script><rect onclick="x()" width="50" height="50" fill="red"/></svg>'
    r = _save_svg_helper("t_free", mal)
    assert "sucesso" in r and os.path.exists(_saida("t_free.svg"))
    c = open(_saida("t_free.svg"), encoding="utf-8").read()
    assert "<script" not in c.lower() and "onclick" not in c.lower()
    assert '<rect' in c and 'red' in c
    _cleanup("t_free.svg")


def test_save_svg_rejeita_nao_svg():
    from sentury.exec.python_exec import _save_svg_helper
    assert "Erro" in _save_svg_helper("x", "só um texto sem svg")


def test_svg_diagram_layouts():
    from sentury.exec.python_exec import _save_svg_diagram_helper
    boxes = [{"id": "a", "text": "Medida", "color": "red", "level": 0}, {"id": "b", "text": "SLA", "color": "yellow", "level": 1}]
    for lay in ("flow", "tree", "star", "funnel"):
        r = _save_svg_diagram_helper(f"t_{lay}", boxes, [{"from": "b", "to": "a"}], layout=lay, title="T")
        assert lay in r and os.path.exists(_saida(f"t_{lay}.svg"))
        _cleanup(f"t_{lay}.svg")


def test_svg_tree_without_explicit_levels_spreads_nodes_across_more_than_two_rows():
    boxes = [
        {"id": "root", "text": "Medida em queda", "color": "red"},
        {"id": "a", "text": "Fila pendente", "color": "yellow"},
        {"id": "b", "text": "SLA fora", "color": "yellow"},
        {"id": "c", "text": "Clientes em risco", "color": "purple"},
        {"id": "d", "text": "Tickets repetidos", "color": "blue"},
    ]
    arrows = [
        {"from": "root", "to": "a"},
        {"from": "root", "to": "b"},
        {"from": "a", "to": "c"},
        {"from": "b", "to": "d"},
    ]

    _save_svg_diagram_helper("t_tree_auto", boxes, arrows, layout="tree", title="Causa-raiz")

    svg = open(_saida("t_tree_auto.svg"), encoding="utf-8").read()
    y_positions = {int(match) for match in re.findall(r'<rect x="\d+" y="(\d+)" width="\d+" height="80" rx="14"', svg)}

    assert len(y_positions) >= 3
    _cleanup("t_tree_auto.svg")


def test_svg_flow_wraps_long_sequences_across_multiple_rows():
    boxes = [{"id": f"n{i}", "text": f"Etapa {i}", "color": "blue"} for i in range(1, 7)]
    arrows = [{"from": f"n{i}", "to": f"n{i+1}"} for i in range(1, 6)]

    _save_svg_diagram_helper("t_flow_wrap", boxes, arrows, layout="flow", title="Jornada")

    svg = open(_saida("t_flow_wrap.svg"), encoding="utf-8").read()
    y_positions = {int(match) for match in re.findall(r'<rect x="\d+" y="(\d+)" width="\d+" height="80" rx="14"', svg)}

    assert len(y_positions) >= 2
    _cleanup("t_flow_wrap.svg")
