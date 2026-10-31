"""O cliente escolhe onde os dados e a sessao moram.

Quem usa o Sentury nao precisa migrar o data warehouse dele, e quem nao pode
exportar dado (LGPD, politica interna) pluga o proprio backend.
"""
import os

import pytest

from sentury.data.store import DATA_BACKENDS, get_store, register_data_backend
from sentury.memory.session_store import (
    SESSION_BACKENDS,
    InMemorySessionStore,
    get_session_store,
)
from sentury.memory.local_session_store import LocalSessionStore


class _Cfg:
    # Sem isto o store de teste abre em ~/.sentury, onde um Sentury de verdade
    # pode estar escrevendo: e o lock de escritor unico recusa, com razao.
    SENTURY_HOME = os.environ.get("SENTURY_HOME", "")
    SENTURY_SESSION_BACKEND = ""
    SENTURY_DATA_BACKEND = ""
    SENTURY_MOCK_SEED = 1
    SENTURY_MOCK_FEEDBACKS = 10
    SENTURY_MOCK_TICKETS = 10
    SENTURY_MOCK_TECHNICIANS = 2
    SENTURY_MOCK_CONTACTS = 5


def test_so_existem_backends_locais():
    """Sessao so em disco local ou memoria: ela nao sai da maquina."""
    assert set(SESSION_BACKENDS) == {"local", "memory"}


def test_escolha_explicita_vence_o_padrao():
    c = _Cfg()
    c.SENTURY_SESSION_BACKEND = "memory"
    assert isinstance(get_session_store(c), InMemorySessionStore)


def test_local_duravel_e_o_padrao_sem_servico_externo(tmp_path):
    c = _Cfg()
    c.SENTURY_HOME = str(tmp_path)
    assert isinstance(get_session_store(c), LocalSessionStore)


def test_backend_desconhecido_falha_dizendo_as_opcoes():
    """Erro que ensina: config errada nao pode virar fallback silencioso pra
    memoria, que perderia a sessao do usuario sem avisar."""
    c = _Cfg()
    c.SENTURY_SESSION_BACKEND = "dynamo"
    with pytest.raises(ValueError) as e:
        get_session_store(c)
    assert "local" in str(e.value) and "memory" in str(e.value)


def test_nenhum_backend_e_eleito_por_omissao():
    """O `if` encadeado elegia o Supabase sempre que a credencial existisse no
    ambiente: e a credencial existia, apontando para uma instancia suspensa.

    Por isso o registro so traz o de memoria: quem precisar de outro backend
    registra o seu, e a escolha vem de `SENTURY_DATA_BACKEND`, nunca da
    credencial que por acaso esteja no ambiente.
    """
    assert "memory" in DATA_BACKENDS
    assert "supabase" not in DATA_BACKENDS and "sqlite" not in DATA_BACKENDS

def test_cliente_registra_a_fonte_dele_sem_tocar_no_nucleo():
    """O ponto do white-label: adapter novo entra pelo registro."""
    class _MinhaFonte:
        def __init__(self, cfg):
            self.cfg = cfg

    register_data_backend("meu_postgres", _MinhaFonte)
    c = _Cfg()
    c.SENTURY_DATA_BACKEND = "meu_postgres"
    assert isinstance(get_store(c), _MinhaFonte)


def test_fonte_desconhecida_falha_dizendo_como_registrar():
    c = _Cfg()
    c.SENTURY_DATA_BACKEND = "bigquery"
    with pytest.raises(ValueError) as e:
        get_store(c)
    assert "register_data_backend" in str(e.value)
