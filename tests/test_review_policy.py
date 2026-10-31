"""Testa a política de review por sinais observáveis."""
from sentury.harness.review_policy import ReviewSignals, must_review, review_reasons


def test_default_nao_obriga():
    assert not must_review(ReviewSignals())
    assert review_reasons(ReviewSignals()) == []


def test_critical_obriga():
    assert must_review(ReviewSignals(complexity="CRITICAL"))
    assert "complexity=CRITICAL" in review_reasons(ReviewSignals(complexity="CRITICAL"))


def test_falha_de_tool_obriga():
    assert must_review(ReviewSignals(tool_failure_count=1))


def test_cada_sinal_obriga_e_lista_motivo():
    casos = [
        ("missing_evidence", ReviewSignals(missing_required_evidence=True)),
        ("conflicting_results", ReviewSignals(conflicting_tool_results=True)),
        ("high_impact", ReviewSignals(high_impact_recommendation=True)),
        ("insufficient_coverage", ReviewSignals(insufficient_source_coverage=True)),
        ("unverified_claims", ReviewSignals(unverified_claims=True)),
    ]
    for motivo, sinais in casos:
        assert must_review(sinais)
        assert motivo in review_reasons(sinais)


def test_multiplos_sinais_somam_motivos():
    s = ReviewSignals(complexity="CRITICAL", tool_failure_count=2, unverified_claims=True)
    assert set(review_reasons(s)) == {"complexity=CRITICAL", "tool_failure", "unverified_claims"}
