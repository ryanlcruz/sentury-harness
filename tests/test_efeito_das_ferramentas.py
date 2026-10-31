"""Cada ferramenta declara o que faz no mundo, e cada ação também.

O efeito decide o que só observa e o que muda algo. Ferramenta nova sem
efeito, ou ação nova sem efeito, cairia em escrita sem ninguém escolher.
"""
from pathlib import Path

import pytest
import yaml

from sentury.tools.registry import EFEITOS, TOOL_REGISTRY, acoes_com_efeito, efeito_de

NUCLEO = yaml.safe_load((Path(__file__).resolve().parents[1] / "sentury" / "tools" / "tools.yaml")
                        .read_text(encoding="utf-8"))


@pytest.mark.parametrize("nome", sorted(NUCLEO))
def test_toda_ferramenta_do_nucleo_declara_o_efeito(nome):
    assert NUCLEO[nome].get("efeito") in EFEITOS, f"{nome} sem `efeito`"


def test_toda_acao_declara_o_efeito_e_a_ferramenta_e_o_da_mais_forte():
    for nome, meta in NUCLEO.items():
        enum = ((meta.get("parametros") or {}).get("properties") or {}).get("acao", {}).get("enum")
        if not enum:
            continue
        acoes = meta.get("acoes") or {}
        assert set(acoes) == set(enum), f"{nome}: ações do schema e do `acoes` diferem"
        assert set(acoes.values()) <= set(EFEITOS)
        mais_forte = max(acoes.values(), key=EFEITOS.index)
        assert meta["efeito"] == mais_forte, f"{nome}: `efeito` deveria ser {mais_forte}"


def test_efeito_da_chamada_segue_a_acao():
    assert efeito_de("memoria", {"acao": "listar"}) == "leitura"
    assert efeito_de("memoria", {"acao": "salvar"}) == "escrita"
    # Sem ação, ou com ação que não existe, vale o mais forte.
    assert efeito_de("memoria", {}) == "escrita"
    assert efeito_de("memoria", {"acao": "inventada"}) == "escrita"
    assert efeito_de("codigo", {"acao": "chamadas"}) == "leitura"
    assert efeito_de("ler_arquivo") == "leitura"
    # Apagar o que se refaz (encerrar comando, esquecer, cancelar agenda) é escrita.
    assert efeito_de("kill_command") == "escrita"


def test_toda_ferramenta_registrada_tem_efeito():
    """Setor que não declara cai na categoria: análise só lê, o resto escreve."""
    for nome in TOOL_REGISTRY:
        assert efeito_de(nome) in EFEITOS


def test_listas_do_computador_e_do_navegador_concordam_com_o_yaml():
    """As listas que decidem cartão no computador e no navegador não podem
    contradizer o efeito declarado: leitura nunca vira gesto, e o que muda a
    página nunca é tratado como leitura."""
    from sentury.tools import browser_contracts, computador

    assert computador.LEITURA == frozenset({"ver", "elementos", "janelas", "programas", "esperar", "ler"})
    assert computador.GESTOS <= acoes_com_efeito("computador", "escrita", "destrutiva")
    assert browser_contracts.ACOES_MUTANTES <= acoes_com_efeito("browser", "escrita", "destrutiva")
    leituras = acoes_com_efeito("browser", "leitura")
    assert leituras <= browser_contracts.ACOES_IDEMPOTENTES
    assert not leituras & browser_contracts.ACOES_MUTANTES
