"""Orçamento e detecção de repetição para decidir quando o laço deve parar."""
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Repetir uma leitura com a mesma saída indica falta de progresso. As
# categorias vêm do registro; repetir uma escrita pode ter efeito colateral.
_CATEGORIAS_QUE_SO_LEEM = frozenset({"analise", "acao", "conhecimento", "memoria", "skill"})


def idempotentes() -> frozenset:
    """Ferramentas cuja repeticao nao acrescenta nada, derivadas do registro."""
    try:
        from ..tools.registry import TOOL_REGISTRY

        return frozenset(
            nome for nome, meta in TOOL_REGISTRY.items()
            if str(meta.get("categoria") or "") in _CATEGORIAS_QUE_SO_LEEM
        )
    except Exception:
        return frozenset()


def result_fingerprint(result: Any) -> str:
    """Hash estável do resultado, pra reconhecer 'veio a mesma coisa'."""
    try:
        bruto = json.dumps(result, sort_keys=True, default=str, ensure_ascii=False)
    except Exception:
        bruto = repr(result)
    return hashlib.sha1(bruto.encode("utf-8", "replace")).hexdigest()[:16]


class StopReason:
    # Por que o loop encerrou (auditável).
    COMPLETED = "completed"
    USER_INPUT_REQUIRED = "user_input_required"
    BUDGET_EXHAUSTED = "budget_exhausted"
    REPETITION_DETECTED = "repetition_detected"
    TOOL_FAILURE = "tool_failure"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class LoopBudget:
    # Limites duros de uma volta do agente. Defaults conservadores; A1/A3 ajustam.
    max_loops: int = 3
    max_tool_calls: int = 12
    max_total_tokens: int = 120_000
    max_elapsed_ms: float = 120_000.0
    max_failures: int = 3
    max_consecutive_no_progress: int = 2

    @classmethod
    def from_settings(cls, settings: Any) -> "LoopBudget":
        g = lambda name, d: getattr(settings, name, d)
        return cls(
            max_loops=int(g("SENTURY_MAX_LOOPS", cls.max_loops)),
            max_tool_calls=int(g("SENTURY_MAX_TOOL_CALLS", cls.max_tool_calls)),
            max_total_tokens=int(g("SENTURY_MAX_TOTAL_TOKENS", cls.max_total_tokens)),
            max_elapsed_ms=float(g("SENTURY_MAX_ELAPSED_MS", cls.max_elapsed_ms)),
            max_failures=int(g("SENTURY_MAX_FAILURES", cls.max_failures)),
            max_consecutive_no_progress=int(g("SENTURY_MAX_NO_PROGRESS", cls.max_consecutive_no_progress)),
        )


def orcamento_do_turno(settings: Any, funcoes_ativas: Any = ()) -> "LoopBudget":
    """O orçamento das settings, alargado pelo que as ferramentas ligadas no
    turno declaram em `orcamento_do_turno` no tools.yaml: o maior de cada limite.

    Usar o computador ou o navegador é uma tarefa de muitos passos; o teto de
    uma pergunta cortava o trabalho no meio. A parada por falta de progresso
    (tela igual, gesto repetido sem efeito) continua valendo."""
    from dataclasses import fields, replace

    base = LoopBudget.from_settings(settings)
    try:
        from ..tools.registry import TOOL_REGISTRY
        from .funcoes import ferramentas_ligadas

        ligadas = ferramentas_ligadas(funcoes_ativas or [])
    except Exception:
        return base
    maiores: Dict[str, float] = {}
    nomes = {f.name for f in fields(LoopBudget)}
    for ferramenta in ligadas:
        for campo, valor in ((TOOL_REGISTRY.get(ferramenta) or {}).get("orcamento_do_turno") or {}).items():
            if campo in nomes and isinstance(valor, (int, float)):
                maiores[campo] = max(maiores.get(campo, 0), valor)
    alargado = {c: type(getattr(base, c))(max(getattr(base, c), v)) for c, v in maiores.items()}
    return replace(base, **alargado) if alargado else base


@dataclass
class IterationDecision:
    # O que o modelo declara ao fim de uma iteração (contrato do loop).
    status: str  # "continue" | "done" | "ask"
    reason: str = ""
    expected_information_gain: str = "medium"  # low|medium|high
    next_action: Optional[str] = None


