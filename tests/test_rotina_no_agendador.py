import json
from httpx import ASGITransport, AsyncClient
from tests.test_rotinas_do_residente import scheduler
from sentury.residentes import rotinas
from sentury.residentes.api_local import router
from fastapi import FastAPI, HTTPException
import pytest
from unittest.mock import AsyncMock


async def test_edita_pedido_e_horario_pelo_endpoint_da_rotina(scheduler):
    criada = await rotinas.criar("atlas", "Pedido antigo", interval_sec=300)
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://teste") as client:
        resposta = await client.patch(f"/sentury/residentes/atlas/rotinas/{criada['id']}",
                                      json={"pedido": "Pedido novo", "cron_expr": "0 10 * * 2"})
    assert resposta.status_code == 200
    assert resposta.json()["residente"] == "atlas"
    assert resposta.json()["prompt"] == "Pedido novo"
    assert resposta.json()["kind"] == "cron"
    assert resposta.json()["interval_sec"] is None
    assert json.loads(scheduler.caminho_local().read_text())[0]["prompt"] == "Pedido novo"


async def test_edicao_nao_muda_dono_e_recusa_horarios_ambiguos(scheduler):
    criada = await rotinas.criar("atlas", "Verifique", interval_sec=300)
    with pytest.raises(ValueError):
        await rotinas.mudar("outro", criada["id"], campos={"pedido": "novo"})
    with pytest.raises(ValueError):
        await rotinas.mudar("atlas", criada["id"], campos={"interval_sec": 500, "cron_expr": "0 9 * * *"})
    assert scheduler.jobs[criada["id"]]["prompt"] == "Verifique"


async def test_lista_inclui_rotinas_da_hq_remota(scheduler, monkeypatch):
    from sentury import main
    from sentury.residentes import cliente
    monkeypatch.setattr(main, "cron_scheduler", scheduler)
    monkeypatch.setattr(cliente, "url_da_hq", lambda: "https://hq.exemplo")
    monkeypatch.setattr(cliente, "listar", AsyncMock(return_value=[{"nome": "atlas"}]))
    rotina = {"id": "remota", "residente": "atlas", "session_id": "agente:atlas"}
    monkeypatch.setattr(cliente, "rotinas", AsyncMock(return_value={"rotinas": [rotina]}))
    listado = await main.cron_list()
    assert rotina in listado["jobs"]
    assert (await main.cron_list(session_id="outra"))["jobs"] == []


async def test_endpoints_genericos_nao_editam_rotina_de_residente(scheduler, monkeypatch):
    from sentury import main
    from sentury.external import agendador
    agendador.registrar(scheduler)
    criada = await rotinas.criar("atlas", "Verifique", interval_sec=300)
    monkeypatch.setattr(main, "cron_scheduler", scheduler)
    for acao in (main.cron_delete, main.cron_activate, main.cron_pause):
        with pytest.raises(HTTPException) as erro:
            await acao(criada["id"])
        assert erro.value.status_code == 409
    with pytest.raises(HTTPException):
        await main.cron_update(criada["id"], main.CronUpdateRequest(prompt="novo", kind="interval", interval_sec=400))
    assert scheduler.jobs[criada["id"]]["prompt"] == "Verifique"
