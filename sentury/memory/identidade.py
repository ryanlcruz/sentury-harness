"""Identidade da instalação, em `~/.sentury/identidade.json`.

`localStorage` é por origem, então um id sorteado no navegador vira um usuário
novo a cada porta ou host. Aqui a máquina é dona e o navegador consulta.

Com login, este arquivo passa a ser o fallback do anônimo.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .local_session_store import default_sentury_home
from .session_index import index_key

logger = logging.getLogger(__name__)

ARQUIVO = "identidade.json"
PREFIXO = "local-"
PASTA_TESTES = "Testes do desenvolvimento"


def caminho(sentury_home: str = "") -> Path:
    return default_sentury_home(sentury_home) / ARQUIVO


def _ler(arquivo: Path) -> str:
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str(dados.get("user_id") or "").strip() if isinstance(dados, dict) else ""


def _gravar(arquivo: Path, user_id: str, origem: str) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(
        json.dumps({"user_id": user_id, "origem": origem, "criado_em": time.time()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _todos_os_indices(store: Any) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """Todo índice de sessão do banco, com o dono de cada um.

    A chave é o hash do `user_id`; o dono só aparece dentro do valor.
    """
    achados: List[Tuple[str, List[Dict[str, Any]]]] = []
    try:
        import sqlite3

        conexao = sqlite3.connect(str(store.catalog_path), timeout=10.0)
        try:
            linhas = conexao.execute(
                "SELECT value_json FROM memory_records WHERE key LIKE ?",
                ("__sentury_session_index__%",),
            ).fetchall()
        finally:
            conexao.close()
    except Exception as exc:
        logger.debug("Nao consegui varrer os indices de sessao: %s", exc)
        return achados

    for (valor,) in linhas:
        try:
            dados = json.loads(valor)
        except Exception:
            continue
        if not isinstance(dados, dict):
            continue
        dono = str(dados.get("user_id") or "").strip()
        sessoes = [s for s in (dados.get("sessions") or []) if isinstance(s, dict)]
        if dono and sessoes:
            achados.append((dono, sessoes))
    return achados


def _sorteado(user_id: str) -> bool:
    """Id que o navegador inventou, e não um nome que alguém escolheu."""
    return user_id.startswith(PREFIXO) and len(user_id) > len(PREFIXO) + 20


async def _trocar_dono_do_arquivo(store: Any, session_id: str, destino: str) -> None:
    """Sem isto a conversa aparece na lista e abre vazia: `load` compara o dono
    do arquivo com o do índice e recusa quando diferem."""
    from .session_index import archive_key

    for chave in (archive_key(session_id), session_id):
        try:
            bruto = await store.get(chave)
        except Exception:
            continue
        if not isinstance(bruto, dict) or bruto.get("user_id") == destino:
            continue
        await store.set(chave, {**bruto, "user_id": destino},
                        hot_ttl=2592000, warm_ttl=2592000)


async def unificar(store: Any, destino: str) -> int:
    """Junta sob `destino` as conversas de todas as identidades.

    Conversa vinda de id nomeado à mão é teste de desenvolvimento: entra
    marcada, para cair numa pasta à parte.
    """
    espalhados = [(dono, ses) for dono, ses in _todos_os_indices(store) if dono != destino]
    if not espalhados:
        return 0

    try:
        atual = await store.get(index_key(destino))
    except Exception:
        atual = None
    reunidas: Dict[str, Dict[str, Any]] = {
        str(s.get("session_id")): s
        for s in ((atual or {}).get("sessions") or [])
        if isinstance(s, dict) and s.get("session_id")
    }

    adotadas = 0
    para_a_pasta: List[str] = []
    for dono, sessoes in espalhados:
        de_teste = not _sorteado(dono)
        for sessao in sessoes:
            sid = str(sessao.get("session_id") or "")
            if not sid or sid in reunidas:
                continue
            # O dono muda junto: a sessão é lida por `user_id`.
            reunidas[sid] = {**sessao, "user_id": destino, "origem_id": dono}
            await _trocar_dono_do_arquivo(store, sid, destino)
            if de_teste:
                para_a_pasta.append(sid)
            adotadas += 1

    if not adotadas:
        return 0

    ordenadas = sorted(reunidas.values(),
                       key=lambda s: float(s.get("updated_at") or 0), reverse=True)
    await store.set(index_key(destino), {"user_id": destino, "sessions": ordenadas},
                    hot_ttl=2592000, warm_ttl=2592000)
    if para_a_pasta:
        from . import preferencias_ui

        await preferencias_ui.marcar(store, destino, para_a_pasta, PASTA_TESTES)
    logger.info("Identidade '%s' adotou %d conversas que estavam orfas.", destino, adotadas)
    return adotadas


async def resolver(store: Any = None, sentury_home: str = "") -> str:
    """A identidade desta instalação, criando-a na primeira vez.

    Herda o `local-*` com mais conversa, para o histórico não sumir da lista.
    """
    arquivo = caminho(sentury_home)
    existente = _ler(arquivo)
    if existente:
        return existente

    herdado, origem = "", "nova"
    if store is not None:
        candidatos = [c for c in _todos_os_indices(store) if _sorteado(c[0])]
        if candidatos:
            herdado = max(
                candidatos,
                key=lambda item: (
                    len(item[1]),
                    max((float(s.get("updated_at") or 0) for s in item[1]), default=0.0),
                ),
            )[0]
            origem = "herdada"

    user_id = herdado or f"{PREFIXO}{uuid.uuid4()}"
    _gravar(arquivo, user_id, origem)
    if store is not None:
        try:
            await unificar(store, user_id)
        except Exception as exc:
            logger.warning("Nao consegui reunir as conversas espalhadas: %s", exc)
    return user_id


def definir(user_id: str, sentury_home: str = "") -> Optional[str]:
    """Troca a identidade da máquina à mão. Vazio não apaga o que existe."""
    escolhido = str(user_id or "").strip()
    if not escolhido:
        return None
    _gravar(caminho(sentury_home), escolhido, "manual")
    return escolhido


__all__ = ["ARQUIVO", "PASTA_TESTES", "caminho", "definir", "resolver", "unificar"]