@dataclass
class ProgressReport:
    # O ganho REAL verificado pelo harness depois da tool (não a auto-declaração).
    new_evidence_count: int = 0
    resolved_questions: List[str] = field(default_factory=list)
    remaining_gaps: List[str] = field(default_factory=list)

    @property
    def made_progress(self) -> bool:
        return self.new_evidence_count > 0 or bool(self.resolved_questions)


@dataclass
class BudgetTracker:
    # Acompanha o consumo do turno e diz quando/por que parar.
    budget: LoopBudget = field(default_factory=LoopBudget)
    loops: int = 0
    tool_calls: int = 0
    total_tokens: int = 0
    failures: int = 0
    consecutive_no_progress: int = 0
    started_ms: float = field(default_factory=lambda: time.time() * 1000)
    # (tool, hash do resultado) já vistos: pra reconhecer releitura em círculo.
    seen_results: set = field(default_factory=set)
    # Trocas de rota ja tentadas, pela assinatura canonica das duas chamadas.
    rotas_tentadas: set = field(default_factory=set)

    def record_iteration(self) -> None:
        self.loops += 1

    def observe_result(self, tool: str, result: Any) -> bool:
        """Registra o resultado e diz se ele TROUXE algo novo.

        Ferramenta de leitura devolvendo o MESMO conteúdo de antes é
        não-progresso: a chamada "deu certo", então contador de falha não pega,
        mas o agente só releu o que já tinha. É o caso que a eval mostrou
        (analyze_nps chamado duas vezes no mesmo turno).
        """
        if tool not in idempotentes():
            return True
        chave = (tool, result_fingerprint(result))
        if chave in self.seen_results:
            return False
        self.seen_results.add(chave)
        return True

    def record_tool(self, tokens: int = 0, failed: bool = False, progressed: bool = True) -> None:
        self.tool_calls += 1
        self.total_tokens += max(0, int(tokens))
        if failed:
            self.failures += 1
        self.consecutive_no_progress = 0 if progressed else self.consecutive_no_progress + 1

    def volta_sem_efeito(self) -> None:
        """A volta inteira foi de passos repetidos: nada rodou, nada mudou."""
        self.consecutive_no_progress += 1

    def registrar_rota(
        self,
        origem: str,
        argumentos_origem: Optional[Dict[str, Any]],
        destino: str,
        argumentos_destino: Optional[Dict[str, Any]],
    ) -> bool:
        """Registra uma troca; ``True`` somente na primeira tentativa."""
        assinatura = (
            tool_signature(origem, argumentos_origem),
            tool_signature(destino, argumentos_destino),
        )
        if assinatura in self.rotas_tentadas:
            return False
        self.rotas_tentadas.add(assinatura)
        return True

    def rota_bem_sucedida(self, primeira_tentativa: bool) -> None:
        if primeira_tentativa:
            self.consecutive_no_progress = 0

    @property
    def elapsed_ms(self) -> float:
        return time.time() * 1000 - self.started_ms

    def stop_reason(self) -> Optional[str]:
        b = self.budget
        if self.failures >= b.max_failures:
            return StopReason.TOOL_FAILURE
        if self.consecutive_no_progress >= b.max_consecutive_no_progress:
            return StopReason.REPETITION_DETECTED
        if (self.loops >= b.max_loops or self.tool_calls >= b.max_tool_calls
                or self.total_tokens >= b.max_total_tokens or self.elapsed_ms >= b.max_elapsed_ms):
            return StopReason.BUDGET_EXHAUSTED
        return None

    def exhausted(self) -> bool:
        return self.stop_reason() is not None


# Aliases de região pra assinatura de repetição pegar "Sudeste/sudeste/SE".
_REGION_ALIASES = {
    "se": "sudeste", "s": "sul", "ne": "nordeste", "n": "norte",
    "co": "centro-oeste", "centrooeste": "centro-oeste",
}


def _canon_value(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip().lower()
        return _REGION_ALIASES.get(s, s)
    return v


def canonicalize_arguments(args: Optional[Dict[str, Any]]) -> tuple:
    """Assinatura determinística dos args: lowercase/trim, aliases de região,
    chaves ordenadas, sem valores vazios. É o começo determinístico do A3
    (semântica só se a eval mostrar loop que isto não pega)."""
    if not args:
        return ()
    out = []
    for k in sorted(args):
        v = args[k]
        if v in (None, "", [], {}):
            continue
        out.append((str(k).strip().lower(), _canon_value(v)))
    return tuple(out)


def tool_signature(tool: str, args: Optional[Dict[str, Any]]) -> tuple:
    return (str(tool).strip().lower(), canonicalize_arguments(args))
