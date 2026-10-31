"""O cofre guarda a chave e nunca a devolve.

Cada teste aqui prova uma das três regras do módulo: valor não sai, só nome
conhecido entra, e o cofre vence o ambiente (com a origem visível).
"""
import json
import os

import pytest

from robinbandit import accounts, secrets as cofre


@pytest.fixture(autouse=True)
def cofre_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_VAULT_PATH", str(tmp_path / "cofre.json"))
    yield


def test_guarda_e_le():
    cofre.guardar("GROQ_API_KEY", "gsk_chave_secreta_1234")
    assert cofre.ler("GROQ_API_KEY") == "gsk_chave_secreta_1234"


def test_so_variavel_conhecida_entra():
    with pytest.raises(ValueError, match="não pertence"):
        cofre.guardar("PATH", "/etc/evil", permitidos=["GROQ_API_KEY"])
    assert cofre.ler("PATH") == ""


def test_valor_vazio_nao_e_forma_de_remover():
    with pytest.raises(ValueError, match="vazio"):
        cofre.guardar("GROQ_API_KEY", "   ")


def test_dica_nunca_entrega_chave_curta():
    assert cofre.dica("abc") == "..."          # curta demais: nada de sufixo
    assert cofre.dica("gsk_1234567890ab") == "...90ab"
    assert cofre.dica("") == ""


def test_varias_chaves_na_mesma_conta():
    """O rotador alterna entre chaves da mesma conta quando uma bate a cota."""
    cofre.guardar("GROQ_API_KEY", "gsk_primeira_chave_aa")
    cofre.guardar("GROQ_API_KEY", "gsk_segunda_chave_bb", adicionar=True)
    assert cofre.listar("GROQ_API_KEY") == ["gsk_primeira_chave_aa", "gsk_segunda_chave_bb"]
    # CSV é o formato que o parse_keys/KeyRotator consome.
    assert cofre.ler("GROQ_API_KEY") == "gsk_primeira_chave_aa,gsk_segunda_chave_bb"


def test_adicionar_nao_apaga_o_que_o_ambiente_tinha():
    # Sem a semente, somar a terceira chave a uma variável que vem do .env com
    # duas deixaria a conta com uma só, em silêncio.
    cofre.guardar("GROQ_API_KEY", "gsk_nova_chave_ccc",
                  adicionar=True, semente="gsk_do_env_1111,gsk_do_env_2222")
    assert cofre.listar("GROQ_API_KEY") == [
        "gsk_do_env_1111", "gsk_do_env_2222", "gsk_nova_chave_ccc"]


def test_chave_repetida_nao_entra_duas_vezes():
    cofre.guardar("GROQ_API_KEY", "gsk_mesma_chave_aaa")
    cofre.guardar("GROQ_API_KEY", "gsk_mesma_chave_aaa", adicionar=True)
    assert cofre.listar("GROQ_API_KEY") == ["gsk_mesma_chave_aaa"]


def test_remover_uma_chave_por_indice():
    cofre.guardar("GROQ_API_KEY", "gsk_primeira_chave_aa")
    cofre.guardar("GROQ_API_KEY", "gsk_segunda_chave_bb", adicionar=True)
    assert cofre.remover_chave("GROQ_API_KEY", 0) is True
    assert cofre.listar("GROQ_API_KEY") == ["gsk_segunda_chave_bb"]
    assert cofre.remover_chave("GROQ_API_KEY", 9) is False


def test_formato_antigo_com_csv_continua_lendo():
    # Cofres gravados antes guardavam uma string; quebrar isso na leitura
    # invalidaria configuração existente.
    cofre.caminho_do_cofre().parent.mkdir(parents=True, exist_ok=True)
    cofre.caminho_do_cofre().write_text(
        json.dumps({"GROQ_API_KEY": "gsk_uma_chave_11,gsk_outra_chave_22"}), encoding="utf-8")
    assert cofre.listar("GROQ_API_KEY") == ["gsk_uma_chave_11", "gsk_outra_chave_22"]


def test_situacao_lista_cada_chave():
    cofre.guardar("GROQ_API_KEY", "gsk_primeira_chave_aa")
    cofre.guardar("GROQ_API_KEY", "gsk_segunda_chave_bb", adicionar=True)
    s = cofre.situacao("GROQ_API_KEY")
    assert [k["dica"] for k in s["chaves"]] == ["...e_aa", "...e_bb"]


def test_situacao_diz_a_origem():
    assert cofre.situacao("GROQ_API_KEY", "")["configurada"] is False
    assert cofre.situacao("GROQ_API_KEY", "do_ambiente_x")["origem"] == "ambiente"
    cofre.guardar("GROQ_API_KEY", "gsk_do_cofre_98765")
    s = cofre.situacao("GROQ_API_KEY", "do_ambiente_x")
    assert s["origem"] == "cofre" and s["dica"] == "...8765"


def test_remover_volta_para_o_ambiente():
    cofre.guardar("GROQ_API_KEY", "gsk_do_cofre_98765")
    assert cofre.remover("GROQ_API_KEY") is True
    assert cofre.remover("GROQ_API_KEY") is False
    assert cofre.situacao("GROQ_API_KEY", "do_ambiente_x")["origem"] == "ambiente"


def test_cofre_corrompido_nao_apaga_segredos():
    cofre.caminho_do_cofre().parent.mkdir(parents=True, exist_ok=True)
    cofre.caminho_do_cofre().write_text("{ isto nao e json", encoding="utf-8")
    with pytest.raises(cofre.CofreInvalido, match="preservado"):
        cofre.ler("GROQ_API_KEY")
    with pytest.raises(cofre.CofreInvalido):
        cofre.guardar("GROQ_API_KEY", "nova")
    assert cofre.caminho_do_cofre().read_text(encoding="utf-8") == "{ isto nao e json"


def test_conta_no_painel_nunca_carrega_o_valor():
    cofre.guardar("GROQ_API_KEY", "gsk_valor_ultrassecreto")
    conta = accounts.Conta(id="groq", provider="groq", key_env="GROQ_API_KEY", label="Groq")
    painel = conta.para_painel()
    serializado = json.dumps(painel)
    assert "ultrassecreto" not in serializado
    assert painel["configurada"] is True and painel["origem"] == "cofre"
    assert conta.resolver_chave() == "gsk_valor_ultrassecreto"


def test_cofre_vence_o_ambiente(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "do_ambiente")
    assert accounts._ler_segredo("GROQ_API_KEY") == "do_ambiente"
    cofre.guardar("GROQ_API_KEY", "do_cofre_mais_recente")
    assert accounts._ler_segredo("GROQ_API_KEY") == "do_cofre_mais_recente"


def test_lista_branca_cobre_os_provedores_e_os_tiers():
    from sentury.config import settings

    permitidos = accounts.variaveis_conhecidas(settings)
    assert "GROQ_API_KEY" in permitidos
    # `API_KEY_ULTRA_MAX` nao existe mais: nunca chegou a ser uma chave sua,
    # caia em `API_KEY_ULTRA` pelo fallback. Reforcado e Dedicado sao a mesma
    # conta paga do OpenRouter com modelos diferentes.
    assert "API_KEY_ULTRA" in permitidos
    assert "PATH" not in permitidos


def test_arquivo_do_cofre_nao_fica_legivel_para_todos():
    cofre.guardar("GROQ_API_KEY", "gsk_qualquer_coisa_a")
    modo = os.stat(cofre.caminho_do_cofre()).st_mode & 0o077
    # No Windows o chmod é aproximado; a asserção vale onde o SO honra o bit.
    if os.name != "nt":
        assert modo == 0
