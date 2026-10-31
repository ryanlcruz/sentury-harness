"""Catalogo de contas: qual conta serve cada tier.

A decisao de seguranca no centro: a conta aponta pro NOME da variavel de
ambiente, nunca guarda o valor. Assim o catalogo e configuracao comum (vai pro
banco, pro painel, pro YAML do tenant) e o segredo fica onde segredo deve ficar.
"""
import pytest

from robinbandit.accounts import CatalogoDeContas, Conta, carregar_catalogo


def _bruto():
    return {
        "contas": [
            {"id": "or-paga", "provider": "openrouter", "key_env": "OR_KEY_PAGA",
             "models": ["deepseek/deepseek-v4-pro"], "label": "OpenRouter (creditos)", "paga": True},
            {"id": "or-free", "provider": "openrouter", "key_env": "OR_KEY_FREE",
             "models": ["meta-llama/llama-3.3-70b-instruct:free"]},
            {"id": "groq-1", "provider": "groq", "key_env": "GROQ_KEY_1"},
        ],
        "tiers": {"ultra_max": "or-paga", "ultra": "or-free"},
    }


def test_a_chave_nunca_entra_no_objeto(monkeypatch):
    """O valor e lido do ambiente NA HORA do uso: nao vaza em log, repr,
    serializacao nem no payload do painel."""
    monkeypatch.setenv("OR_KEY_PAGA", "sk-segredo-de-verdade")
    c = carregar_catalogo(_bruto()).obter("or-paga")
    assert c.resolver_chave() == "sk-segredo-de-verdade"
    assert "sk-segredo" not in repr(c)
    assert "sk-segredo" not in str(c.para_painel())
    assert c.para_painel()["key_env"] == "OR_KEY_PAGA"   # o NOME ajuda a debugar


def test_painel_diz_se_esta_configurada_sem_mostrar_o_valor(monkeypatch):
    monkeypatch.delenv("OR_KEY_FREE", raising=False)
    monkeypatch.setenv("OR_KEY_PAGA", "x")
    cat = carregar_catalogo(_bruto())
    p = {c["id"]: c for c in cat.para_painel()["contas"]}
    assert p["or-paga"]["configurada"] is True
    assert p["or-free"]["configurada"] is False


def test_escolhe_qual_conta_serve_cada_tier():
    """O caso que motivou: duas contas do MESMO provedor, e a paga fica
    reservada pro tier caro."""
    cat = carregar_catalogo(_bruto())
    assert cat.conta_do_tier("ultra_max").id == "or-paga"
    assert cat.conta_do_tier("ultra").id == "or-free"
    assert cat.conta_do_tier("inexistente") is None


def test_varias_contas_do_mesmo_provedor():
    cat = carregar_catalogo(_bruto())
    assert {c.id for c in cat.do_provedor("openrouter")} == {"or-paga", "or-free"}


def test_apontar_tier_pra_conta_que_nao_existe_e_erro():
    """Apontar pro nada deixaria o tier caindo no fallback em SILENCIO."""
    cat = carregar_catalogo(_bruto())
    with pytest.raises(ValueError) as e:
        cat.apontar_tier("ultra_max", "conta-fantasma")
    assert "or-paga" in str(e.value)


def test_config_invalida_levanta_em_vez_de_virar_catalogo_vazio():
    """Catalogo vazio em silencio faria todo tier cair no fallback sem
    ninguem perceber."""
    with pytest.raises(ValueError):
        carregar_catalogo({"contas": [{"provider": "groq"}]})          # sem id
    with pytest.raises(ValueError):
        carregar_catalogo({"contas": [{"id": "a", "provider": "groq"}]})  # sem key_env
    with pytest.raises(ValueError):
        carregar_catalogo({"contas": [
            {"id": "a", "provider": "groq", "key_env": "K"},
            {"id": "a", "provider": "groq", "key_env": "K2"},
        ]})
    with pytest.raises(ValueError):
        carregar_catalogo({"contas": [], "tiers": {"ultra": "nao-existe"}})


def test_sem_catalogo_nao_quebra():
    """Ausente = comportamento antigo por env."""
    assert carregar_catalogo(None).listar() == []
    assert carregar_catalogo(None).conta_do_tier("ultra") is None


def test_marca_conta_paga_pra_nao_gastar_em_tarefa_lateral():
    cat = carregar_catalogo(_bruto())
    assert cat.obter("or-paga").paga is True
    assert cat.obter("or-free").paga is False


# --- descoberta do ambiente ---

def test_descobre_as_chaves_que_o_usuario_JA_tem():
    """Sem isto o painel pedia pra reescrever a mao, em JSON, uma configuracao
    que ja existe -- inutil. E 'trazer pro cofre' e seguro porque NADA de
    segredo se move: a conta guarda o NOME da variavel."""
    from sentury.config import settings
    from robinbandit.accounts import catalogo_efetivo

    cat = catalogo_efetivo(settings)
    ids = {c.id for c in cat.listar()}
    # `ultra`/`ultra_max` sairam daqui: nao eram contas descobertas do
    # ambiente, eram o mesmo OpenRouter com outra chave. Viraram uma conta
    # paga declarada, `openrouter-paga`.
    assert {"groq", "gemini", "openrouter", "openrouter-paga"} <= ids
    assert cat.obter("groq").key_env == "GROQ_API_KEY"


def test_le_o_segredo_do_settings_nao_so_do_environ(monkeypatch):
    """As chaves vem do .env pelo pydantic, que NAO exporta pro os.environ --
    procurar so no ambiente encontrava zero conta configurada."""
    from robinbandit.accounts import Conta, vincular_fonte

    class _S:
        MINHA_CHAVE = "valor-do-env-file"

    monkeypatch.delenv("MINHA_CHAVE", raising=False)
    vincular_fonte(_S())
    c = Conta(id="x", provider="p", key_env="MINHA_CHAVE")
    assert c.configurada is True
    assert c.resolver_chave() == "valor-do-env-file"
    assert "valor-do-env" not in str(c.para_painel())


def test_ambiente_tem_precedencia_sobre_o_settings(monkeypatch):
    """No deploy quem manda e a variavel real do processo."""
    from robinbandit.accounts import Conta, vincular_fonte

    class _S:
        K = "do-arquivo"

    vincular_fonte(_S())
    monkeypatch.setenv("K", "do-processo")
    assert Conta(id="x", provider="p", key_env="K").resolver_chave() == "do-processo"


def test_a_conta_paga_serve_os_dois_modos_pesados():
    """Sem isso nao da pra dizer "a conta paga serve a Super Maxima".

    Reforcado e Dedicado eram DOIS provedores, `ultra` e `ultra_max`, e nunca
    foram dois: mesmo endpoint do OpenRouter, a mesma chave (o segundo caia no
    primeiro pelo fallback) e so o modelo mudando. Viraram uma conta paga do
    OpenRouter com dois modelos, e o tier escolhe qual.
    """
    from sentury.config import settings
    from robinbandit.accounts import catalogo_efetivo

    cat = catalogo_efetivo(settings)
    # A conta existe declarada, mas nenhum tier aponta para ela de fabrica:
    # gastar credito pago sem o usuario ter escolhido seria decidir por ele.
    paga = cat.obter("openrouter-paga")
    assert paga is not None and paga.provider == "openrouter" and paga.paga is True
    for tier in ("ultra", "ultra_max"):
        assert cat.conta_do_tier(tier) is None, tier
