"""Pedido "muda Y no X" tem que mexer no X, nao trazer B.

O planner montava plano fechado sem saber que ja existia um artefato. O
contexto anterior so era injetado quando uma regex de pronome demonstrativo
casava -- quem nao usasse a palavra certa ficava sem antecedente.
"""
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState


def _estado_com_analise_e_artefato():
    st = AnalysisState.new("s-ref", "u")
    st.register_result("consultar_medida", {"grupo": "Alfa"},
                       {"grupo": "Alfa", "medida": -49.3, "volume": 2009}, 2009)
    st.history.append({"role": "user", "content": "gere um grafico"})
    st.history.append({
        "role": "assistant", "content": "Pronto.",
        "attachment": {"type": "chart_json", "filename": "medida.png", "title": "Medida por grupo"},
    })
    return st


def test_descreve_o_que_ja_existe():
    d = SenturyOrchestrator._describe_current_state(_estado_com_analise_e_artefato())
    assert "consultar_medida" in d
    assert "grupo=Alfa" in d
    assert "resultado_001" in d


def test_aponta_o_ultimo_artefato_como_alvo_de_mudanca():
    """O antecedente que faltava: existe um grafico, e mudar significa refaze-lo."""
    d = SenturyOrchestrator._describe_current_state(_estado_com_analise_e_artefato())
    assert "ULTIMO ARTEFATO ENTREGUE" in d.replace("Ú", "U")
    assert "Medida por grupo" in d
    baixo = d.lower()
    assert "refaça este" in baixo or "refaca este" in baixo
    assert "analise nova" in baixo.replace("á", "a").replace("é", "e")


def test_sessao_limpa_nao_inventa_antecedente():
    assert SenturyOrchestrator._describe_current_state(AnalysisState.new("s0", "u")) == ""


def test_analise_sem_artefato_lista_so_o_resultado():
    st = AnalysisState.new("s1", "u")
    st.register_result("executar_python", {}, {"volume": 15000, "pct_backlog": 33.6}, 15000)
    d = SenturyOrchestrator._describe_current_state(st)
    assert "executar_python" in d
    assert "ARTEFATO" not in d


def test_mantem_so_os_ultimos_resultados():
    """Contexto e caro: nao despeja a sessao inteira."""
    st = AnalysisState.new("s2", "u")
    for i in range(8):
        st.register_result("consultar_medida", {}, {"volume": i}, i)
    d = SenturyOrchestrator._describe_current_state(st)
    assert len(d.splitlines()) <= 4


def test_aguenta_valor_numpy_no_resumo():
    """O dataset devolve np.float64: `v not in (None, '', [])` faria comparacao
    elemento a elemento e estouraria. Foi o que quebrou 7 testes."""
    import numpy as np

    from sentury.harness.state import AnalysisState

    st = AnalysisState.new("s-np", "u")
    st.register_result("consultar_medida", {}, {
        "medida": np.float64(-31.2),
        "volume": 5000,
        "tendencia_mensal": np.array([]),
    }, 5000)
    d = SenturyOrchestrator._describe_current_state(st)
    assert "consultar_medida" in d
