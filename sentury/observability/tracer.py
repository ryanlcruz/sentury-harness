"""Tracer local em memória: registra cada turno como um TRACE com filhos
(generations de LLM + spans de ferramenta), reconstruído a partir do
`decision_log`/`telemetry`/`tool_results` que o orquestrador já coleta.

Sem dependência externa. Ring buffer com teto: os traces mais antigos caem.
Lido pelo endpoint `/sentury/traces` (aba "Traces" do painel).
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_TRACES = 100          # teto do ring buffer (não vaza memória)
_MAX_TEXT = 1600           # truncamento de payloads (input/output/reasoning)
_MAX_OBS = 600             # truncamento de observação de ferramenta

_traces: Deque[Dict[str, Any]] = deque(maxlen=_MAX_TRACES)
_lock = Lock()


def _clip(value: Any, limit: int = _MAX_TEXT) -> str:
    """Trunca texto e redige data-URI/base64 (não vaza HTML/imagem gigante)."""
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:
        return ""
    if not text:
        return ""
    low = text[:64].lower()
    if "data:" in low and "base64," in text[:120].lower():
        return f"[data-uri redigido · {len(text)} chars]"
    text = text.strip()
    from ..exec.segredos import redigir_segredos

    text = redigir_segredos(text)
    if len(text) > limit:
        return text[:limit].rstrip() + f"… (+{len(text) - limit} chars)"
    return text


def _model_short(model: Any) -> str:
    m = str(model or "").strip()
    if not m:
        return "—"
    # "ultra:deepseek/deepseek-v4-flash" → "ultra · deepseek-v4-flash"
    if ":" in m:
        prov, rest = m.split(":", 1)
        rest = rest.split("/")[-1]
        return f"{prov} · {rest}"
    return m.split("/")[-1]


def record_turn_trace(
    *,
    session_id: str,
    user_id: str,
    user_message: str,
    reply: str,
    decision_log: Optional[Dict[str, Any]] = None,
    telemetry: Optional[Dict[str, Any]] = None,
    tool_results: Optional[List[Dict[str, Any]]] = None,
    deliberation: Optional[Dict[str, Any]] = None,
    mode: str = "auto",
    intent: Optional[str] = None,
    complexity: Optional[str] = None,
) -> None:
    """Monta o trace do turno e empilha no ring buffer. À prova de falha:
    qualquer erro é engolido (nunca afeta a resposta ao usuário)."""
    try:
        dl = decision_log or {}
        tel = telemetry or {}

        generations: List[Dict[str, Any]] = []
        if dl.get("planner_model") or tel.get("planner_ms") is not None:
            generations.append({
                "name": "planner",
                "model": _model_short(dl.get("planner_model")),
                "ms": tel.get("planner_ms"),
                "reasoning": _clip(dl.get("planner_reasoning_summary")),
                "contract": dl.get("planner_contract"),
            })
        if tel.get("council_ms") is not None:
            generations.append({
                "name": "council",
                "model": _model_short(dl.get("council_model")),
                "ms": tel.get("council_ms"),
                "reasoning": _clip(dl.get("council_reasoning_summary")),
            })
        if dl.get("responder_model") or tel.get("responder_ms") is not None:
            generations.append({
                "name": "responder",
                "model": _model_short(dl.get("responder_model")),
                "ms": tel.get("responder_ms"),
                "reasoning": _clip(dl.get("responder_reasoning_summary")),
                "mode": dl.get("responder_mode"),
            })

        spans: List[Dict[str, Any]] = []
        steps = (deliberation or {}).get("steps") if isinstance(deliberation, dict) else None
        if steps:
            for s in steps:
                spans.append({
                    "tool": s.get("tool"),
                    "observation": _clip(s.get("observation"), _MAX_OBS),
                })
        elif tool_results:
            for tr in tool_results:
                spans.append({"tool": tr.get("tool"), "observation": ""})

        trace = {
            "id": uuid.uuid4().hex[:12],
            "ts": time.time(),
            "session_id": session_id,
            "user_id": user_id,
            "mode": mode,
            "intent": intent or dl.get("intent"),
            "complexity": complexity or dl.get("complexity"),
            "input": _clip(user_message),
            "output": _clip(reply),
            "total_ms": tel.get("total_ms") or tel.get("execution_ms"),
            "harness": {
                "proposed_tool": dl.get("proposed_tool"),
                "allowed": dl.get("harness_allowed"),
                "reason": _clip(dl.get("harness_reason"), 240),
            },
            "generations": generations,
            "spans": spans,
        }
        with _lock:
            from ..exec.segredos import sanitizar_dados

            _traces.appendleft(sanitizar_dados(trace))
    except Exception as exc:  # nunca propaga
        logger.debug("Tracer: falha ao registrar trace (ignorada): %s", exc)


def get_recent_traces(limit: int = 50) -> List[Dict[str, Any]]:
    with _lock:
        return list(_traces)[: max(1, min(limit, _MAX_TRACES))]


def clear_traces() -> None:
    with _lock:
        _traces.clear()
