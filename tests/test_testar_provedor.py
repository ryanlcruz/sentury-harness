"""Quem acabou de colar a chave sabe na hora se ela funciona."""
import pytest
from fastapi import HTTPException


class _Roteador:
    def __init__(self):
        self.sucessos, self.falhas = [], []

    def record_success(self, nome, ms, model=None):
        self.sucessos.append(nome)

    def record_failure(self, nome, tipo, detail=""):
        self.falhas.append((nome, tipo))

    def record_quota(self, *a):
        pass


class _Provedor:
    def __init__(self, nome, erro=None):
        self.name, self._erro, self.last_model = nome, erro, "modelo"

    async def complete(self, messages, **kwargs):
        if self._erro:
            raise self._erro
        return "pong"


class _Robin:
    def __init__(self):
        self.router = _Roteador()


@pytest.fixture
def api(monkeypatch):
    from sentury import main

    robin = _Robin()
    monkeypatch.setattr(main, "robin", robin)
    monkeypatch.setattr(main, "_provider_set", {
        "boa": _Provedor("boa"),
        "recusada": _Provedor("recusada", RuntimeError("401 Unauthorized: invalid api key")),
        "fallback": _Provedor("fallback"),
    })
    return main, robin.router


async def test_chave_que_funciona_responde_ok_e_entra_no_roteador(api):
    main, roteador = api
    resultado = await main.testar_provedor("boa", None)
    assert resultado["ok"] is True and "ms" in resultado
    assert roteador.sucessos == ["boa"]


async def test_chave_recusada_diz_o_tipo_da_falha(api):
    main, roteador = api
    resultado = await main.testar_provedor("recusada", None)
    assert resultado["ok"] is False and resultado["tipo"]
    assert roteador.falhas and roteador.falhas[0][0] == "recusada"


@pytest.mark.parametrize("chave", ["sem-chave", "fallback"])
async def test_provedor_sem_chave_ou_de_demonstracao_nao_testa(api, chave):
    main, _ = api
    with pytest.raises(HTTPException) as erro:
        await main.testar_provedor(chave, None)
    assert erro.value.status_code == 404
