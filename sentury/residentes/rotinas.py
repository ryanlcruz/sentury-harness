"""Rotinas só enfileiram trabalho; o worker mantém orçamento e permissões."""
import time
from datetime import datetime
from pydantic import BaseModel, Field

from ..external import agendador
from . import hq, manifesto, registro


class NovaRotina(BaseModel):
    pedido: str = Field(min_length=1, max_length=8000)
    cron_expr: str | None = None
    interval_sec: int | None = Field(default=None, ge=30)
    run_at: str | None = None


class EstadoDaRotina(BaseModel):
    ativa: bool | None = None
    pedido: str | None = Field(default=None, min_length=1, max_length=8000)
    cron_expr: str | None = None
    interval_sec: int | None = Field(default=None, ge=30)
    run_at: str | None = None


def _agendador():
    atual = agendador.atual()
    if atual is None:
        raise ValueError("Agendador indisponível nesta instalação.")
    return atual


def _bloqueio(nome, criada_em=None):
    agente = registro.carregar(nome)
    if not agente or agente.estado == manifesto.APOSENTADO:
        return "Residente aposentado ou ausente: a rotina não enfileira tarefas."
    if criada_em is not None and agente.criado_em != criada_em:
        return "Esta rotina pertence a um residente aposentado com o mesmo nome."
    if agente.estado == manifesto.PAUSADO:
        return "Residente pausado: a rotina não enfileira tarefas."
    return ""


def _rotulo(job):
    if job["kind"] == "interval":
        segundos = job["interval_sec"]
        if segundos % 3600 == 0:
            return f"A cada {segundos // 3600} h"
        if segundos % 60 == 0:
            return f"A cada {segundos // 60} min"
        return f"A cada {segundos} s"
    if job["kind"] == "once":
        return "Uma vez em " + datetime.fromisoformat(job["run_at"]).strftime("%d/%m/%Y às %H:%M")
    minuto, hora, dia, mes, semana = job["cron_expr"].split()
    if minuto.isdigit() and hora.isdigit() and dia == mes == "*":
        dias = {"0": "domingo", "1": "segunda", "2": "terça", "3": "quarta",
                "4": "quinta", "5": "sexta", "6": "sábado", "7": "domingo"}
        artigo = "Todo" if semana in ("0", "6", "7") else "Toda"
        quando = "Todo dia" if semana == "*" else f"{artigo} {dias[semana]}" if semana in dias else ""
        if quando:
            return f"{quando} às {int(hora)}h" + (f"{int(minuto):02d}" if int(minuto) else "")
    return f"Cron: {job['cron_expr']}"


def _publico(scheduler, job):
    proxima = datetime.fromtimestamp(job["next_run"], scheduler.timezone).isoformat() if job.get("active") and job.get("next_run") else None
    return {**scheduler._public(job), "rotulo": _rotulo(job),
            "proxima_execucao": proxima, "fuso": scheduler.timezone_name,
            "bloqueio": _bloqueio(job["residente"], job.get("residente_criado_em"))}


def listar(nome):
    hq.ver(nome)
    scheduler = _agendador()
    return [_publico(scheduler, job) for job in scheduler.jobs.values() if job.get("residente") == nome]


async def criar(nome, pedido, cron_expr=None, interval_sec=None, run_at=None):
    agente = hq.ver(nome)
    if agente["estado"] == manifesto.APOSENTADO:
        raise ValueError("Um residente aposentado não recebe rotinas novas.")
    texto = str(pedido or "").strip()
    if not texto:
        raise ValueError("Diga a tarefa da rotina.")
    if sum(valor is not None and valor != "" for valor in (cron_expr, interval_sec, run_at)) != 1:
        raise ValueError("Escolha um horário, um intervalo ou uma data para a rotina.")
    if interval_sec is not None and interval_sec < 30:
        raise ValueError("O intervalo mínimo é de 30 segundos.")
    scheduler = _agendador()
    job = scheduler.add_job(hq.sessao_do(nome), "hq", texto, cron_expr=cron_expr,
                            interval_sec=interval_sec, run_at=run_at, residente=nome,
                            residente_criado_em=agente["criado_em"], persist=False)
    await scheduler._persist()
    return _publico(scheduler, scheduler.jobs[job["id"]])


def _exigir(scheduler, nome, rotina_id):
    job = scheduler.jobs.get(rotina_id)
    if not job or job.get("residente") != nome:
        raise ValueError("Rotina não encontrada para este residente.")
    return job


async def mudar(nome, rotina_id, ativa=None, campos=None):
    scheduler = _agendador()
    job = _exigir(scheduler, nome, rotina_id)
    campos = campos or {}
    horarios = {chave: campos[chave] for chave in ("cron_expr", "interval_sec", "run_at") if campos.get(chave) is not None}
    if len(horarios) > 1:
        raise ValueError("Escolha um horário, um intervalo ou uma data para a rotina.")
    if horarios or campos.get("pedido") is not None:
        tipo = {"cron_expr": "cron", "interval_sec": "interval", "run_at": "once"}
        kind = tipo[next(iter(horarios))] if horarios else job["kind"]
        valores = horarios or {"cron_expr": job.get("cron_expr"), "interval_sec": job.get("interval_sec"), "run_at": job.get("run_at")}
        scheduler.update_job(rotina_id, prompt=campos.get("pedido") if campos.get("pedido") is not None else job["prompt"], kind=kind, **valores)
        job["next_run"] = time.time() + scheduler._next_delay(job) if job["active"] else None
    if ativa is not None:
        scheduler.set_active(rotina_id, ativa)
    await scheduler._persist()
    return _publico(scheduler, scheduler.jobs[rotina_id])


async def apagar(nome, rotina_id):
    scheduler = _agendador()
    _exigir(scheduler, nome, rotina_id)
    scheduler.remove_job(rotina_id)
    await scheduler._persist()
    return {"ok": True}


async def disparar(scheduler, job):
    motivo = _bloqueio(job["residente"], job.get("residente_criado_em"))
    if not motivo:
        try:
            hq.pedir(job["residente"], job["prompt"], origem=f"rotina:{job['id']}")
        except (ValueError, hq.NaoEncontrado) as exc:
            motivo = str(exc)
        else:
            job["last_run"] = time.time()
            job["run_count"] += 1
    job["motivo"] = motivo
    await scheduler._persist()
