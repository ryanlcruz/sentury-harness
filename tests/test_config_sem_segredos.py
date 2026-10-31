"""Representar as configurações num erro não revela as credenciais."""
from sentury.config import Settings


def test_repr_e_str_nao_expoem_chaves_e_nao_alteram_os_valores():
    configuracao = Settings(_env_file=None, OPENROUTER_API_KEY="chave-ficticia-da-bancada", TELEGRAM_TOKEN="token-ficticio-da-bancada")
    for texto in (repr(configuracao), str(configuracao)):
        assert "chave-ficticia-da-bancada" not in texto
        assert "token-ficticio-da-bancada" not in texto
        assert "OPENROUTER_API_KEY" not in texto
        assert "TELEGRAM_TOKEN" not in texto
        assert "APP_NAME" in texto
    assert configuracao.OPENROUTER_API_KEY == "chave-ficticia-da-bancada"
    assert configuracao.TELEGRAM_TOKEN == "token-ficticio-da-bancada"
