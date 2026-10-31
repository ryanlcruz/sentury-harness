from unittest.mock import AsyncMock

import pytest

from sentury.residentes.escopo import vestido
from sentury.residentes.manifesto import Manifesto
from sentury.tools import catalog
from sentury.tools.registry import TOOL_REGISTRY


def test_toda_ferramenta_declara_um_destino():
    for nome, meta in TOOL_REGISTRY.items():
        assert meta.get("destino_residente") in {"caixa", "hq", "proibida"}, nome
        assert (meta["destino_residente"] == "caixa") == bool(meta.get("operacao_caixa")), nome


@pytest.mark.parametrize("tool", [n for n, m in TOOL_REGISTRY.items() if m["destino_residente"] == "proibida"] + ["setor.sem_destino"])
async def test_hq_recusa_sem_chamar_codigo_local(tool, monkeypatch):
    monkeypatch.setenv("SENTURY_CAIXA_OBRIGATORIA", "true")
    local = AsyncMock(side_effect=AssertionError("fugiu da caixa"))
    monkeypatch.setattr(catalog, "_executar_local", local)
    with vestido(Manifesto("atlas", "infra", "observar")):
        resposta = await catalog._executar_ferramenta(None, None, tool, {})
    assert resposta["ok"] is False
    assert "recusada" in resposta["erro"]
    assert "Considere" in resposta["erro"]
    local.assert_not_called()


async def test_estado_da_hq_nao_exige_caixa(monkeypatch):
    monkeypatch.setenv("SENTURY_CAIXA_OBRIGATORIA", "true")
    local = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(catalog, "_executar_local", local)
    with vestido(Manifesto("atlas", "infra", "observar")):
        assert await catalog._executar_ferramenta(None, None, "pedir_ao_agente", {}) == {"ok": True}
    local.assert_awaited_once()


async def test_turno_da_pessoa_preserva_ferramenta_local(monkeypatch):
    monkeypatch.setenv("SENTURY_CAIXA_OBRIGATORIA", "true")
    local = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(catalog, "_executar_local", local)
    assert await catalog._executar_ferramenta(None, None, "mapa_do_arquivo", {}) == {"ok": True}
    local.assert_awaited_once()
