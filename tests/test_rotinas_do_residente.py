import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from sentury.external import agendador
from sentury.external.cron_scheduler import CronScheduler
from sentury.residentes import registro, rotinas, tarefas, worker
from sentury.residentes.api_local import router


class SemTurnoPrincipal:
    async def handle_message(self, *_):
        pytest.fail("Rotina de residente chamou o Sentury principal")


@pytest_asyncio.fixture
async def scheduler(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.delenv("SENTURY_HQ_URL", raising=False)
    worker.configurar(None)
    registro.criar({"nome": "atlas", "papel": "infraestrutura", "objetivo": "vigiar disco",
                    "ferramentas": ["ler_arquivo"]})
    atual = agendador.atual()
    scheduler = CronScheduler(SemTurnoPrincipal(), None,
                              SimpleNamespace(SESSION_TTL_SEC=1800, SENTURY_TIMEZONE="America/Sao_Paulo"))
    agendador.registrar(scheduler)
    yield scheduler
    await scheduler.shutdown()
    agendador.registrar(atual)
    worker.configurar(None)


async def test_disparo_enfileira_com_origem_da_rotina(scheduler):
    criada = await rotinas.criar("atlas", "Verifique o disco", cron_expr="0 9 * * 1")
    await scheduler._execute(scheduler.jobs[criada["id"]])
    fila = tarefas.listar("atlas")
    assert len(fila) == 1
    assert fila[0].pedido == "Verifique o disco"
    assert fila[0].origem == f"rotina:{criada['id']}"
    assert fila[0].estado == tarefas.NA_FILA
    assert criada["rotulo"] == "Toda segunda às 9h"
    assert scheduler.jobs[criada["id"]]["run_count"] == 1


@pytest.mark.parametrize("estado", ["pausar", "aposentar"])
async def test_residente_parado_nao_enfileira(scheduler, estado):
    criada = await rotinas.criar("atlas", "Verifique", interval_sec=300)
    getattr(registro, estado)("atlas")
    await scheduler._execute(scheduler.jobs[criada["id"]])
    assert tarefas.listar("atlas") == []
    assert scheduler.jobs[criada["id"]]["motivo"]
    assert rotinas.listar("atlas")[0]["bloqueio"]


async def test_apagar_tira_do_agendador_e_do_disco(scheduler):
    criada = await rotinas.criar("atlas", "Verifique", interval_sec=300)
    assert json.loads(scheduler.caminho_local().read_text())[0]["residente"] == "atlas"
    await rotinas.apagar("atlas", criada["id"])
    assert scheduler.jobs == {}
    assert criada["id"] not in scheduler._tasks
    assert json.loads(scheduler.caminho_local().read_text()) == []


async def test_reinicio_preserva_destino_e_pausa(scheduler):
    criada = await rotinas.criar("atlas", "Verifique", interval_sec=300)
    await rotinas.mudar("atlas", criada["id"], False)
    await scheduler.shutdown()
    scheduler.jobs.clear()
    await scheduler.load_persisted()
    job = scheduler.jobs[criada["id"]]
    assert job["residente"] == "atlas"
    assert job["residente_criado_em"] == registro.carregar("atlas").criado_em
    assert not job["active"]
    assert rotinas.listar("atlas")[0]["proxima_execucao"] is None


async def test_nao_entrega_rotina_do_aposentado_ao_nome_reutilizado(scheduler):
    criada = await rotinas.criar("atlas", "Verifique", interval_sec=300)
    registro.aposentar("atlas")
    registro.criar({"nome": "atlas", "papel": "outro", "objetivo": "outro",
                    "ferramentas": ["ler_arquivo"]})
    await scheduler._execute(scheduler.jobs[criada["id"]])
    assert tarefas.listar("atlas") == []


async def test_endpoints_criar_pausar_retomar_apagar(scheduler):
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://teste") as cliente:
        criado = await cliente.post("/sentury/residentes/atlas/rotinas",
                                    json={"pedido": "Verifique", "run_at": "2099-10-02T09:00"})
        assert criado.status_code == 201
        rotina = criado.json()
        assert rotina["kind"] == "once"
        path = f"/sentury/residentes/atlas/rotinas/{rotina['id']}"
        assert (await cliente.patch(path, json={"ativa": False})).json()["active"] is False
        assert (await cliente.patch(path, json={"ativa": True})).json()["active"] is True
        assert (await cliente.get("/sentury/residentes/atlas/rotinas")).json()["rotinas"][0]["id"] == rotina["id"]
        assert (await cliente.delete(path)).status_code == 200
        assert (await cliente.get("/sentury/residentes/atlas/rotinas")).json()["rotinas"] == []


async def test_agenda_de_outro_residente_nao_pode_ser_apagada(scheduler):
    criada = await rotinas.criar("atlas", "Verifique", interval_sec=300)
    with pytest.raises(ValueError, match="não encontrada"):
        await rotinas.apagar("outro", criada["id"])
    assert criada["id"] in scheduler.jobs


async def test_agenda_do_residente_fica_em_nome_dele_e_dispara_pela_fila(scheduler):
    """O residente que agenda pela ferramenta cria uma rotina dele: aparece com o
    dono na tela e, ao disparar, entra na fila dele, nunca no turno do Sentury."""
    from sentury.residentes import escopo, hq

    agente = registro.carregar("atlas")
    with escopo.vestido(agente, None):
        criado = agendador.agendar(session_id=hq.sessao_do("atlas"), user_id="hq",
                                   tarefa="Verifique o disco", cron="0 9 * * 1")
    assert criado["ok"] and scheduler.jobs[criado["id"]]["residente"] == "atlas"
    await scheduler._execute(scheduler.jobs[criado["id"]])
    assert [t.pedido for t in tarefas.listar("atlas")] == ["Verifique o disco"]


async def test_residente_nao_cancela_agendamento_que_nao_e_dele(scheduler):
    from sentury.residentes import escopo

    do_sentury = agendador.agendar(session_id="conversa", user_id="pessoa", tarefa="Resumo do dia",
                                   cron="0 18 * * *")
    with escopo.vestido(registro.carregar("atlas"), None):
        recusa = agendador.cancelar(do_sentury["id"])
    assert not recusa["ok"] and do_sentury["id"] in scheduler.jobs
    assert agendador.cancelar(do_sentury["id"])["ok"]
