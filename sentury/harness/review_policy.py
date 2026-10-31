"""Política de review: quando o harness OBRIGA revisão.

Governança: review é model-callable **e** policy-forced. A política decide por
sinais OBSERVÁVEIS do harness, nunca pela autoconfiança da LLM (justo na
resposta confiante-e-errada ela não pediria review). Fundação (funções puras);
o wiring no fluxo é A2c/A3.
"""
from dataclasses import dataclass
from typing import List


@dataclass
class ReviewSignals:
    complexity: str = "STANDARD"
    tool_failure_count: int = 0
    missing_required_evidence: bool = False
    conflicting_tool_results: bool = False
    high_impact_recommendation: bool = False
    insufficient_source_coverage: bool = False
    unverified_claims: bool = False


_RULES = [
    ("complexity=CRITICAL", lambda s: s.complexity == "CRITICAL"),
    ("tool_failure", lambda s: s.tool_failure_count > 0),
    ("missing_evidence", lambda s: s.missing_required_evidence),
    ("conflicting_results", lambda s: s.conflicting_tool_results),
    ("high_impact", lambda s: s.high_impact_recommendation),
    ("insufficient_coverage", lambda s: s.insufficient_source_coverage),
    ("unverified_claims", lambda s: s.unverified_claims),
]


def review_reasons(s: ReviewSignals) -> List[str]:
    """Motivos observáveis que obrigam review (auditável)."""
    return [name for name, rule in _RULES if rule(s)]


def must_review(s: ReviewSignals) -> bool:
    return bool(review_reasons(s))
