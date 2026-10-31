"""Telemetria de INTERVENÇÃO do Harness (prevenção de bugs/alucinação por medição).

Toda vez que o harness precisa CONSERTAR ou REJEITAR o que o modelo produziu
(bridge de SQL, coerção de HTML, guard de grounding, erro de tool descartado…),
registramos aqui. Assim dá pra ver a TAXA e ONDE os problemas acontecem (e
comparar por tier (flash vs pro vs auto)) em vez de adivinhar.

Mesma filosofia do tracer: em memória, à prova de falha (nunca quebra o turno),
com teto de memória, sem phone-home. Lido por um endpoint local.
"""
from __future__ import annotations

import time
from collections import Counter, deque
from typing import Any, Deque, Dict, Optional

_MAX_EVENTS = 300
_events: Deque[Dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_counts: Counter = Counter()        # kind -> n
_counts_tier: Counter = Counter()   # "kind|tier" -> n


def _active_tier() -> str:
    """Tier de inteligência ativo NESTE request (auto / ultra=flash / ultra_max=pro).
    Vem do contextvar do Ultra, que é herdado pela task do turno: então funciona
    em qualquer ponto de interceptação (orchestrator, sandbox, catalog)."""
    try:
        from robinbandit.sentury import active_ultra_tier
        return active_ultra_tier() or "auto"
    except Exception:
        return "auto"


def record_intervention(kind: str, detail: Optional[Any] = None) -> None:
    """Registra uma intervenção do harness. À prova de falha: nunca lança."""
    try:
        from ..exec.segredos import redigir_segredos
        tier = _active_tier()
        _counts[kind] += 1
        _counts_tier[f"{kind}|{tier}"] += 1
        _events.append({
            "kind": kind,
            "tier": tier,
            "detail": (redigir_segredos(str(detail))[:200] if detail is not None else None),
            "ts": time.time(),
        })
    except Exception:
        pass


def get_interventions() -> Dict[str, Any]:
    by_kind_tier: Dict[str, Dict[str, int]] = {}
    for chave, n in _counts_tier.items():
        kind, tier = chave.split("|", 1)
        by_kind_tier.setdefault(kind, {})[tier] = n
    return {
        "total": sum(_counts.values()),
        "by_kind": dict(_counts),
        "by_kind_tier": by_kind_tier,
        "recent": list(_events)[-60:],
    }


def clear_interventions() -> None:
    _events.clear()
    _counts.clear()
    _counts_tier.clear()
