"""Subagentes: olhares independentes sobre a evidência verificada do turno.

O modelo chama pela ferramenta `subagentes` quando o trabalho pede; cada um
lê só os resultados verificados da sessão, sem ferramentas, e o parecer volta
para quem chamou juntar na mesma volta."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..context import PromptContextEngine
from ..llm.action_parser import extract_plain_text


# A marca de capacidade permite à interface escolher cor e ícone por papel.
_ROLES = (
    (
        "evidence_analyst",
        "Audit the metrics, periods, sample sizes and comparisons. Flag contradictions or missing evidence.",
        "researcher",
        "Auditando a evidencia",
    ),
    (
        "operations_critic",
        "Assess operational causes, risks and trade-offs. Separate measured causes from hypotheses.",
        "reviewer",
        "Criticando causas e riscos",
    ),
    (
        "action_specialist",
        "Prioritize grounded actions, controls and acceptance criteria without inventing targets or owners.",
        "planner",
        "Priorizando acoes",
    ),
)


# Instrução genérica para um papel que o usuário inventou na hora. Os papéis
# fixos existem porque cobrem o caminho comum, não porque são os únicos que
# fazem sentido: quem conhece o problema às vezes sabe de um recorte melhor.
INSTRUCAO_LIVRE = (
    "Analyze the evidence strictly from this angle: {papel}. Say what this angle "
    "reveals and what it cannot answer with the evidence at hand."
)


class ExplicitSubagentCoordinator:
    """Executa subagentes analíticos isolados quando o modelo pede.

    Eles recebem contexto limitado e devolvem resumos ao agente principal, sem
    ferramentas, memória própria ou capacidade de delegar novamente.
    """

    def __init__(
        self,
        provider: Any,
        *,
        context_engine: Optional[PromptContextEngine] = None,
        enabled: bool = True,
        default_count: int = 2,
        max_count: int = 3,
        timeout_seconds: float = 35.0,
        max_context_chars: int = 12_000,
        max_summary_chars: int = 2_400,
    ) -> None:
        self.provider = provider
        self.context_engine = context_engine
        self.enabled = bool(enabled)
        self.default_count = max(1, int(default_count))
        self.max_count = max(1, int(max_count))
        self.timeout_seconds = max(0.01, float(timeout_seconds))
        self.max_context_chars = max(1_000, int(max_context_chars))
        self.max_summary_chars = max(400, int(max_summary_chars))

    def _grounded_context(self, state: Any) -> str:
        results = getattr(state, "results", {})
        filters = getattr(state, "filtros", {})
        records: List[Dict[str, Any]] = []
        if isinstance(results, dict):
            for result_id, record in sorted(results.items(), reverse=True)[:8]:
                if not isinstance(record, dict):
                    continue
                records.append({
                    "result_id": result_id,
                    "tool": record.get("tool"),
                    "arguments": record.get("arguments"),
                    "summary": record.get("summary"),
                    "row_count": record.get("row_count"),
                })
        payload = {
            "active_filters": filters if isinstance(filters, dict) else {},
            "verified_session_results": records,
        }
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        return rendered[: self.max_context_chars]

    async def _complete(self, messages: List[Dict[str, str]]) -> str:
        try:
            return await self.provider.complete(
                messages,
                temperature=0.1,
                complexity="SUBAGENT",
                profile="analysis",
            )
        except TypeError:
            try:
                return await self.provider.complete(messages, temperature=0.1, complexity="SUBAGENT")
            except TypeError:
                try:
                    return await self.provider.complete(messages, temperature=0.1)
                except TypeError:
                    return await self.provider.complete(messages)

    def _trim(self, value: Any) -> str:
        text = extract_plain_text(str(value or "")).strip()
        if len(text) <= self.max_summary_chars:
            return text
        clipped = text[: self.max_summary_chars]
        boundary = max(clipped.rfind(". "), clipped.rfind("\n"))
        if boundary >= self.max_summary_chars // 2:
            clipped = clipped[: boundary + 1]
        return clipped.rstrip() + "\n[summary truncated]"

    async def _run_one(
        self,
        role: str,
        role_instruction: str,
        user_message: str,
        evidence: str,
        capability: str = "core",
        titulo: str = "",
        emit: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        base_prompt = (
            "You are a focused, read-only Sentury subagent. Analyze only the VERIFIED "
            "EVIDENCE supplied below. If the evidence is insufficient, identify the exact gap. "
            "Return a compact summary for the parent, not hidden chain-of-thought.\n\n"
            # Cada restrição explica o risco que evita para não ser removida sem critério.
            "HARD LIMITS — and why each one exists:\n"
            "- You CANNOT delegate. Recursive delegation makes cost and latency unbounded.\n"
            "- You CANNOT call tools or run code. Your job is judgement over evidence already "
            "gathered; fetching more would duplicate work the parent already did.\n"
            "- You CANNOT talk to the user or ask questions. Only the parent owns that channel; "
            "a child asking would interleave with the parent's own turn.\n"
            "- You CANNOT write to memory or skills. Several children writing to shared state "
            "race with each other and with the parent.\n"
            "- You CANNOT invent numbers, targets, owners or deadlines. If it is not in the "
            "evidence, say it is missing — a fabricated number here reaches the user as if the "
            "parent had verified it.\n\n"
            f"ROLE: {role}\n{role_instruction}"
        )
        if self.context_engine:
            base_prompt = self.context_engine.build_prompt(base_prompt, "subagent")
        messages = [
            {"role": "system", "content": base_prompt},
            {"role": "user", "content": f"PARENT REQUEST:\n{user_message}\n\nVERIFIED EVIDENCE:\n{evidence}"},
        ]
        # Subagente rodava invisivel: o turno parava e ninguem sabia em quem.
        # Agora cada um abre e fecha o proprio passo, com papel e duracao.
        passo_id = f"sub:{role}"
        inicio = time.time()

        def _passo(evento: Dict[str, Any]) -> None:
            if emit:
                try:
                    emit(evento)
                except Exception:
                    pass

        _passo({
            "type": "tool_start",
            "id": passo_id,
            "tool": role,
            "kind": capability,
            "title": titulo or role,
        })

        def _fechar(status: str) -> None:
            _passo({
                "type": "tool_complete",
                "id": passo_id,
                "status": status,
                "duration_ms": max(1, int((time.time() - inicio) * 1000)),
            })

        try:
            raw = await asyncio.wait_for(self._complete(messages), timeout=self.timeout_seconds)
            summary = self._trim(raw)
            if not summary:
                _fechar("skipped")
                return {"role": role, "capability": capability, "status": "empty", "summary": ""}
            _fechar("ok")
            return {"role": role, "capability": capability, "status": "completed", "summary": summary}
        except asyncio.TimeoutError:
            _fechar("error")
            return {"role": role, "capability": capability, "status": "timeout", "summary": ""}
        except Exception as exc:
            _fechar("error")
            return {
                "role": role, "capability": capability, "status": "failed",
                "summary": "", "error": type(exc).__name__,
            }

    async def consultar(
        self,
        pedido: str,
        state: Any,
        *,
        papeis: Sequence[str] = (),
        quantos: int = 0,
        emit: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Os pareceres sobre `pedido`: um por papel nomeado ou, sem papel, os padrão."""
        nomeados = [" ".join(str(p).split())[:60] for p in papeis if str(p).strip()][: self.max_count]
        if nomeados:
            # Papel inventado entra com a marca do Sentury: não é nenhum dos
            # especialistas conhecidos, e adivinhar um pelo nome do papel só
            # funcionaria numa língua.
            selected = [(papel, INSTRUCAO_LIVRE.format(papel=papel), "core", f"Olhando por: {papel}")
                        for papel in nomeados]
        else:
            selected = list(_ROLES[: min(max(1, int(quantos or self.default_count)), self.max_count)])
        evidence = self._grounded_context(state)
        results = await asyncio.gather(*(
            self._run_one(role, instruction, pedido, evidence, capability, titulo, emit)
            for role, instruction, capability, titulo in selected
        ))
        completed = [item for item in results if item.get("status") == "completed" and item.get("summary")]
        return {
            "requested": True,
            "requested_count": len(selected),
            "completed_count": len(completed),
            "results": results,
        }
