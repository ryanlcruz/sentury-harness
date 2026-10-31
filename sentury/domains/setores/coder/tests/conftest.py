"""Isola os dados e as contas da bancada do setor."""
from tests.conftest import _casa_do_robinbandit, _sem_caixa_da_maquina

import pytest


@pytest.fixture(autouse=True)
def _escolha_do_pacote(monkeypatch):
    monkeypatch.setattr("sentury.domains.escolha.ler", lambda *a, **k: "coder")
