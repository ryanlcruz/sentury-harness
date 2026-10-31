"""Pacotes de setor são carregados pelo contrato de arquivos."""
import pytest

from sentury.domains import carregador


def _pacote(tmp_path, nome="teste", extra=""):
    pasta = tmp_path / nome
    pasta.mkdir()
    (pasta / "pack.yaml").write_text(
        f"nome: {nome}\n"
        "metricas:\n"
        "  cobertura:\n"
        "    label: Cobertura\n"
        "    unidade: '%'\n"
        "    maior_melhor: true\n"
        "    grupo: operacao\n"
        "  satisfacao:\n"
        "    label: Satisfacao\n"
        "    grupo: experiencia\n"
        + extra,
        encoding="utf-8")
    return pasta


def test_pacote_vira_setor_sem_uma_linha_de_codigo(tmp_path):
    pack = carregador.ler(_pacote(tmp_path))
    assert pack.name == "teste"
    assert pack.metric_names == {"cobertura", "satisfacao"}
    # `grupo` separa percepcao de operacao, e isso muda o que ele promete saber.
    assert pack.cx_metrics == {"satisfacao"} and pack.ops_metrics == {"cobertura"}
    assert pack.higher_is_better["cobertura"] is True


def test_metrica_sem_grupo_cai_em_operacao(tmp_path):
    """Operacao e o lado que NAO promete leitura de percepcao do cliente:
    errar para esse lado afirma menos."""
    pasta = tmp_path / "solto"
    pasta.mkdir()
    (pasta / "pack.yaml").write_text(
        "nome: solto\nmetricas:\n  algo:\n    label: Algo\n", encoding="utf-8")
    pack = carregador.ler(pasta)
    assert pack.ops_metrics == {"algo"} and not pack.cx_metrics


def test_persona_pode_vir_de_arquivo(tmp_path):
    pasta = _pacote(tmp_path, extra="persona_arquivo: persona.md\n")
    (pasta / "persona.md").write_text("Voce e o Sentury de teste.", encoding="utf-8")
    assert "Sentury de teste" in carregador.ler(pasta).persona


def test_pacote_sem_metrica_e_recusado(tmp_path):
    """Um agente que fala de um setor sem saber medir nada dele e pior que
    nenhum setor."""
    pasta = tmp_path / "vazio"
    pasta.mkdir()
    (pasta / "pack.yaml").write_text("nome: vazio\n", encoding="utf-8")
    assert carregador.ler(pasta) is None


def test_pacote_quebrado_nao_derruba(tmp_path):
    pasta = tmp_path / "ruim"
    pasta.mkdir()
    (pasta / "pack.yaml").write_text("isto: [nao fecha", encoding="utf-8")
    assert carregador.ler(pasta) is None
    # E a descoberta segue com os que prestam.
    _pacote(tmp_path, "bom")
    assert [p.name for p in carregador.descobrir(str(tmp_path))] == ["bom"]


def test_pasta_ausente_e_o_generalista(tmp_path):
    """Sem pacote nenhum ele e generalista, nao um erro."""
    assert carregador.descobrir(str(tmp_path / "nao-existe")) == []


def test_pacote_de_teste_carrega_da_pasta():
    """O pacote de teste carrega do disco pelo mesmo contrato dos outros setores."""
    from pathlib import Path

    from sentury.domains.registry import DOMAIN_REGISTRY

    da_pasta = carregador.ler(Path("tests/fixtures/setor_teste"))
    assert da_pasta is not None, "o pacote de teste sumiu da pasta"
    assert da_pasta.metric_names, "o pacote da pasta perdeu as metricas"

    # E nao ha mais nenhum setor nascendo de codigo: tudo vem da pasta.
    assert not Path("sentury/domains/cx.py").exists()
    for nome in DOMAIN_REGISTRY:
        origem = Path("tests/fixtures") if nome == "setor_teste" else Path("sentury/domains/setores")
        assert (origem / nome / "pack.yaml").is_file(), nome


def test_registro_ve_os_pacotes_da_pasta():
    from sentury.domains import DOMAIN_REGISTRY

    assert "setor_teste" in DOMAIN_REGISTRY
    # O exemplo em `setores/coder` prova que um setor novo entra sem codigo.
    assert "setor_teste" in DOMAIN_REGISTRY
