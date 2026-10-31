"""Agendador do Sentury: parser de linguagem natural (once, intervalo e cron
ancorado), CRUD de jobs e entrega no feed do painel. Sem Redis nos fakes,
a persistência vira no-op."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import sentury.external.cron_scheduler as cron_scheduler
from sentury.external.cron_scheduler import CronScheduler, parse_cron_command


class _FakeStore:
    async def get(self, sid):
        return None

    async def set(self, sid, value, ttl=None):
        pass


class _FakeOrch:
    async def handle_message(self, state, msg):
        return {"message": f"resposta para: {msg}", "attachment": None}


class _FakeSettings:
    SESSION_TTL_SEC = 1800
    SENTURY_TIMEZONE = "America/Sao_Paulo"


def _sched():
    return CronScheduler(_FakeOrch(), _FakeStore(), _FakeSettings())


def test_parse_interval_and_cron():
    assert parse_cron_command("a cada 5 minutos me informe o Medida") == {"interval_sec": 300, "prompt": "me informe o Medida"}
    assert parse_cron_command("todo dia às 11h me informe o Medida") == {"cron_expr": "0 11 * * *", "prompt": "me informe o Medida"}
    assert parse_cron_command("a cada 30s Medida geral") == {"interval_sec": 30, "prompt": "Medida geral"}
    assert parse_cron_command("me fala qualquer coisa") is None


def test_parse_disparo_unico_relativo_e_absoluto():
    assert parse_cron_command("daqui a 30 minutos me lembre da reuniao") == {
        "kind": "once", "delay_sec": 1800, "prompt": "me lembre da reuniao",
    }
    assert parse_cron_command("em 2026-09-24T10:30:00-03:00 revisar o relatorio") == {
        "kind": "once", "run_at": "2026-09-24T10:30:00-03:00",
        "prompt": "revisar o relatorio",
    }


async def test_add_list_remove():
    s = _sched()
    job = s.add_job("sess1", "u", "me informe o Medida", interval_sec=300, persist=False)
    assert job["id"] and job["kind"] == "interval"
    assert len(s.list_jobs("sess1")) == 1
    assert s.list_jobs("outra_sessao") == []
    assert s.remove_job(job["id"]) is True
    assert s.list_jobs("sess1") == []
    assert s.remove_job("naoexiste") is False
    await s.shutdown()


async def test_min_interval_enforced():
    s = _sched()
    job = s.add_job("s", "u", "x", interval_sec=5, persist=False)  # abaixo do piso de 30s
    assert job["interval_sec"] == 30
    await s.shutdown()


async def test_cron_kind_when_expr_given():
    s = _sched()
    job = s.add_job("s", "u", "Medida", cron_expr="0 11 * * *", persist=False)
    assert job["kind"] == "cron"
    assert job["cron_expr"] == "0 11 * * *"
    await s.shutdown()


async def test_disparo_unico_usa_fuso_configurado_e_some_depois_de_rodar(monkeypatch):
    s = _sched()
    fixed = datetime(2026, 9, 23, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    monkeypatch.setattr(s, "_now", lambda: fixed)
    publico = s.add_once_job(
        "s", "u", "lembrar", run_at=fixed + timedelta(minutes=2),
        persist=False, active=False,
    )
    job_id = publico["id"]
    assert publico["kind"] == "once"
    assert publico["run_at"].endswith("-03:00")
    assert s._next_delay(s.jobs[job_id]) == 120

    sleeps = []

    async def sem_esperar(delay):
        sleeps.append(delay)

    monkeypatch.setattr(cron_scheduler.asyncio, "sleep", sem_esperar)
    s.jobs[job_id]["active"] = True
    await s._run_loop(job_id)

    assert sleeps == [120]
    assert job_id not in s.jobs
    assert len(s.get_feed("s")) == 1
    await s.shutdown()


def test_cron_diario_calcula_no_fuso_do_usuario(monkeypatch):
    s = _sched()
    fixed = datetime(2026, 9, 23, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    monkeypatch.setattr(s, "_now", lambda: fixed)
    job = {"kind": "cron", "cron_expr": "0 8 * * *"}
    assert s._next_delay(job) == 22 * 3600


async def test_agendamento_pendente_so_roda_depois_da_aprovacao():
    s = _sched()
    job = s.add_job(
        "s", "u", "rotina", cron_expr="0 8 * * 1", persist=False,
        workflow="rotina", active=False,
    )
    assert job["active"] is False
    assert job["id"] not in s._tasks

    ativo = s.set_active(job["id"], True)
    assert ativo["active"] is True
    assert job["id"] in s._tasks

    pausado = s.set_active(job["id"], False)
    assert pausado["active"] is False
    assert job["id"] not in s._tasks
    await s.shutdown()


async def test_agendamento_pendente_sobrevive_na_persistencia(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    s = _sched()
    job = s.add_job(
        "s", "u", "rotina", cron_expr="0 8 * * 1", persist=False,
        workflow="rotina", active=False,
    )

    await s._persist()

    guardados = s._ler_local()
    assert [item["id"] for item in guardados] == [job["id"]]
    assert guardados[0]["active"] is False
    await s.shutdown()


async def test_edita_prompt_dias_horario_e_intervalo_sem_trocar_id():
    s = _sched()
    job = s.add_job("s", "u", "primeiro prompt", cron_expr="0 8 * * 1", persist=False)
    editado = s.update_job(
        job["id"], prompt="prompt novo", kind="cron", cron_expr="30 14 * * 2,4",
    )
    assert editado["id"] == job["id"]
    assert editado["prompt"] == "prompt novo"
    assert editado["cron_expr"] == "30 14 * * 2,4"

    editado = s.update_job(job["id"], prompt="por intervalo", kind="interval", interval_sec=120)
    assert editado["kind"] == "interval"
    assert editado["interval_sec"] == 120
    assert editado["cron_expr"] is None
    await s.shutdown()


async def test_edicao_recusa_prompt_vazio_e_cron_invalido():
    s = _sched()
    job = s.add_job("s", "u", "x", cron_expr="0 8 * * 1", persist=False)
    with pytest.raises(ValueError, match="prompt"):
        s.update_job(job["id"], prompt="", kind="cron", cron_expr="0 8 * * 1")
    with pytest.raises(ValueError, match="cron"):
        s.update_job(job["id"], prompt="x", kind="cron", cron_expr="nao e cron")
    await s.shutdown()


async def test_edita_alerta_sem_transformar_em_cron(setor_teste):
    s = _sched()
    job = s.add_alert_job("s", "u", "medida", "<", 20, interval_sec=120, persist=False)
    editado = s.update_job(
        job["id"], prompt="Medida crítico", kind="alert", interval_sec=300,
        metric="medida", op="<", threshold=10,
    )
    assert editado["kind"] == "alert"
    assert editado["threshold"] == 10
    assert editado["interval_sec"] == 300
    await s.shutdown()


def test_parseia_rotina_semanal_em_portugues():
    assert parse_cron_command("toda segunda-feira às 8h buscar vagas") == {
        "cron_expr": "0 8 * * 1", "prompt": "buscar vagas",
    }


def test_simple_cron_delay_without_croniter(monkeypatch):
    monkeypatch.setattr(cron_scheduler, "_HAS_CRONITER", False)
    delay = cron_scheduler._simple_cron_delay("0 11 * * *")
    assert delay is not None
    assert 0 < delay <= 86400


async def test_execute_posts_to_feed():
    s = _sched()
    job = s.add_job("sess1", "u", "me informe o Medida", interval_sec=300, persist=False)
    await s._execute(s.jobs[job["id"]])
    feed = s.get_feed("sess1")
    assert len(feed) == 1
    assert "me informe o Medida" in feed[0]["message"]
    assert s.jobs[job["id"]]["run_count"] == 1
    # o "since" filtra itens antigos
    assert s.get_feed("sess1", since=feed[0]["ts"] + 1) == []
    await s.shutdown()


async def test_workflow_materializa_plano_e_so_muda_de_sessao_se_a_origem_sumiu(tmp_path, monkeypatch):
    from sentury.memory import plano, workflow

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setattr(workflow, "raiz_dos_workflows", lambda trabalho=None: tmp_path / "workflows")
    monkeypatch.setattr(plano, "raiz_dos_planos", lambda trabalho=None: tmp_path / "planos")
    workflow.criar("vagas", "acompanhar", "0 8 * * 1", ["Buscar", "Atualizar"])

    class IndiceSemOrigem:
        def __init__(self):
            self.lembrada = None

        async def load(self, user_id, session_id):
            return None

        async def remember(self, state, title=None):
            self.lembrada = (state.session_id, title)

    indice = IndiceSemOrigem()
    s = CronScheduler(_FakeOrch(), _FakeStore(), _FakeSettings(), session_index=indice)
    publico = s.add_job(
        "origem", "u", "Execute o workflow 'vagas'.", cron_expr="0 8 * * 1",
        workflow="vagas", persist=False,
    )
    await s._execute(s.jobs[publico["id"]])

    nova = s.jobs[publico["id"]]["session_id"]
    assert nova.startswith("cron-") and nova != "origem"
    assert indice.lembrada == (nova, "Workflow: vagas")
    assert list((tmp_path / "planos").glob("*/tarefas.md"))
    assert workflow.resumo("vagas")["total_de_execucoes"] == 1
    assert len(s.get_feed(nova)) == 1
    await s.shutdown()


# --- Alerta por limiar (cron reativo) ---
from sentury.external.cron_scheduler import parse_alert_command
from tests.fixtures.setor_teste.dados import StoreTeste


def test_parse_alert(setor_teste):
    assert parse_alert_command("me avise se a medida cair abaixo de 50%") == {"metric": "medida", "op": "<", "threshold": 50.0, "interval_sec": 120}
    assert parse_alert_command("Medida abaixo de -40")["op"] == "<"
    assert parse_alert_command("medida acima de 45%")["op"] == ">"
    assert parse_alert_command("qualquer coisa") is None


class _Orch:
    store = StoreTeste()


async def test_check_alert_da_medida(setor_teste):
    s = CronScheduler(_Orch(), _FakeStore(), _FakeSettings())
    sla = await s._check_alert({"metric": "medida", "op": "<", "threshold": 60})
    assert isinstance(sla, list) and all("%" in b for b in sla)
    medida = await s._check_alert({"metric": "medida", "op": "<", "threshold": 100})  # sempre abaixo de 100
    assert medida and "Medida Alfa" in medida[0]
    await s.shutdown()


async def test_alert_job_so_avisa_em_mudanca(setor_teste):
    s = CronScheduler(_Orch(), _FakeStore(), _FakeSettings())
    job = s.add_alert_job("sess", "u", "medida", "<", 60, persist=False)
    j = s.jobs[job["id"]]
    await s._execute_alert(j)
    n1 = len(s.get_feed("sess"))
    assert n1 > 0
    await s._execute_alert(j)  # mesmo conjunto -> não repete
    assert len(s.get_feed("sess")) == n1
    await s.shutdown()
