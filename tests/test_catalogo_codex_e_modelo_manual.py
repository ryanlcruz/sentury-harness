"""O catálogo do Codex é vivo; o ID manual é uma escolha explícita do operador."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from robinbandit.catalog import model_catalog
from robinbandit.providers import codex_provider
from robinbandit import account_config
from sentury import main


@pytest.mark.asyncio
async def test_codex_lista_modelos_do_app_server_em_vez_de_tres_fixos(monkeypatch):
    async def listar(_binary):
        return [
            {"id": "gpt-6-astra", "model": "gpt-6-astra", "displayName": "GPT-6 Astra",
             "inputModalities": ["text", "image"], "hidden": False},
            {"id": "interno", "model": "interno", "hidden": True},
        ]

    monkeypatch.setattr(codex_provider, "listar_modelos_codex", listar)
    config = SimpleNamespace(
        providers={"chatgpt_codex": {"binary": "codex"}},
        provider_models=lambda _key: ["gpt-5.6-luna"],
    )
    catalogo = await model_catalog.fetch_model_catalog(config, "chatgpt_codex", force=True)
    assert catalogo["source"] == "live"
    assert [item["id"] for item in catalogo["models"]] == ["gpt-6-astra"]
    assert "vision" in catalogo["models"][0]["capabilities"]


@pytest.mark.asyncio
async def test_id_manual_exige_escolha_explicita_e_chega_ao_router(monkeypatch):
    async def catalogo(_config, _provider, _settings):
        return {"models": [{"id": "gpt-5.6-luna", "selectable": True, "roles": ["texto"]}]}

    gravados = []
    monkeypatch.setattr(model_catalog, "fetch_model_catalog", catalogo)
    monkeypatch.setattr(account_config, "definir_modelos_de_provedor",
                        lambda _key, models, _role: gravados.extend(models) or models)
    monkeypatch.setattr(main, "_refresh_provider_chains", lambda: None)

    pedido = main.ModelosDoProvedorRequest(models=["gpt-6-astra"])
    with pytest.raises(HTTPException, match="modelos indisponiveis"):
        await main.escolher_modelos_do_provedor("chatgpt_codex", pedido)
    assert gravados == []

    manual = main.ModelosDoProvedorRequest(models=["gpt-6-astra"], allow_unlisted=True)
    resposta = await main.escolher_modelos_do_provedor("chatgpt_codex", manual)
    assert resposta["models"] == ["gpt-6-astra"]
    assert gravados == ["gpt-6-astra"]

    invalido = main.ModelosDoProvedorRequest(models=["modelo com espaços"], allow_unlisted=True)
    with pytest.raises(HTTPException, match="não conter espaços"):
        await main.escolher_modelos_do_provedor("chatgpt_codex", invalido)
