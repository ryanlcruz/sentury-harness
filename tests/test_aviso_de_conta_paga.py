"""Conta paga sem chave so avisa quando alguem DECLAROU que paga.

Numa instalacao nova, com duas chaves, o painel de provedores abria com 36
avisos: 16 amarelos de "conta paga sem chave" para OpenAI, Bedrock, Vertex e
companhia: contas pagas por padrao do catalogo, que ninguem escolheu. Aviso que
aparece sempre e o que ninguem le, inclusive na vez que importa.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path("sentury/plugins/robinbandit/src")))

from robinbandit.account_health import diagnosticar  # noqa: E402


class _Config:
    providers = {}


def _gravidade(conta):
    return diagnosticar(_Config(), object(), [conta])[0]["gravidade"]


def test_paga_de_fabrica_nao_acende_amarelo():
    conta = {"id": "openai", "provider": "openai", "key_env": "OPENAI_API_KEY",
             "configurada": False, "paga": True, "declarada": False}
    assert _gravidade(conta) == "info"


def test_paga_declarada_pelo_usuario_acende():
    conta = {"id": "openai-trabalho", "provider": "openai", "key_env": "OPENAI_TRABALHO",
             "configurada": False, "paga": True, "declarada": True}
    assert _gravidade(conta) == "atencao"


def test_o_catalogo_diz_quem_foi_declarado(monkeypatch, tmp_path):
    """Descoberta e fabrica chegam com `declarada: false`; conta do painel, true."""
    monkeypatch.setenv("ROBINBANDIT_HOME", str(tmp_path))
    from robinbandit import account_config
    from robinbandit.accounts import catalogo_efetivo
    from sentury.config import settings
    from sentury.main import _robin_config

    account_config.salvar_conta({"id": "minha-openai", "provider": "openai",
                                 "key_env": "MINHA_OPENAI_KEY", "label": "Minha", "paga": True})
    contas = {c["id"]: c for c in catalogo_efetivo(settings, _robin_config).para_painel()["contas"]}

    assert contas["minha-openai"]["declarada"] is True
    assert contas["openai"]["declarada"] is False          # descoberta pelo provedor
    assert contas["openrouter-paga"]["declarada"] is False  # de fabrica, no padrao.yaml
