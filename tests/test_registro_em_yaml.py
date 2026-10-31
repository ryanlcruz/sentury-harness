"""A declaração da ferramenta mora em YAML; o código só deriva.

Acrescentar ou ajustar uma ferramenta de conhecimento deve ser
mexer no `tools.yaml`, não no código.
"""
import pytest

from sentury.tools import registry


def _escrever(pasta, texto):
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "tools.yaml").write_text(texto, encoding="utf-8")


def test_o_registro_vem_dos_yamls():
    assert registry.TOOL_REGISTRY["ler_pagina"]["texto_de_terceiros"] is True
    assert registry.setor_da_ferramenta("consultar_medida") == "setor_teste"
    assert registry.setor_da_ferramenta("ler_pagina") == ""


def test_o_setor_vem_da_pasta_e_ferramenta_sem_parametros_fica_livre(tmp_path, monkeypatch):
    _escrever(tmp_path / "motor", "minha_busca:\n  categoria: conhecimento\n  descricao: Busca nova.\n")
    _escrever(tmp_path / "setores" / "juridico", "ler_processo:\n  categoria: conhecimento\n  descricao: Le um processo.\n")
    monkeypatch.setattr(registry, "_AQUI", tmp_path / "motor")
    monkeypatch.setattr(registry, "_SETORES", tmp_path / "setores")

    novo = registry._registro()

    assert novo["minha_busca"]["parametros"] == registry._PARAMETROS_LIVRES
    assert novo["ler_processo"]["setor"] == "juridico"
    assert "setor" not in novo["minha_busca"]


def test_nome_repetido_entre_motor_e_setor_e_erro(tmp_path, monkeypatch):
    _escrever(tmp_path / "motor", "igual:\n  categoria: conhecimento\n  descricao: a\n")
    _escrever(tmp_path / "setores" / "x", "igual:\n  categoria: conhecimento\n  descricao: b\n")
    monkeypatch.setattr(registry, "_AQUI", tmp_path / "motor")
    monkeypatch.setattr(registry, "_SETORES", tmp_path / "setores")
    with pytest.raises(ValueError, match="duas vezes"):
        registry._registro()


def test_nao_ha_mais_declaracao_no_codigo():
    import inspect

    fonte = inspect.getsource(registry)
    assert '"orientacao":' not in fonte and '"quando_usar":' not in fonte
