"""Agenda turnos do agente e entrega resultados no painel ou no Telegram.

Aceita intervalo, disparo único e expressão cron. Os agendamentos persistem
em disco; o fuso configurado pela pessoa governa os horários, inclusive após
reinício do servidor.
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


from ..harness.state import AnalysisState
from ..runtime_imports import ensure_local_site_packages

ensure_local_site_packages()

try:
    from croniter import croniter
    _HAS_CRONITER = True
except ImportError:  # dependência opcional
    _HAS_CRONITER = False

logger = logging.getLogger(__name__)

_MIN_INTERVAL_SEC = 30      # piso de segurança (rate limit de LLM/Telegram)
_MAX_JOBS = 20              # teto para a demo não virar bomba de chamadas
_FEED_MAXLEN = 30           # itens de feed guardados por sessão


def _simple_cron_delay(cron_expr: str, now: Optional[datetime] = None) -> Optional[float]:
    """Fallback simples para `M H * * *` quando croniter nao estiver disponivel."""

    try:
        minute_raw, hour_raw, day_raw, month_raw, weekday_raw = cron_expr.split()
    except ValueError:
        return None

    if day_raw != "*" or month_raw != "*" or weekday_raw != "*":
        return None
    if not (minute_raw.isdigit() and hour_raw.isdigit()):
        return None

    minute = int(minute_raw)
    hour = int(hour_raw)
    if not (0 <= minute <= 59 and 0 <= hour <= 23):
        return None

    now = now or datetime.now().astimezone()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run = next_run + timedelta(days=1)
    return max(1.0, (next_run - now).total_seconds())


class CronScheduler:
    def __init__(self, orchestrator: Any, session_store: Any, settings: Any, telegram_manager: Any = None,
                 session_index: Any = None):
        self.orchestrator = orchestrator
        self.session_store = session_store
        self.settings = settings
        self.telegram_manager = telegram_manager
        self.session_index = session_index
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self.feed: Dict[str, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_FEED_MAXLEN))
        # Configuracao explicita: o relogio do servidor nunca decide a hora do
        # usuario. Enquanto a tela de preferencias nao expoe o campo, o operador
        # pode definir SENTURY_TIMEZONE no ambiente.
        self.timezone_name = (
            os.environ.get("SENTURY_TIMEZONE")
            or getattr(settings, "SENTURY_TIMEZONE", None)
            or "America/Sao_Paulo"
        )
        try:
            self.timezone = ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"fuso horario desconhecido: {self.timezone_name}") from exc

    def _now(self) -> datetime:
        return datetime.now(self.timezone)

    def _normalize_run_at(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            moment = value
        else:
            raw = str(value or "").strip().replace("Z", "+00:00")
            if not raw:
                raise ValueError("falta a data e hora do disparo unico")
            try:
                moment = datetime.fromisoformat(raw)
            except ValueError as exc:
                raise ValueError("data do disparo unico deve estar em ISO 8601") from exc
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=self.timezone)
        return moment.astimezone(self.timezone)

    # ---- CRUD ----
    def add_job(self, session_id: str, user_id: str, prompt: str,
                interval_sec: Optional[int] = None, cron_expr: Optional[str] = None,
                run_at: Optional[Any] = None,
                chat_id: Optional[Any] = None, job_id: Optional[str] = None,
                persist: bool = True, workflow: Optional[str] = None,
                active: bool = True, residente: Optional[str] = None,
                residente_criado_em: Optional[float] = None) -> Dict[str, Any]:
        if active and len([j for j in self.jobs.values() if j["active"]]) >= _MAX_JOBS:
            raise ValueError("limite de agendamentos atingido")

        run_at_iso: Optional[str] = None
        if run_at is not None:
            kind = "once"
            run_at_iso = self._normalize_run_at(run_at).isoformat()
            cron_expr = None
            interval_sec = None
        elif cron_expr:
            self._validate_cron(cron_expr)
            kind = "cron"
            interval_sec = None
        else:
            kind = "interval"
            cron_expr = None
            interval_sec = max(_MIN_INTERVAL_SEC, int(interval_sec or _MIN_INTERVAL_SEC))

        job_id = job_id or uuid.uuid4().hex[:8]
        job = {
            "id": job_id,
            "session_id": session_id,
            "user_id": user_id,
            "prompt": prompt.strip(),
            "workflow": str(workflow or "").strip() or None,
            "residente": residente,
            "residente_criado_em": residente_criado_em,
            "origin_session_id": session_id,
            "kind": kind,
            "interval_sec": interval_sec,
            "cron_expr": cron_expr,
            "run_at": run_at_iso,
            "chat_id": chat_id,
            "active": bool(active),
            "created_at": time.time(),
            "last_run": None,
            "run_count": 0,
        }
        self.jobs[job_id] = job
        job["next_run"] = time.time() + self._next_delay(job) if job["active"] else None
        if job["active"]:
            self._tasks[job_id] = asyncio.create_task(self._run_loop(job_id))
        logger.info(
            "Cron: job %s criado (%s): %r",
            job_id, run_at_iso or cron_expr or f"{interval_sec}s", prompt,
        )
        if persist:
            asyncio.create_task(self._persist())
        return self._public(job)

    def add_once_job(self, session_id: str, user_id: str, prompt: str, *,
                     delay_sec: Optional[int] = None, run_at: Optional[Any] = None,
                     **kwargs: Any) -> Dict[str, Any]:
        """Agenda uma unica tentativa em instante absoluto ou apos um atraso."""

        target = run_at
        if target is None:
            if delay_sec is None:
                raise ValueError("falta quando executar o disparo unico")
            target = self._now() + timedelta(seconds=max(0, int(delay_sec)))
        return self.add_job(
            session_id, user_id, prompt, run_at=target, **kwargs,
        )

    @staticmethod
    def _validate_cron(cron_expr: str) -> None:
        expressao = str(cron_expr or "").strip()
        if len(expressao.split()) != 5:
            raise ValueError("cron precisa ter 5 campos: minuto hora dia mes dia-da-semana")
        if _HAS_CRONITER and not croniter.is_valid(expressao):
            raise ValueError(f"expressao cron invalida: {expressao}")

    def update_job(self, job_id: str, *, prompt: str, kind: str,
                   cron_expr: Optional[str] = None,
                   interval_sec: Optional[int] = None,
                   run_at: Optional[Any] = None,
                   metric: Optional[str] = None, op: Optional[str] = None,
                   threshold: Optional[float] = None) -> Dict[str, Any]:
        """Atualiza uma automacao sem perder identidade nem historico."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"agendamento '{job_id}' nao existe")
        texto = str(prompt or "").strip()
        if not texto:
            raise ValueError("o prompt do agendamento nao pode ficar vazio")
        tipo = str(kind or "").strip().lower()
        if tipo == "cron":
            expressao = str(cron_expr or "").strip()
            self._validate_cron(expressao)
            job.update(kind="cron", cron_expr=expressao, interval_sec=None, run_at=None)
        elif tipo == "interval":
            segundos = max(_MIN_INTERVAL_SEC, int(interval_sec or 0))
            job.update(kind="interval", cron_expr=None, interval_sec=segundos, run_at=None)
        elif tipo == "once":
            moment = self._normalize_run_at(run_at)
            job.update(kind="once", cron_expr=None, interval_sec=None, run_at=moment.isoformat())
        elif tipo == "alert":
            metrica = str(metric or job.get("metric") or "").strip().lower()
            operador = str(op or job.get("op") or "").strip()
            vigiaveis = self._METRIC_LABEL
            if metrica not in vigiaveis:
                if not vigiaveis:
                    raise ValueError("o setor ativo nao tem metrica para vigiar")
                raise ValueError(f"metrica do alerta deve ser uma destas: {', '.join(sorted(vigiaveis))}")
            if operador not in ("<", ">"):
                raise ValueError("operador do alerta deve ser '<' ou '>'")
            segundos = max(_MIN_INTERVAL_SEC, int(interval_sec or job.get("interval_sec") or 0))
            limite = threshold if threshold is not None else job.get("threshold")
            if limite is None:
                raise ValueError("falta o limite do alerta")
            job.update(
                kind="alert", cron_expr=None, interval_sec=segundos, run_at=None,
                metric=metrica, op=operador, threshold=float(limite),
            )
        else:
            raise ValueError("tipo deve ser 'cron', 'interval', 'once' ou 'alert'")
        job["prompt"] = texto
        anterior = self._tasks.pop(job_id, None)
        if anterior:
            anterior.cancel()
        if job.get("active"):
            self._tasks[job_id] = asyncio.create_task(self._run_loop(job_id))
        asyncio.create_task(self._persist())
        return self._public(job)

    def set_active(self, job_id: str, active: bool) -> Dict[str, Any]:
        """Ativa ou pausa sem apagar configuracao nem historico."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"agendamento '{job_id}' nao existe")
        alvo = bool(active)
        if alvo == bool(job.get("active")):
            return self._public(job)
        if alvo and len([j for j in self.jobs.values() if j.get("active")]) >= _MAX_JOBS:
            raise ValueError("limite de agendamentos atingido")
        job["active"] = alvo
        job["next_run"] = time.time() + self._next_delay(job) if alvo else None
        anterior = self._tasks.pop(job_id, None)
        if anterior:
            anterior.cancel()
        if alvo:
            self._tasks[job_id] = asyncio.create_task(self._run_loop(job_id))
        asyncio.create_task(self._persist())
        return self._public(job)

    def remove_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        job["active"] = False
        task = self._tasks.pop(job_id, None)
        if task:
            task.cancel()
        self.jobs.pop(job_id, None)
        asyncio.create_task(self._persist())
        return True

    def list_jobs(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return [self._public(j) for j in self.jobs.values() if session_id is None or j["session_id"] == session_id]

    def get_feed(self, session_id: str, since: float = 0.0) -> List[Dict[str, Any]]:
        return [item for item in self.feed.get(session_id, ()) if item["ts"] > since]

    # ---- Execução ----
    def _next_delay(self, job: Dict[str, Any]) -> float:
        if job["kind"] == "once":
            run_at = self._normalize_run_at(job.get("run_at"))
            return max(0.0, (run_at - self._now()).total_seconds())
        if job["kind"] == "cron" and job.get("cron_expr"):
            if _HAS_CRONITER:
                try:
                    now = self._now()
                    nxt = croniter(job["cron_expr"], now).get_next(float)
                    return max(1.0, nxt - now.timestamp())
                except Exception:
                    return 3600.0
            fallback_delay = _simple_cron_delay(job["cron_expr"], self._now())
            if fallback_delay is not None:
                return fallback_delay
            return 3600.0
        return float(job["interval_sec"])

    async def _run_loop(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        try:
            while job.get("active"):
                demora = self._next_delay(job)
                job["next_run"] = time.time() + demora
                await asyncio.sleep(demora)
                if not job.get("active"):
                    break
                try:
                    await self._execute(job)
                finally:
                    if job.get("kind") == "once":
                        job["active"] = False
                        self.jobs.pop(job_id, None)
                        self._tasks.pop(job_id, None)
                        await self._persist()
                        break
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Cron: loop do job %s falhou: %s", job_id, exc)

    async def _execute(self, job: Dict[str, Any]) -> None:
        if job.get("residente"):
            from ..residentes.rotinas import disparar
            await disparar(self, job)
            return
        if job.get("kind") == "alert":
            await self._execute_alert(job)
            return
        session_id = job["session_id"]
        run_plan = ""
        try:
            raw = await self.session_store.get(session_id)
            if not raw and self.session_index is not None:
                raw = await self.session_index.load(job["user_id"], session_id)
                if not raw:
                    # A rotina fica na conversa de origem enquanto ela existir.
                    # Se ela sumiu de verdade, cria uma nova e continua nela.
                    session_id = f"cron-{uuid.uuid4().hex}"
                    job["session_id"] = session_id
            state = AnalysisState.from_dict(raw) if raw else AnalysisState.new(session_id, job["user_id"])
            state.session_id = session_id
            state.user_id = job["user_id"]

            prompt = job["prompt"]
            if job.get("workflow"):
                from ..memory import plano as _plano
                from ..memory import workflow as _workflow

                receita = _workflow.ler(job["workflow"])
                if not receita:
                    raise ValueError(f"workflow '{job['workflow']}' nao existe mais")
                run_plan = (
                    f"{job['workflow']}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
                    f"{uuid.uuid4().hex[:4]}"
                )
                passos = [re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", p) for p in receita["passos"]]
                criado = _plano.criar(
                    run_plan,
                    f"Execucao de {job['workflow']}",
                    passos,
                    contexto=receita.get("porque") or f"Disparo do workflow {job['workflow']}",
                )
                if not criado.get("ok"):
                    raise ValueError(criado.get("erro") or "nao consegui materializar o workflow")
                prompt = (
                    f"Execute agora o plano `{run_plan}`, criado pelo workflow "
                    f"`{job['workflow']}`. Consulte-o com ver_plano, execute seus "
                    "passos e marque cada tarefa conforme terminar."
                )

            result = await self.orchestrator.handle_message(state, prompt)
            state.trim_history()
            await self.session_store.set(session_id, state.to_dict(), self.settings.SESSION_TTL_SEC)
            if self.session_index is not None:
                await self.session_index.remember(
                    state,
                    title=f"Workflow: {job['workflow']}" if job.get("workflow") else None,
                )
            if job.get("workflow"):
                from ..memory import workflow as _workflow

                _workflow.registrar_execucao(job["workflow"], run_plan, estado="disparado")
        except Exception as exc:
            logger.error("Cron: execução do job %s falhou: %s", job["id"], exc)
            if job.get("workflow"):
                from ..memory import workflow as _workflow

                _workflow.registrar_execucao(
                    job["workflow"], run_plan, estado="falhou", nota=str(exc),
                )
            return

        job["last_run"] = time.time()
        job["run_count"] += 1
        mensagem = result.get("message") or "(sem resposta)"

        # PAINEL: feed para o frontend puxar via polling.
        self.feed[session_id].append({
            "ts": time.time(),
            "job_id": job["id"],
            "prompt": job["prompt"],
            "message": mensagem,
            "attachment": result.get("attachment"),
        })

        # TELEGRAM: push direto, se houver chat_id.
        if job.get("chat_id") and self.telegram_manager:
            await self.telegram_manager.send_message(job["chat_id"], f"*Agendado* — {job['prompt']}\n\n{mensagem}")

        await self._persist()  # salva run_count/last_run

    # ---- Alerta por limiar (cron reativo) ----
    @property
    def _METRIC_LABEL(self) -> Dict[str, str]:
        """Quem existe para vigiar vem do PACOTE ativo, nao de uma lista aqui."""
        from ..domains.do_setor import metricas_vigiaveis

        return metricas_vigiaveis()

    def add_alert_job(self, session_id: str, user_id: str, metric: str, op: str, threshold: float,
                      interval_sec: int = 120, chat_id: Optional[Any] = None,
                      job_id: Optional[str] = None, persist: bool = True,
                      active: bool = True) -> Dict[str, Any]:
        if active and len([j for j in self.jobs.values() if j["active"]]) >= _MAX_JOBS:
            raise ValueError("limite de agendamentos atingido")
        job_id = job_id or uuid.uuid4().hex[:8]
        job = {
            "id": job_id, "session_id": session_id, "user_id": user_id,
            "kind": "alert", "metric": metric, "op": op, "threshold": float(threshold),
            "workflow": None, "origin_session_id": session_id,
            "prompt": f"alerta: {self._METRIC_LABEL.get(metric, metric)} {op} {threshold}",
            "interval_sec": max(_MIN_INTERVAL_SEC, int(interval_sec)), "cron_expr": None,
            "chat_id": chat_id, "active": bool(active), "created_at": time.time(),
            "last_run": None, "run_count": 0, "_last_breach": None,
        }
        self.jobs[job_id] = job
        if job["active"]:
            self._tasks[job_id] = asyncio.create_task(self._run_loop(job_id))
        logger.info("Cron: alerta %s criado (%s %s %s, %ss)", job_id, metric, op, threshold, job["interval_sec"])
        if persist:
            asyncio.create_task(self._persist())
        return self._public(job)

    async def _execute_alert(self, job: Dict[str, Any]) -> None:
        try:
            breaches = await self._check_alert(job)
        except Exception as exc:
            logger.error("Cron: checagem do alerta %s falhou: %s", job["id"], exc)
            return
        job["last_run"] = time.time()
        job["run_count"] += 1
        chave = tuple(sorted(breaches))
        if not breaches:
            job["_last_breach"] = ()
            return
        if chave == job.get("_last_breach"):
            return  # já avisou desse mesmo conjunto: não repete a cada ciclo
        job["_last_breach"] = chave
        label = self._METRIC_LABEL.get(job["metric"], job["metric"])
        corpo = "\n".join(f"• {b}" for b in breaches[:10])
        if len(breaches) > 10:
            corpo += f"\n… (+{len(breaches) - 10})"
        msg = f"**Alerta** — {label} {job['op']} {job['threshold']}:\n{corpo}"
        self.feed[job["session_id"]].append({
            "ts": time.time(), "job_id": job["id"], "prompt": job["prompt"],
            "message": msg, "attachment": None,
        })
        if job.get("chat_id") and self.telegram_manager:
            await self.telegram_manager.send_message(job["chat_id"], msg)

    async def _check_alert(self, job: Dict[str, Any]) -> List[str]:
        """Pede ao setor ativo a medição exigida pelo alerta."""
        from ..domains.do_setor import medir_para_alerta

        thr = float(job["threshold"])
        rompeu = (lambda v: v < thr) if job["op"] == "<" else (lambda v: v > thr)
        fora = await medir_para_alerta(self.orchestrator.store, job["metric"], rompeu)
        # Maior rompimento primeiro quando o alerta e "acima de".
        try:
            fora.sort(key=lambda s: float(s.rsplit(":", 1)[1].strip().rstrip("%")),
                      reverse=(job["op"] == ">"))
        except (IndexError, ValueError):
            pass
        return fora

    # ---- Persistência ----
    def caminho_local(self) -> "pathlib.Path":
        """Onde os agendamentos moram nesta máquina."""
        import os
        import pathlib

        home = os.environ.get("SENTURY_HOME") or str(pathlib.Path.home() / ".sentury")
        return pathlib.Path(home) / "agendamentos.json"

    def _gravar_local(self, dados: str) -> None:
        try:
            caminho = self.caminho_local()
            caminho.parent.mkdir(parents=True, exist_ok=True)
            tmp = caminho.with_suffix(".tmp")
            tmp.write_text(dados, encoding="utf-8")
            tmp.replace(caminho)
        except OSError as exc:
            logger.warning("Cron: falha ao gravar agendamentos localmente: %s", exc)

    def _ler_local(self):
        try:
            return json.loads(self.caminho_local().read_text(encoding="utf-8") or "[]")
        except (OSError, json.JSONDecodeError):
            return []

    async def _persist(self) -> None:
        # Inativo nao significa descartavel: workflows com agenda nascem
        # pausados enquanto aguardam aprovacao, e precisam sobreviver ao restart.
        dados = json.dumps([self._storable(j) for j in self.jobs.values()])
        # O cron e local: o disco e a unica persistencia. Enquanto o Redis
        # tinha preferencia, um restart re-armava a versao velha que ficou la.
        self._gravar_local(dados)

    async def _jobs_guardados(self):
        return self._ler_local()

    async def load_persisted(self) -> None:
        """Recarrega os jobs salvos e re-arma as tasks (chamado no startup)."""
        try:
            guardados = await self._jobs_guardados()
            if not guardados:
                return
            for j in guardados:
                try:
                    if j.get("kind") == "alert":
                        self.add_alert_job(
                            session_id=j["session_id"], user_id=j.get("user_id", "cron"),
                            metric=j["metric"], op=j["op"], threshold=j["threshold"],
                            interval_sec=j.get("interval_sec", 120), chat_id=j.get("chat_id"),
                            job_id=j.get("id"), persist=False,
                            active=bool(j.get("active", True)),
                        )
                        self.jobs[j["id"]].update({
                            "origin_session_id": j.get("origin_session_id") or j["session_id"],
                            "created_at": j.get("created_at") or time.time(),
                            "last_run": j.get("last_run"),
                            "run_count": int(j.get("run_count") or 0),
                        })
                    else:
                        self.add_job(
                            session_id=j["session_id"], user_id=j.get("user_id", "cron"),
                            prompt=j["prompt"], interval_sec=j.get("interval_sec"),
                            cron_expr=j.get("cron_expr"), run_at=j.get("run_at"),
                            chat_id=j.get("chat_id"),
                            job_id=j.get("id"), persist=False,
                            workflow=j.get("workflow"),
                            residente=j.get("residente"),
                            residente_criado_em=j.get("residente_criado_em"),
                            active=bool(j.get("active", True)),
                        )
                        self.jobs[j["id"]].update({
                            "origin_session_id": j.get("origin_session_id") or j["session_id"],
                            "created_at": j.get("created_at") or time.time(),
                            "last_run": j.get("last_run"),
                            "run_count": int(j.get("run_count") or 0),
                            "motivo": j.get("motivo", ""),
                        })
                except Exception:
                    continue
            logger.info("Cron: %d agendamento(s) recarregado(s).", len(self.jobs))
        except Exception as exc:
            logger.warning("Cron: falha ao recarregar agendamentos: %s", exc)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()

    @staticmethod
    def _storable(job: Dict[str, Any]) -> Dict[str, Any]:
        return {k: job.get(k) for k in
                ("id", "session_id", "user_id", "prompt", "kind", "interval_sec",
                 "cron_expr", "run_at", "chat_id", "metric", "op", "threshold", "workflow",
                 "origin_session_id", "created_at", "last_run", "run_count", "active",
                 "residente", "residente_criado_em", "motivo")}

    @staticmethod
    def _public(job: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in job.items() if k != "user_id"}


def parse_cron_command(raw: str) -> Optional[Dict[str, Any]]:
    """Interpreta o pedido em linguagem natural:
    - "a cada N min/h/s ..."      -> {"interval_sec": N, "prompt": ...}
    - "todo dia às 11h ..."       -> {"cron_expr": "0 11 * * *", "prompt": ...} (croniter)
    Retorna None se não parsear."""
    texto = raw.strip()
    low = texto.lower()

    once = re.search(
        r"daqui\s+a\s+(\d+)\s*(segundos?|minutos?|horas?|seg|min|h|s|m)\b",
        low,
    )
    if once:
        quantidade = int(once.group(1))
        unidade = once.group(2)
        if unidade in ("h", "hora", "horas"):
            delay = quantidade * 3600
        elif unidade in ("s", "seg", "segundo", "segundos"):
            delay = quantidade
        else:
            delay = quantidade * 60
        prompt = re.sub(
            r"daqui\s+a\s+\d+\s*\w+\b", "", texto,
            count=1, flags=re.IGNORECASE,
        ).strip(" ,.-") or "Me lembre"
        return {"kind": "once", "delay_sec": delay, "prompt": prompt}

    absolute = re.search(
        r"(?:^|\bem\s+)(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)\b",
        texto,
        flags=re.IGNORECASE,
    )
    if absolute:
        prompt = (texto[:absolute.start()] + texto[absolute.end():]).strip(" ,.-") or "Me lembre"
        return {"kind": "once", "run_at": absolute.group(1), "prompt": prompt}

    # "a cada N unidade": plural incluído (minutoS)
    m = re.search(r"a cada\s+(\d+)\s*(segundos?|minutos?|horas?|seg|min|h|s|m)\b", low)
    if m:
        n = int(m.group(1))
        unidade = m.group(2)
        if unidade in ("h", "hora", "horas"):
            intervalo = n * 3600
        elif unidade in ("s", "seg", "segundo", "segundos"):
            intervalo = n
        else:
            intervalo = n * 60
        prompt = re.sub(r"a cada\s+\d+\s*\w+\b", "", texto, flags=re.IGNORECASE).strip(" ,.-") or "Me dê o panorama geral"
        return {"interval_sec": intervalo, "prompt": prompt}

    # (nota: parse_alert_command trata os alertas por limiar, ver abaixo)

    # "todo dia às 11h" / "diariamente 9:30" -> expressão cron ancorada no horário
    md = re.search(r"todo\s+dia|todos os dias|diariamente", low)
    if md:
        hm = re.search(r"(\d{1,2})(?::(\d{2}))?\s*h", low) or re.search(r"(\d{1,2}):(\d{2})", low)
        hora = int(hm.group(1)) if hm else 9
        minuto = int(hm.group(2)) if (hm and hm.group(2)) else 0
        # Limpa a frase de agendamento E o token de horário do prompt.
        prompt = texto
        if hm:
            prompt = prompt.replace(hm.group(0), " ", 1)
        prompt = re.sub(r"(todo\s+dia|todos os dias|diariamente)(\s+(à|a)s)?", "", prompt, flags=re.IGNORECASE)
        prompt = re.sub(r"\s+", " ", prompt).strip(" ,.-") or "Me dê o panorama geral"
        return {"cron_expr": f"{minuto} {hora} * * *", "prompt": prompt}

    # "toda segunda-feira às 8h". No cron, domingo=0 e segunda=1.
    dias = {
        "domingo": 0, "segunda": 1, "terca": 2, "terça": 2,
        "quarta": 3, "quinta": 4, "sexta": 5, "sabado": 6, "sábado": 6,
    }
    mw = re.search(
        r"tod[ao]s?(?:\s+as)?\s+(domingos?|segundas?(?:-feiras?)?|"
        r"ter[cç]as?(?:-feiras?)?|quartas?(?:-feiras?)?|quintas?(?:-feiras?)?|"
        r"sextas?(?:-feiras?)?|s[áa]bados?)",
        low,
    )
    if mw:
        palavra = mw.group(1).split("-", 1)[0].rstrip("s")
        hm = re.search(r"(\d{1,2})(?::(\d{2}))?\s*h", low) or re.search(r"(\d{1,2}):(\d{2})", low)
        hora = int(hm.group(1)) if hm else 9
        minuto = int(hm.group(2)) if (hm and hm.group(2)) else 0
        prompt = texto
        if hm:
            prompt = prompt.replace(hm.group(0), " ", 1)
        prompt = prompt.replace(mw.group(0), " ", 1)
        prompt = re.sub(r"^\s*(?:às|as|a)\s+", "", prompt, count=1, flags=re.IGNORECASE)
        prompt = re.sub(r"\s+", " ", prompt).strip(" ,.-") or "Me dê o panorama geral"
        return {"cron_expr": f"{minuto} {hora} * * {dias[palavra]}", "prompt": prompt}

    return None


def _maior_e_melhor(metric: str) -> bool:
    """Se subir é bom para essa métrica, segundo o pacote ativo (padrão: sim)."""
    try:
        from ..domains import get_active_domain

        mapa = getattr(get_active_domain(), "higher_is_better", {}) or {}
    except Exception:
        return True
    for nome, maior in mapa.items():
        if nome == metric or str(nome).startswith(f"{metric}_"):
            return bool(maior)
    return True


def parse_alert_command(raw: str, metricas: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Interpreta um alerta por limiar, com as métricas que o setor ativo sabe
    vigiar ("<métrica> abaixo de 50%" -> {"metric", "op": "<", "threshold": 50}).
    Retorna None se não parsear ou se o setor não tem essa métrica."""
    low = (raw or "").lower()
    if metricas is None:
        from ..domains.do_setor import metricas_vigiaveis

        metricas = metricas_vigiaveis()

    metric = next(
        (chave for chave, rotulo in metricas.items()
         if re.search(rf"\b(?:{re.escape(str(chave).lower())}|{re.escape(str(rotulo).lower())})\b", low)),
        None,
    )
    if metric is None:
        return None

    # Tira "a cada N unidade" para não confundir o número do limiar.
    limpo = re.sub(r"a cada\s+\d+\s*\w+", " ", low)
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*%?", limpo)
    if not m:
        return None
    threshold = float(m.group(1).replace(",", "."))

    if any(w in low for w in ("abaixo", "menor", "cair", "cai", "despenca", "<", "menos de")):
        op = "<"
    elif any(w in low for w in ("acima", "maior", "passar", "ultrapassar", "subir", ">", "mais de")):
        op = ">"
    else:
        op = "<" if _maior_e_melhor(metric) else ">"

    interval = 120
    mi = re.search(r"a cada\s+(\d+)\s*(segundos?|minutos?|min|seg|h|s|m)\b", low)
    if mi:
        n, u = int(mi.group(1)), mi.group(2)
        interval = n * (3600 if u.startswith("h") else 1 if u in ("s", "seg", "segundo", "segundos") else 60)

    return {"metric": metric, "op": op, "threshold": threshold, "interval_sec": interval}
