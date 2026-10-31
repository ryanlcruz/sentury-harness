"""O token da API confere em tempo constante e recusa o que não bate."""
import pytest
from fastapi import HTTPException


async def test_token_certo_passa_e_errado_e_recusado(monkeypatch):
    from sentury import main

    monkeypatch.setattr(main.settings, "SENTURY_API_TOKEN", "segredo-de-teste", raising=False)
    assert await main.verify_api_token("Bearer segredo-de-teste") is None
    for errado in ("Bearer segredo-de-test", "Bearer outro", "segredo-de-teste", None):
        with pytest.raises(HTTPException) as erro:
            await main.verify_api_token(errado)
        assert erro.value.status_code == 401


def test_a_comparacao_e_em_tempo_constante():
    import inspect

    from sentury import main

    fonte = inspect.getsource(main.verify_api_token)
    assert "compare_digest" in fonte and "token != " not in fonte
