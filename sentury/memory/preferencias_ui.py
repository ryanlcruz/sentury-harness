"""Arrumação da barra lateral: pastas, fixados, recolhidos.

Fica no store junto das conversas. No `localStorage` sumiria a cada troca de
origem: porta, host ou empacotamento em Tauri.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PREFIXO = "__sentury_ui_prefs__"
_TTL = 60 * 60 * 24 * 365


def chave(user_id: str) -> str:
    digest = hashlib.sha256((user_id or "anon").encode("utf-8", "ignore")).hexdigest()[:32]
    return f"{_PREFIXO}:{digest}"


def _limpo(valor: Any, maximo: int = 40) -> str:
    return str(valor or "").strip()[:maximo]


def vazio() -> Dict[str, Any]:
    return {"pastas": [], "sessoes": {}, "raiz_recolhida": False}


async def ler(store: Any, user_id: str) -> Dict[str, Any]:
    try:
        bruto = await store.get(chave(user_id))
    except Exception as exc:
        logger.debug("Preferencias de interface ilegiveis: %s", exc)
        return vazio()
    if not isinstance(bruto, dict):
        return vazio()
    pastas = [p for p in (bruto.get("pastas") or []) if isinstance(p, dict) and p.get("id")]
    sessoes = bruto.get("sessoes") if isinstance(bruto.get("sessoes"), dict) else {}
    return {"pastas": pastas, "sessoes": sessoes,
            "raiz_recolhida": bool(bruto.get("raiz_recolhida"))}


async def gravar(store: Any, user_id: str, dados: Dict[str, Any]) -> Dict[str, Any]:
    limpo = {
        "pastas": [
            {"id": _limpo(p.get("id"), 64),
             "nome": _limpo(p.get("nome")) or "Pasta",
             "recolhida": bool(p.get("recolhida"))}
            for p in (dados.get("pastas") or []) if isinstance(p, dict) and p.get("id")
        ],
        "sessoes": {
            str(sid)[:128]: {
                "pinned": bool((v or {}).get("pinned")),
                "pasta": _limpo((v or {}).get("pasta"), 64),
            }
            for sid, v in (dados.get("sessoes") or {}).items()
            if isinstance(v, dict)
        },
        "raiz_recolhida": bool(dados.get("raiz_recolhida")),
        "atualizado_em": time.time(),
    }
    await store.set(chave(user_id), limpo, hot_ttl=_TTL, warm_ttl=_TTL)
    return limpo


async def garantir_pasta(store: Any, user_id: str, nome: str) -> Optional[str]:
    """Devolve o id da pasta com esse nome, criando-a se preciso."""
    alvo = _limpo(nome)
    if not alvo:
        return None
    prefs = await ler(store, user_id)
    for pasta in prefs["pastas"]:
        if str(pasta.get("nome", "")).strip().lower() == alvo.lower():
            return str(pasta["id"])
    novo = f"pasta-{hashlib.sha256(alvo.encode('utf-8')).hexdigest()[:8]}"
    prefs["pastas"].append({"id": novo, "nome": alvo, "recolhida": False})
    await gravar(store, user_id, prefs)
    return novo


async def marcar(store: Any, user_id: str, sessoes: List[str], pasta_nome: str) -> int:
    """Joga um punhado de conversas numa pasta pelo nome dela."""
    pasta_id = await garantir_pasta(store, user_id, pasta_nome)
    if not pasta_id:
        return 0
    prefs = await ler(store, user_id)
    tocadas = 0
    for sid in sessoes:
        atual = prefs["sessoes"].get(sid) or {}
        if atual.get("pasta"):
            continue
        prefs["sessoes"][sid] = {**atual, "pasta": pasta_id}
        tocadas += 1
    if tocadas:
        await gravar(store, user_id, prefs)
    return tocadas


__all__ = ["chave", "garantir_pasta", "gravar", "ler", "marcar", "vazio"]
