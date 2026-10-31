"""Journal duravel para a compactacao de contexto.

O modelo produz o resumo; este modulo o grava *antes* de o chamador trocar o
``AnalysisState`` em memoria. Se o processo cair nesse intervalo, o proximo
turno encontra o mesmo ``contexto_hash`` e reaproveita o resultado sem chamar o
modelo outra vez.

O SQLite tambem guarda uma lease por sessao. A lease evita duas compactacoes
concorrentes do mesmo snapshot e expira sozinha quando o dono morre.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Optional, Tuple
from uuid import uuid4


SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)
_TAREFAS_PROTEGIDAS: set[asyncio.Task] = set()


class CompactacaoEmAndamento(RuntimeError):
    """Outra execucao ainda possui a lease desta sessao."""


class LeasePerdida(RuntimeError):
    """O chamador tentou gravar sem possuir uma lease valida."""


@dataclass(frozen=True)
class LeaseCompactacao:
    sessao_id: str
    dono: str
    expira_em: float


@dataclass(frozen=True)
class CompactacaoGravada:
    id: str
    sessao_id: str
    contexto_hash: str
    historico: List[Dict[str, Any]]
    estado_conversa: Dict[str, Any]
    criada_em: float
    aplicada_em: Optional[float]


@dataclass(frozen=True)
class ViabilidadeDoAuxiliar:
    cabe: bool
    limiar_efetivo: int
    aviso: Optional[str] = None


def verificar_janela_auxiliar(
    janela_auxiliar: int,
    limiar_principal: int,
    *,
    nome_auxiliar: str = "modelo auxiliar",
) -> ViabilidadeDoAuxiliar:
    """Compara a janela do sumarizador com o ponto em que ele sera chamado.

    O startup pode mostrar ``aviso`` e usar ``limiar_efetivo``. A funcao nao
    conhece provedores: ela recebe os limites ja resolvidos pelo roteador.
    """

    janela = int(janela_auxiliar)
    limiar = int(limiar_principal)
    if janela <= 0 or limiar <= 0:
        raise ValueError("janela e limiar precisam ser positivos")
    if janela >= limiar:
        return ViabilidadeDoAuxiliar(True, limiar)
    return ViabilidadeDoAuxiliar(
        False,
        janela,
        (
            f"A janela de {janela:,} tokens de {nome_auxiliar} nao comporta "
            f"o limiar de compactacao de {limiar:,} tokens; use um modelo "
            f"maior ou reduza o limiar para no maximo {janela:,}."
        ),
    )


def hash_do_contexto(mensagens: List[Dict[str, Any]]) -> str:
    """Identidade estavel do snapshot enviado ao modelo de compactacao."""

    serializado = json.dumps(
        mensagens,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def novo_dono() -> str:
    return (
        f"pid={os.getpid()}:thread={threading.get_ident()}:"
        f"nonce={uuid4().hex[:10]}"
    )


def caminho_padrao() -> Path:
    from ..config import settings
    from ..memory.local_session_store import default_sentury_home

    raiz = default_sentury_home(str(getattr(settings, "SENTURY_HOME", "") or ""))
    return raiz / "state" / "compactacoes.db"


class DiarioDeCompactacao:
    """Persistencia transacional de resultados e leases de compactacao."""

    def __init__(
        self,
        caminho: str | Path | None = None,
        *,
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self.caminho = Path(caminho) if caminho is not None else caminho_padrao()
        self.caminho = self.caminho.expanduser().resolve()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._relogio = relogio
        self._inicializar()

    def _conectar(self) -> sqlite3.Connection:
        conexao = sqlite3.connect(str(self.caminho), timeout=10.0)
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.execute("PRAGMA synchronous=FULL")
        conexao.execute("PRAGMA busy_timeout=10000")
        return conexao

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        conexao = self._conectar()
        try:
            yield conexao
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def _inicializar(self) -> None:
        with self._conexao() as conexao:
            conexao.executescript(
                """
                CREATE TABLE IF NOT EXISTS compactacoes (
                    id TEXT PRIMARY KEY,
                    sessao_id TEXT NOT NULL,
                    contexto_hash TEXT NOT NULL,
                    historico_json TEXT NOT NULL,
                    estado_conversa_json TEXT NOT NULL,
                    criada_em REAL NOT NULL,
                    aplicada_em REAL,
                    schema_version INTEGER NOT NULL,
                    UNIQUE(sessao_id, contexto_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_compactacoes_sessao_criada
                    ON compactacoes(sessao_id, criada_em DESC);
                CREATE TABLE IF NOT EXISTS leases_compactacao (
                    sessao_id TEXT PRIMARY KEY,
                    dono TEXT NOT NULL,
                    expira_em REAL NOT NULL
                );
                """
            )

    def adquirir_lease(
        self,
        sessao_id: str,
        dono: str,
        *,
        ttl_segundos: float = 300.0,
    ) -> Optional[LeaseCompactacao]:
        sessao = str(sessao_id or "").strip()
        proprietario = str(dono or "").strip()
        ttl = float(ttl_segundos)
        if not sessao or not proprietario:
            raise ValueError("sessao_id e dono sao obrigatorios")
        if ttl <= 0:
            raise ValueError("ttl_segundos precisa ser positivo")
        agora = float(self._relogio())
        expira = agora + ttl
        conexao = self._conectar()
        try:
            conexao.execute("BEGIN IMMEDIATE")
            cursor = conexao.execute(
                """
                INSERT INTO leases_compactacao(sessao_id, dono, expira_em)
                VALUES (?, ?, ?)
                ON CONFLICT(sessao_id) DO UPDATE SET
                    dono = excluded.dono,
                    expira_em = excluded.expira_em
                WHERE leases_compactacao.expira_em <= ?
                   OR leases_compactacao.dono = excluded.dono
                """,
                (sessao, proprietario, expira, agora),
            )
            conexao.commit()
            if cursor.rowcount != 1:
                return None
            return LeaseCompactacao(sessao, proprietario, expira)
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def renovar_lease(
        self,
        lease: LeaseCompactacao,
        *,
        ttl_segundos: float = 300.0,
    ) -> Optional[LeaseCompactacao]:
        ttl = float(ttl_segundos)
        if ttl <= 0:
            raise ValueError("ttl_segundos precisa ser positivo")
        agora = float(self._relogio())
        expira = agora + ttl
        with self._conexao() as conexao:
            cursor = conexao.execute(
                """
                UPDATE leases_compactacao SET expira_em = ?
                WHERE sessao_id = ? AND dono = ? AND expira_em > ?
                """,
                (expira, lease.sessao_id, lease.dono, agora),
            )
        if cursor.rowcount != 1:
            return None
        return LeaseCompactacao(lease.sessao_id, lease.dono, expira)

    def liberar_lease(self, lease: LeaseCompactacao) -> bool:
        with self._conexao() as conexao:
            cursor = conexao.execute(
                "DELETE FROM leases_compactacao WHERE sessao_id = ? AND dono = ?",
                (lease.sessao_id, lease.dono),
            )
        return cursor.rowcount == 1

    @contextmanager
    def lease(
        self,
        sessao_id: str,
        *,
        dono: Optional[str] = None,
        ttl_segundos: float = 300.0,
    ) -> Iterator[LeaseCompactacao]:
        obtida = self.adquirir_lease(
            sessao_id, dono or novo_dono(), ttl_segundos=ttl_segundos
        )
        if obtida is None:
            raise CompactacaoEmAndamento(
                f"a sessao {sessao_id!r} ja esta sendo compactada"
            )
        try:
            yield obtida
        finally:
            self.liberar_lease(obtida)

    def salvar(
        self,
        lease: LeaseCompactacao,
        contexto_hash: str,
        historico: List[Dict[str, Any]],
        estado_conversa: Dict[str, Any],
    ) -> CompactacaoGravada:
        """Grava de forma sincrona logo apos o ``await`` do modelo.

        A chamada nao contem outro ``await``: depois que o modelo devolve, o
        resultado chega ao disco antes de o task poder ser cancelado no proximo
        ponto cooperativo.
        """

        identidade = str(contexto_hash or "").strip()
        if not identidade:
            raise ValueError("contexto_hash obrigatorio")
        historico_json = json.dumps(historico, ensure_ascii=False, default=str)
        estado_json = json.dumps(estado_conversa, ensure_ascii=False, default=str)
        agora = float(self._relogio())
        registro_id = uuid4().hex

        conexao = self._conectar()
        try:
            conexao.execute("BEGIN IMMEDIATE")
            posse = conexao.execute(
                """
                SELECT 1 FROM leases_compactacao
                WHERE sessao_id = ? AND dono = ? AND expira_em > ?
                """,
                (lease.sessao_id, lease.dono, agora),
            ).fetchone()
            if posse is None:
                raise LeasePerdida(
                    f"lease expirada ou pertencente a outro dono: {lease.sessao_id}"
                )
            conexao.execute(
                """
                INSERT INTO compactacoes(
                    id, sessao_id, contexto_hash, historico_json,
                    estado_conversa_json, criada_em, aplicada_em, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(sessao_id, contexto_hash) DO NOTHING
                """,
                (
                    registro_id,
                    lease.sessao_id,
                    identidade,
                    historico_json,
                    estado_json,
                    agora,
                    SCHEMA_VERSION,
                ),
            )
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()
        recuperada = self.recuperar(lease.sessao_id, identidade)
        if recuperada is None:  # pragma: no cover - invariante do INSERT
            raise RuntimeError("compactacao foi gravada mas nao pode ser relida")
        return recuperada

    async def obter_ou_produzir(
        self,
        sessao_id: str,
        contexto_hash: str,
        produtor: Callable[
            [],
            Awaitable[Tuple[List[Dict[str, Any]], Dict[str, Any]]],
        ],
        *,
        dono: Optional[str] = None,
        ttl_segundos: float = 300.0,
    ) -> CompactacaoGravada:
        """Recupera do disco ou produz uma vez, protegendo o trabalho do stop.

        ``produtor`` deve chamar o modelo e devolver ``(novo_historico,
        estado_conversa)``. O task interno e protegido com ``asyncio.shield``:
        cancelar a requisicao devolve o controle ao usuario, mas nao cancela a
        compactacao. Assim que o modelo retorna, ``salvar`` roda de forma
        sincrona antes de qualquer novo ponto de cancelamento.
        """

        existente = self.recuperar(sessao_id, contexto_hash)
        if existente is not None:
            return existente

        lease = self.adquirir_lease(
            sessao_id, dono or novo_dono(), ttl_segundos=ttl_segundos
        )
        if lease is None:
            raise CompactacaoEmAndamento(
                f"a sessao {sessao_id!r} ja esta sendo compactada"
            )

        async def _trabalho() -> CompactacaoGravada:
            try:
                # Double check depois da lease: outro processo pode ter gravado
                # entre a primeira leitura e a nossa aquisicao.
                pronta = self.recuperar(sessao_id, contexto_hash)
                if pronta is not None:
                    return pronta
                historico, estado = await produtor()
                return self.salvar(lease, contexto_hash, historico, estado)
            finally:
                self.liberar_lease(lease)

        tarefa = asyncio.create_task(_trabalho())
        _TAREFAS_PROTEGIDAS.add(tarefa)

        def _concluida(finalizada: asyncio.Task) -> None:
            _TAREFAS_PROTEGIDAS.discard(finalizada)
            if finalizada.cancelled():
                return
            erro = finalizada.exception()
            if erro is not None:
                logger.warning(
                    "Compactacao protegida falhou para a sessao %s: %s",
                    sessao_id,
                    erro,
                )

        tarefa.add_done_callback(_concluida)
        return await asyncio.shield(tarefa)

    def recuperar(
        self,
        sessao_id: str,
        contexto_hash: str,
    ) -> Optional[CompactacaoGravada]:
        with self._conexao() as conexao:
            linha = conexao.execute(
                """
                SELECT * FROM compactacoes
                WHERE sessao_id = ? AND contexto_hash = ?
                LIMIT 1
                """,
                (str(sessao_id), str(contexto_hash)),
            ).fetchone()
        return self._da_linha(linha) if linha is not None else None

    def mais_recente(self, sessao_id: str) -> Optional[CompactacaoGravada]:
        with self._conexao() as conexao:
            linha = conexao.execute(
                """
                SELECT * FROM compactacoes
                WHERE sessao_id = ? ORDER BY criada_em DESC LIMIT 1
                """,
                (str(sessao_id),),
            ).fetchone()
        return self._da_linha(linha) if linha is not None else None

    def marcar_aplicada(self, registro_id: str) -> bool:
        with self._conexao() as conexao:
            cursor = conexao.execute(
                """
                UPDATE compactacoes
                SET aplicada_em = COALESCE(aplicada_em, ?)
                WHERE id = ?
                """,
                (float(self._relogio()), str(registro_id)),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _da_linha(linha: sqlite3.Row) -> CompactacaoGravada:
        return CompactacaoGravada(
            id=str(linha["id"]),
            sessao_id=str(linha["sessao_id"]),
            contexto_hash=str(linha["contexto_hash"]),
            historico=json.loads(linha["historico_json"]),
            estado_conversa=json.loads(linha["estado_conversa_json"]),
            criada_em=float(linha["criada_em"]),
            aplicada_em=(
                float(linha["aplicada_em"])
                if linha["aplicada_em"] is not None
                else None
            ),
        )


__all__ = [
    "CompactacaoEmAndamento",
    "CompactacaoGravada",
    "DiarioDeCompactacao",
    "LeaseCompactacao",
    "LeasePerdida",
    "ViabilidadeDoAuxiliar",
    "hash_do_contexto",
    "novo_dono",
    "verificar_janela_auxiliar",
]
