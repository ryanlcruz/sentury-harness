import os

import pytest

from sentury.tools import shell


@pytest.fixture(autouse=True)
def cache_isolado(monkeypatch):
    monkeypatch.setattr(shell, "_CONFIG", {})
    monkeypatch.setattr(shell, "_CONFIG_FONTE", None)


def test_trocar_arquivo_da_politica_nao_reusa_a_anterior(tmp_path, monkeypatch):
    primeira, segunda = tmp_path / "primeira.yaml", tmp_path / "segunda.yaml"
    primeira.write_text("leitura: {git: [log]}\n", encoding="utf-8")
    segunda.write_text("leitura: {git: [status]}\n", encoding="utf-8")
    monkeypatch.setenv("SENTURY_SHELL_CONFIG", str(primeira))
    assert shell.politica()["leitura"]["git"] == ["log"]
    monkeypatch.setenv("SENTURY_SHELL_CONFIG", str(segunda))
    assert shell.politica()["leitura"]["git"] == ["status"]
    monkeypatch.setenv("SENTURY_SHELL_CONFIG", str(primeira))
    assert shell.politica()["leitura"]["git"] == ["log"]


def test_edicao_no_mesmo_arquivo_invalida_o_cache(tmp_path, monkeypatch):
    arquivo = tmp_path / "politica.yaml"
    arquivo.write_text("leitura: {git: [log]}\n", encoding="utf-8")
    monkeypatch.setenv("SENTURY_SHELL_CONFIG", str(arquivo))
    antes = arquivo.stat().st_mtime_ns
    assert shell.politica()["leitura"]["git"] == ["log"]
    arquivo.write_text("leitura: {git: [status]}\n", encoding="utf-8")
    os.utime(arquivo, ns=(antes + 1_000_000, antes + 1_000_000))
    assert shell.politica()["leitura"]["git"] == ["status"]


def test_politica_removida_fecha_o_shell_e_nao_reaproveita_permissao(tmp_path, monkeypatch):
    arquivo = tmp_path / "politica.yaml"
    arquivo.write_text("leitura: {git: [log]}\n", encoding="utf-8")
    monkeypatch.setenv("SENTURY_SHELL_CONFIG", str(arquivo))
    assert shell.politica()["leitura"]
    arquivo.unlink()
    assert shell.politica()["leitura"] == {}
    arquivo.write_text("leitura: {git: [status]}\n", encoding="utf-8")
    assert shell.politica()["leitura"]["git"] == ["status"]
