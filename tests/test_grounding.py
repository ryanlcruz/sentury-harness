from sentury.harness.grounding import evidence_text, find_ungrounded
from sentury.harness.state import AnalysisState


def test_currency_is_always_ungrounded_when_no_money_in_evidence():
    evidencia = "{'nps': -30.1, 'volume': 1000}"
    achados = find_ungrounded("A economia seria de R$ 100.000,00 por mês.", evidencia)
    assert achados["currency"]


def test_decimal_present_in_evidence_is_grounded():
    evidencia = "{'nps': -30.1, 'pct_em_risco': 49.4}"
    achados = find_ungrounded("O NPS é de -30,1 com 49,4% em risco.", evidencia)
    assert achados["decimals"] == []


def test_decimal_absent_from_evidence_is_flagged():
    evidencia = "{'nps': -30.1}"
    achados = find_ungrounded("A satisfação subiu para 4,5 em 5.", evidencia)
    assert 4.5 in achados["decimals"]


def test_evidence_text_collects_system_blocks_and_summaries():
    state = AnalysisState.new("s", "u")
    state.history.append({"role": "system", "content": "RESULTADO DA FERRAMENTA: nps -30.1"})
    state.history.append({"role": "system", "content": "SKILL EXEMPLO: csat 4.5"})
    state.history.append({"role": "user", "content": "e a causa?"})
    state.results["resultado_001"] = {"summary": {"pct_em_risco": 49.4}}
    texto = evidence_text(state)
    assert "-30.1" in texto and "49.4" in texto
    assert "e a causa?" not in texto
    assert "4.5" not in texto


def test_trim_history_caps_messages_and_truncates_long_content():
    state = AnalysisState.new("s", "u")
    for i in range(60):
        state.history.append({"role": "user", "content": f"m{i}"})
    state.history.append({"role": "assistant", "content": "x" * 20000})
    state.trim_history()
    assert len(state.history) == AnalysisState.MAX_HISTORY_MESSAGES
    assert len(state.history[-1]["content"]) <= AnalysisState.MAX_MESSAGE_CHARS + 20
