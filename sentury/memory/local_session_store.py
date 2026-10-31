"""Durable local memory for Sentury.

The append-only JSONL journal is the source of truth. SQLite is only the fast,
rebuildable projection used by the existing async key/value store contract.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


SCHEMA_VERSION = 1

# Acima disto o diario e compactado. Medido numa maquina real: 85 MB em
# `store-events.jsonl`, porque cada `set` grava o estado INTEIRO da sessao e
# o diario guardava todas as versoes de todas as conversas.
DIARIO_MAXIMO_BYTES = 20 * 1024 * 1024


class LocalMemoryCorruptionError(RuntimeError):
    """Raised when a committed journal line cannot be decoded safely."""


def default_sentury_home(configured: str = "") -> Path:
    """Resolve Sentury's local data directory without writing inside the repo."""
    explicit = str(configured or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path.home() / ".sentury").resolve()


class LocalSessionStore:
    """Single-process durable store backed by JSONL + SQLite.

    Writes are journal-first and fsynced. If the process stops after the journal
    append but before SQLite commits, the missing projection is replayed on the
    next construction. Async tasks are serialized by a process-local lock;
    deployments should use one Sentury writer for each data directory.
    """

    def __init__(self, sentury_home: str | Path = ""):
        self.backend_name = "local"
        self.sentury_home = default_sentury_home(str(sentury_home or ""))
        self.memory_dir = self.sentury_home / "memory"
        self.state_dir = self.sentury_home / "state"
        self.journal_path = self.memory_dir / "store-events.jsonl"
        # Camada 2: o mesmo evento tambem cai num journal da propria sessao,
        # em sessions/AAAA/MM/DD/<id>/events.jsonl. O journal global continua
        # sendo a fonte; este e o recorte que da para ler, replicar e comparar
        # sem varrer o historico inteiro.
        self.sessions_dir = self.memory_dir / "sessions"
        self.catalog_path = self.state_dir / "sentury.db"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Dois processos no mesmo diretorio intercalam `seq` no journal e a
        # proxima abertura falha. Recusar na hora diz quem ja esta la.
        from .escritor_unico import Lock as _LockDePasta

        self._lock_da_pasta = _LockDePasta(self.sentury_home).adquirir()
        self._async_lock = asyncio.Lock()
        self._file_lock = threading.RLock()
        self._next_seq = 1
        # Tamanho logo depois da ultima compactacao. Se o estado VIVO ja passa
        # do teto, compactar de novo a cada escrita nao reduziria nada.
        self._tamanho_compactado = 0
        self._initialize_projection()
        self._compactar_se_grande()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.catalog_path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_projection(self) -> None:
        with self._file_lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    hot_expires_at REAL NOT NULL,
                    warm_expires_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    event_seq INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            row = connection.execute(
                "SELECT value FROM memory_meta WHERE key = 'last_event_seq'"
            ).fetchone()
            projected_seq = int(row["value"]) if row else 0
            highest_seq = projected_seq
            for event in self._iter_journal():
                seq = int(event["seq"])
                highest_seq = max(highest_seq, seq)
                if seq > projected_seq:
                    self._apply_event(connection, event)
            if projected_seq > highest_seq:
                raise LocalMemoryCorruptionError(
                    "SQLite projection is ahead of the append-only journal. "
                    "The journal cannot be replaced by derived state."
                )
            self._next_seq = highest_seq + 1

    def _iter_journal(self) -> Iterator[Dict[str, Any]]:
        if not self.journal_path.exists():
            return
        raw = self.journal_path.read_bytes()
        if raw and not raw.endswith((b"\n", b"\r")):
            # Our committed records always end in a newline. A non-terminated
            # Um trecho final inválido pode ser escrita interrompida; preserva o prefixo válido.
            valid_size = raw.rfind(b"\n") + 1
            with self.journal_path.open("r+b") as journal:
                journal.truncate(valid_size)
                journal.flush()
                os.fsync(journal.fileno())
            raw = raw[:valid_size]
        lines = raw.splitlines(keepends=True)
        prior_seq = 0
        for index, encoded in enumerate(lines, start=1):
            complete = encoded.endswith((b"\n", b"\r"))
            try:
                event = json.loads(encoded.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                if index == len(lines) and not complete:
                    # A crash can leave an uncommitted partial tail.
                    break
                raise LocalMemoryCorruptionError(
                    f"Invalid local journal at {self.journal_path}, line {index}."
                ) from exc
            if not isinstance(event, dict) or "seq" not in event or "type" not in event:
                raise LocalMemoryCorruptionError(
                    f"Invalid local event at {self.journal_path}, line {index}."
                )
            if int(event.get("schema_version", 0)) != SCHEMA_VERSION:
                raise LocalMemoryCorruptionError(
                    f"Unsupported local event schema at {self.journal_path}, line {index}."
                )
            seq = int(event["seq"])
            if seq <= prior_seq:
                raise LocalMemoryCorruptionError(
                    f"Non-monotonic local event sequence at {self.journal_path}, line {index}."
                )
            prior_seq = seq
            yield event

    def compactar(self) -> Dict[str, int]:
        """Reescreve o diario com o ULTIMO evento de cada chave.

        O diario continua sendo a fonte: o que sai e versao antiga que a
        projecao ja superou. Ficam os `seq` originais, em ordem, e o maior
        deles sobrevive (e o ultimo evento de alguma chave): por isso a
        projecao nunca fica "a frente" do diario. Chave esquecida mantem o
        evento `memory.forgotten`, que e pequeno e e o que impede ela de voltar
        num replay. A versao anterior fica em `store-events.anterior.jsonl.gz`,
        uma so, substituida a cada compactacao.
        """
        import gzip

        with self._file_lock:
            if not self.journal_path.exists():
                return {"antes": 0, "depois": 0, "eventos_antes": 0, "eventos_depois": 0}
            eventos = list(self._iter_journal())
            ultimo: Dict[str, Dict[str, Any]] = {}
            for evento in eventos:
                ultimo[str(evento.get("key"))] = evento
            mantidos = sorted(ultimo.values(), key=lambda e: int(e["seq"]))
            antes = self.journal_path.stat().st_size

            copia = self.journal_path.with_name("store-events.anterior.jsonl.gz")
            with self.journal_path.open("rb") as origem, gzip.open(copia, "wb") as destino:
                while bloco := origem.read(1024 * 1024):
                    destino.write(bloco)

            temporario = self.journal_path.with_suffix(".jsonl.tmp")
            with temporario.open("wb") as saida:
                for evento in mantidos:
                    saida.write((json.dumps(evento, ensure_ascii=False, separators=(",", ":"),
                                            default=str) + "\n").encode("utf-8"))
                saida.flush()
                os.fsync(saida.fileno())
            os.replace(temporario, self.journal_path)
            depois = self.journal_path.stat().st_size
            self._tamanho_compactado = depois
            self._compactar_sessoes()
            logger.info("Diario local compactado: %d -> %d bytes (%d -> %d eventos).",
                        antes, depois, len(eventos), len(mantidos))
            return {"antes": antes, "depois": depois,
                    "eventos_antes": len(eventos), "eventos_depois": len(mantidos)}

    _SESSAO_MAXIMA_BYTES = 1024 * 1024

    def _compactar_sessoes(self) -> None:
        """O diario de cada sessao recebe a mesma copia do estado inteiro a
        cada turno, e quem le (`/sentury/memory/sessions`) so usa seq, tipo e
        hora. Acima de 1 MB fica so o ultimo evento da sessao."""
        for arquivo in self.sessions_dir.glob("*/*/*/*/events.jsonl"):
            try:
                if arquivo.stat().st_size <= self._SESSAO_MAXIMA_BYTES:
                    continue
                linhas = [l for l in arquivo.read_bytes().splitlines(keepends=True) if l.strip()]
                if linhas:
                    temporario = arquivo.with_suffix(".jsonl.tmp")
                    temporario.write_bytes(linhas[-1])
                    os.replace(temporario, arquivo)
            except OSError as exc:
                logger.warning("Nao consegui compactar %s: %s", arquivo, exc)

    def _compactar_se_grande(self) -> None:
        """Por escrita custa um `stat`. Compacta quando passa do teto e cresceu
        de verdade desde a ultima vez; nunca derruba a escrita que o chamou."""
        try:
            tamanho = self.journal_path.stat().st_size
        except OSError:
            return
        if tamanho <= DIARIO_MAXIMO_BYTES or tamanho <= 2 * self._tamanho_compactado:
            return
        try:
            self.compactar()
        except Exception:
            logger.warning("Nao consegui compactar o diario local.", exc_info=True)

    def _apply_event(self, connection: sqlite3.Connection, event: Dict[str, Any]) -> None:
        event_type = event["type"]
        seq = int(event["seq"])
        if event_type == "memory.recorded":
            connection.execute(
                """
                INSERT INTO memory_records
                    (key, value_json, hot_expires_at, warm_expires_at, updated_at, event_seq)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    hot_expires_at = excluded.hot_expires_at,
                    warm_expires_at = excluded.warm_expires_at,
                    updated_at = excluded.updated_at,
                    event_seq = excluded.event_seq
                """,
                (
                    str(event["key"]),
                    json.dumps(event.get("value", {}), ensure_ascii=False, default=str),
                    float(event["hot_expires_at"]),
                    float(event["warm_expires_at"]),
                    float(event["time"]),
                    seq,
                ),
            )
        elif event_type == "memory.forgotten":
            connection.execute("DELETE FROM memory_records WHERE key = ?", (str(event["key"]),))
        else:
            raise LocalMemoryCorruptionError(f"Unknown local event type: {event_type}")
        connection.execute(
            """
            INSERT INTO memory_meta(key, value) VALUES ('last_event_seq', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(seq),),
        )

    def caminho_da_sessao(self, session_id: str, quando: Optional[float] = None) -> Path:
        """Pasta da sessao, por data. Datas separam o que cresce sem limite."""
        momento = time.localtime(quando or time.time())
        seguro = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")[:120] or "sem-id"
        return self.sessions_dir / time.strftime("%Y/%m/%d", momento) / seguro

    def _registrar_na_sessao(self, event: Dict[str, Any], encoded: bytes) -> None:
        """Copia o evento para o journal da propria sessao.

        Falhar aqui nao pode derrubar a escrita: a fonte e o journal global,
        e este e um indice por sessao construido a partir dele.
        """
        chave = str(event.get("key") or "")
        if not chave:
            return
        try:
            pasta = self.caminho_da_sessao(chave, event.get("time"))
            pasta.mkdir(parents=True, exist_ok=True)
            with (pasta / "events.jsonl").open("ab") as arquivo:
                arquivo.write(encoded)
        except OSError as exc:
            logger.warning("Journal da sessao %s indisponivel: %s", chave, exc)

    def eventos_da_sessao(self, session_id: str) -> List[Dict[str, Any]]:
        """Eventos de uma sessao, em qualquer dia em que ela apareceu."""
        seguro = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")[:120]
        if not seguro:
            return []
        saida: List[Dict[str, Any]] = []
        for arquivo in sorted(self.sessions_dir.glob(f"*/*/*/{seguro}/events.jsonl")):
            for linha in arquivo.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    try:
                        saida.append(json.loads(linha))
                    except json.JSONDecodeError:
                        continue
        return sorted(saida, key=lambda e: e.get("seq") or 0)

    def sessoes_por_dia(self, limite: int = 60) -> List[Dict[str, Any]]:
        """Dias com sessoes registradas, do mais recente para o mais antigo."""
        dias: Dict[str, List[str]] = {}
        for arquivo in self.sessions_dir.glob("*/*/*/*/events.jsonl"):
            partes = arquivo.relative_to(self.sessions_dir).parts
            if len(partes) < 5:
                continue
            dia = "-".join(partes[:3])
            dias.setdefault(dia, []).append(partes[3])
        return [
            {"dia": dia, "sessoes": sorted(set(ids)), "total": len(set(ids))}
            for dia, ids in sorted(dias.items(), reverse=True)[:limite]
        ]

    def _commit_event(self, event: Dict[str, Any]) -> None:
        encoded = (
            json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
        ).encode("utf-8")
        with self._file_lock:
            with self.journal_path.open("ab") as journal:
                journal.write(encoded)
                journal.flush()
                os.fsync(journal.fileno())
            self._registrar_na_sessao(event, encoded)
            with self._connection() as connection:
                self._apply_event(connection, event)
            self._compactar_se_grande()

    def _new_event(self, event_type: str, key: str, **payload: Any) -> Dict[str, Any]:
        event = {
            "schema_version": SCHEMA_VERSION,
            "id": str(uuid4()),
            "seq": self._next_seq,
            "time": time.time(),
            "type": event_type,
            "key": str(key),
            **payload,
        }
        self._next_seq += 1
        return event

    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        async with self._async_lock:
            with self._file_lock, self._connection() as connection:
                row = connection.execute(
                    """
                    SELECT value_json
                    FROM memory_records WHERE key = ?
                    """,
                    (str(session_id),),
                ).fetchone()
            if row is None:
                return None
            # TTLs remain recorded for compatibility and future retention jobs,
            # but local durable history is never erased implicitly during read.
            return json.loads(row["value_json"])

    async def set(
        self,
        session_id: str,
        value: Dict[str, Any],
        hot_ttl: int = 1800,
        warm_ttl: int = 604800,
    ) -> None:
        if not isinstance(value, dict):
            raise TypeError("LocalSessionStore only accepts dict values.")
        async with self._async_lock:
            now = time.time()
            event = self._new_event(
                "memory.recorded",
                session_id,
                value=value,
                hot_expires_at=now + max(0, int(hot_ttl)),
                warm_expires_at=now + max(0, int(warm_ttl)),
            )
            self._commit_event(event)

    def inspecionar(self, limite: int = 40) -> Dict[str, Any]:
        """Estado da memoria local para o painel: tamanho, contagens e os
        ultimos eventos. Le do journal, que e a fonte, nao da projecao."""
        eventos = list(self._iter_journal())
        por_tipo: Dict[str, int] = {}
        for e in eventos:
            t = str(e.get("type") or e.get("event") or "?")
            por_tipo[t] = por_tipo.get(t, 0) + 1

        def _tam(caminho: Path) -> int:
            try:
                return caminho.stat().st_size
            except OSError:
                return 0

        recentes = []
        for e in eventos[-limite:][::-1]:
            recentes.append({
                "type": str(e.get("type") or e.get("event") or "?"),
                "key": str(e.get("key") or ""),
                "ts": e.get("ts") or e.get("timestamp"),
            })

        return {
            "backend": self.backend_name,
            "home": str(self.sentury_home),
            "journal_bytes": _tam(self.journal_path),
            "projection_bytes": _tam(self.catalog_path),
            "total_eventos": len(eventos),
            "por_tipo": por_tipo,
            "recentes": recentes,
        }

    async def delete(self, session_id: str) -> None:
        async with self._async_lock:
            self._commit_event(self._new_event("memory.forgotten", session_id))
