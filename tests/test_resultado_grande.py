"""Resultado grande de ferramenta: começo e fim no contexto, o inteiro no rascunho.

Sem o corte, uma listagem longa ou uma página inteira entrava toda na conversa
e era reenviada a cada volta do turno.
"""
import re
from pathlib import Path

from sentury.llm import prompts
from sentury.llm.prompts import build_tool_result_instruction


def test_resultado_pequeno_entra_inteiro(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    texto = build_tool_result_instruction("executar_comando", {"ok": True, "saida": "abc"}, sessao="s1")
    assert "abc" in texto
    assert "ficaram fora" not in texto


def test_resultado_grande_vai_ao_rascunho_com_aviso(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    saida = "\n".join(f"linha {i:05d}" for i in range(5000))
    resultado = {"ok": True, "saida": saida}
    texto = build_tool_result_instruction("executar_comando", resultado, sessao="s1")

    assert len(texto) < prompts._TETO_DO_RESULTADO + 2_000
    assert "linha 00000" in texto and "linha 04999" in texto
    assert "linha 02500" not in texto
    caminho = re.search(r"`([^`]+resultado-executar_comando-[0-9a-f]+\.txt)`", texto).group(1)
    assert Path(caminho).read_text(encoding="utf-8") == str(resultado)
    assert "ler_arquivo" in texto


def test_o_rascunho_e_legivel_pelo_ler_arquivo(monkeypatch, tmp_path):
    """O caminho do aviso precisa abrir pela ferramenta que o aviso indica."""
    from sentury.tools import arquivos

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path / "trabalho"))
    (tmp_path / "trabalho").mkdir()
    texto = build_tool_result_instruction("executar_comando", {"saida": "x" * 20_000}, sessao="s2")
    caminho = re.search(r"`([^`]+\.txt)`", texto).group(1)
    lido = arquivos.ler(caminho, inicio=1, linhas=1)
    assert lido["ok"], lido
