"""O painel acrescenta contas; o ambiente continua sendo o padrão.

A regra que estes testes protegem: declarar uma conta no painel NUNCA apaga o
que o `.env` já configurou. Quem nunca abriu o painel não pode perder nada ao
abri-lo uma vez.
"""
import pytest

from sentury.config import settings
from robinbandit import account_config as contas_config, accounts


@pytest.fixture(autouse=True)
def config_isolada(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_ACCOUNTS_PATH", str(tmp_path / "contas.json"))
    monkeypatch.setenv("SENTURY_VAULT_PATH", str(tmp_path / "cofre.json"))
    yield


# O catalogo declara uma conta de fabrica: a paga do OpenRouter, uma chave so.
DE_FABRICA = {"openrouter-paga"}


def test_config_vazia_nao_muda_nada():
    """Sem nada declarado pelo painel, o efetivo e o ambiente: mais o que o
    catalogo ja declara, que nao e "mudanca do usuario"."""
    do_ambiente = {c.id for c in accounts.descobrir_do_ambiente(settings).listar()}
    efetivo = {c.id for c in accounts.catalogo_efetivo(settings).listar()}
    assert efetivo - DE_FABRICA == do_ambiente - DE_FABRICA


def test_conta_extra_soma_e_nao_substitui():
    contas_config.salvar_conta({
        "id": "groq-paga", "provider": "groq", "key_env": "GROQ_API_KEY_2",
        "label": "Groq (conta paga)", "models": ["llama-3.3-70b-versatile"], "paga": True,
    })
    cat = accounts.catalogo_efetivo(settings)
    ids = {c.id for c in cat.listar()}
    assert "groq-paga" in ids
    assert "groq" in ids, "a conta descoberta do ambiente nao pode sumir"
    assert len(cat.do_provedor("groq")) == 2


def test_key_env_da_conta_nova_entra_na_lista_branca_do_cofre():
    contas_config.salvar_conta({
        "id": "groq-paga", "provider": "groq", "key_env": "GROQ_API_KEY_2",
    })
    assert "GROQ_API_KEY_2" in accounts.variaveis_conhecidas(settings)


def test_key_env_invalida_e_recusada():
    # O nome vira variável de ambiente e entra na lista branca do cofre.
    with pytest.raises(ValueError, match="letras, números e underscore"):
        contas_config.salvar_conta({"id": "x", "provider": "groq", "key_env": "PATH; rm -rf"})


def test_tier_aponta_para_conta_descoberta_do_ambiente():
    contas_config.apontar_tier("ultra_max", "groq")
    cat = accounts.catalogo_efetivo(settings)
    conta = cat.conta_do_tier("ultra_max")
    assert conta is not None and conta.id == "groq"


def test_tier_vazio_volta_ao_padrao():
    contas_config.apontar_tier("ultra_max", "groq")
    contas_config.apontar_tier("ultra_max", "")
    cat = accounts.catalogo_efetivo(settings)
    # Volta para o padrao de fabrica, que hoje e NENHUMA conta: o catalogo
    # declara a conta paga mas nao aponta tier nenhum para ela: Reforcado e
    # Dedicado so ficam ativos depois que o usuario escolhe conta e modelo.
    # Apontar de fabrica gastaria credito pago sem ninguem ter pedido.
    assert cat.conta_do_tier("ultra_max") is None


def test_tier_para_conta_inexistente_ensina_o_erro():
    with pytest.raises(ValueError, match="não existe"):
        contas_config.apontar_tier("ultra", "nao-existe", ids_validos=["groq", "gemini"])


def test_tier_desconhecido_e_recusado():
    with pytest.raises(ValueError, match="não existe"):
        contas_config.apontar_tier("turbo", "groq")


def test_remover_conta_limpa_o_tier_orfao():
    contas_config.salvar_conta({"id": "groq-paga", "provider": "groq", "key_env": "GROQ_API_KEY_2"})
    contas_config.apontar_tier("ultra", "groq-paga")
    assert contas_config.remover_conta("groq-paga") is True
    # Tier apontando pro nada faria o catálogo inteiro recusar carregar.
    cat = accounts.catalogo_efetivo(settings)
    # Tier orfao vira tier sem conta, nao catalogo recusado.
    assert cat.conta_do_tier("ultra") is None


def test_config_corrompida_deixa_o_ambiente_seguir():
    caminho = contas_config.caminho_da_config()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("{ nao e json", encoding="utf-8")
    ids = {c.id for c in accounts.catalogo_efetivo(settings).listar()}
    assert "groq" in ids


def test_conta_declarada_sobrescreve_os_modelos_da_descoberta():
    contas_config.salvar_conta({
        "id": "groq", "provider": "groq", "key_env": "GROQ_API_KEY",
        "label": "Groq", "models": ["so-este-modelo"],
    })
    cat = accounts.catalogo_efetivo(settings)
    assert cat.obter("groq").models == ["so-este-modelo"]
