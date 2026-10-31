"""Ligar e desligar setor pela interface.

Trocar de setor nao pode depender de editar o `.env` e reiniciar: a tela tem
o botao, e a escolha vale na hora.
"""
import pytest

from sentury.domains import DOMAIN_REGISTRY, get_active_domain
from sentury.domains.escolha import GENERALISTA, gravar, ler
from sentury.config import settings


@pytest.fixture(autouse=True)
def casa_temporaria(tmp_path, monkeypatch):
    """A escolha e da instalacao: nao pode vazar para o ~/.sentury de quem roda."""
    monkeypatch.setattr(
        "sentury.memory.local_session_store.default_sentury_home",
        lambda configurado="": tmp_path)
    yield


def test_sem_escolha_vale_o_env():
    assert ler() is None
    assert get_active_domain().name == settings.SENTURY_DOMAIN


def test_ligar_um_setor_troca_o_ativo():
    gravar("setor_teste")
    assert get_active_domain().name == "setor_teste"


def test_generalista_nao_traz_vocabulario_de_setor():
    """Desligado e o motor inteiro sem vocabulario nem metrica de setor:
    nao e um Sentury menor."""
    gravar(GENERALISTA)
    ativo = get_active_domain()
    assert ativo.name == GENERALISTA
    assert not ativo.metric_names


def test_vazio_e_generalista():
    assert gravar("") == GENERALISTA
    assert get_active_domain().name == GENERALISTA


def test_setor_desconhecido_nao_derruba():
    """E "nao derruba" significa virar GENERALISTA, nao virar CX.

    Cair num setor especifico e pior que nao cair em nenhum: o agente passa a
    falar de indicadores que a instalacao nao tem, sem ninguem ter pedido.
    """
    gravar("nao-existe")
    assert get_active_domain().name == "generalista"


def test_a_escolha_sobrevive_a_leitura_seguinte():
    gravar("setor_teste")
    assert ler() == "setor_teste"
    assert "setor_teste" in DOMAIN_REGISTRY
