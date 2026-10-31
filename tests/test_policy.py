from sentury.harness.policy import sentury_harness
from sentury.harness.state import AnalysisState


def _state(**overrides) -> AnalysisState:
    state = AnalysisState.new("s1", "u1")
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_analysis_tools_always_allowed(setor_teste):
    decision = sentury_harness.evaluate(_state(), 'consultar_medida', 'qual a medida?')
    assert decision.allowed is True


def test_unknown_tool_blocked():
    decision = sentury_harness.evaluate(_state(), "apagar_dataset", "sim")
    assert decision.allowed is False
    assert "ferramenta_valida" in decision.missing


def test_export_blocked_without_any_computed_result():
    state = _state()
    for tool in ["generate_chart", "export_xlsx", "export_csv", "export_pdf", "save_analysis"]:
        decision = sentury_harness.evaluate(state, tool, "exporta isso em excel", arguments={})
        assert decision.allowed is False, f"{tool} não deveria ser permitida sem resultado computado"
        assert "rode uma ferramenta de análise antes de exportar/renderizar" in decision.missing


def test_export_blocked_when_source_does_not_exist():
    state = _state()
    state.register_result("consultar_medida", {"grupo": "Alfa"}, {"medida_medio": 6.2}, row_count=500)
    decision = sentury_harness.evaluate(
        state, "export_xlsx", "exporta o resultado_999", arguments={"source": "resultado_999"}
    )
    assert decision.allowed is False
    assert decision.missing == ["resultado 'resultado_999' não existe — rode uma análise antes de exportar"]


def test_export_allowed_with_explicit_source():
    state = _state()
    result_id = state.register_result("consultar_medida", {"grupo": "Alfa"}, {"medida_medio": 6.2}, row_count=500)
    decision = sentury_harness.evaluate(
        state, "export_xlsx", "exporta esse resultado em excel", arguments={"source": result_id}
    )
    assert decision.allowed is True


def test_export_falls_back_to_last_result_when_source_omitted():
    state = _state()
    state.register_result("consultar_medida", {"grupo": "Alfa"}, {"medida_medio": 6.2}, row_count=500)
    decision = sentury_harness.evaluate(state, "export_csv", "exporta isso em csv", arguments={})
    assert decision.allowed is True


def test_export_uses_most_recent_result_as_default():
    state = _state()
    state.register_result("consultar_medida", {"grupo": "Alfa"}, {"medida_medio": 6.2}, row_count=500)
    segundo_id = state.register_result("executar_python", {"grupo": "Alfa"}, {"backlog_pct": 0.45}, row_count=1500)
    decision = sentury_harness.evaluate(state, "export_pdf", "exporta o ultimo resultado", arguments={})
    assert decision.allowed is True
    assert state.last_result_id == segundo_id


def test_export_allowed_with_tool_name_or_alias_as_source():
    state = _state()
    first_id = state.register_result("consultar_medida", {"grupo": "Alfa"}, {"medida_medio": 6.2}, row_count=500)
    second_id = state.register_result("executar_python", {"grupo": "Alfa"}, {"backlog_pct": 0.45}, row_count=1500)

    # Resolving using tool name (should resolve to the matching tool)
    assert state.resolve_source("consultar_medida") == first_id
    assert state.resolve_source("executar_python") == second_id

    # Resolving using tool name with "_result" suffix
    assert state.resolve_source("consultar_medida_result") == first_id
    assert state.resolve_source("executar_python_result") == second_id

    # Planner/LLM output can occasionally send a list of candidate sources.
    assert state.resolve_source(["missing_source", "consultar_medida_result"]) == first_id
    assert state.resolve_source({"source": "executar_python_result"}) == second_id

    # Evaluation with tool alias in arguments
    decision = sentury_harness.evaluate(
        state, "export_xlsx", "exporta o grafico", arguments={"source": "consultar_medida_result"}
    )
    assert decision.allowed is True

