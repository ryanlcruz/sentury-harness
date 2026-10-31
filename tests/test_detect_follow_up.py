"""Observações anteriores não dependem do idioma nem decidem ferramentas."""
import pytest
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.harness.antecedentes import extrair, MAX_RESULTADOS, MAX_CARACTERES


class MockPlanner:
    """Minimal mock planner for testing."""
    last_model = "mock-planner"
    
    async def complete(self, messages, **kwargs):
        return '{"plan": []}'


class MockResponder:
    """Minimal mock responder for testing."""
    last_model = "mock-responder"
    
    async def complete(self, messages, **kwargs):
        return "Mock response"


def create_orchestrator():
    """Create a minimal orchestrator for testing the detection function."""
    return SenturyOrchestrator(
        planner=MockPlanner(),
        responder=MockResponder(),
        store=None
    )


def create_state_with_tool_result():
    """Create a state with a tool result in history."""
    state = AnalysisState.new("test_session", "test_user")
    state.history.append({
        "role": "user",
        "content": "Qual unidade está pior?"
    })
    state.history.append({
        "role": "system",
        "content": "RESULTADO DA FERRAMENTA consultar_medida: Serviço de Campo tem Medida de 45."
    })
    state.history.append({
        "role": "assistant",
        "content": "A unidade com pior desempenho é Serviço de Campo."
    })
    return state


class TestContextExtraction:
    """Test extraction of tool results from history."""
    
    def test_extract_single_tool_result(self):
        """Should extract single tool result from history."""
        orch = create_orchestrator()
        state = create_state_with_tool_result()
        
        is_follow_up, results = orch._detect_follow_up_and_extract_context(
            "Monte um plano para isso",
            state
        )
        
        assert is_follow_up is True
        assert len(results) == 1
        assert results[0]["role"] == "system"
        assert "RESULTADO DA FERRAMENTA" in results[0]["content"]
        assert "consultar_medida" in results[0]["content"]
    
    def test_extract_multiple_tool_results(self):
        """Should extract all tool results from history."""
        orch = create_orchestrator()
        state = AnalysisState.new("test_session", "test_user")
        
        # Add multiple tool results
        state.history.append({
            "role": "system",
            "content": "RESULTADO DA FERRAMENTA consultar_medida: Medida da Beta é 47%"
        })
        state.history.append({
            "role": "assistant",
            "content": "O Medida da Beta está em 47%"
        })
        state.history.append({
            "role": "user",
            "content": "E o backlog?"
        })
        state.history.append({
            "role": "system",
            "content": "RESULTADO DA FERRAMENTA executar_python: Backlog é 120 tickets"
        })
        state.history.append({
            "role": "assistant",
            "content": "O backlog tem 120 tickets"
        })
        
        is_follow_up, results = orch._detect_follow_up_and_extract_context(
            "Monte um plano baseado nisso",
            state
        )
        
        assert is_follow_up is True
        assert len(results) == 2
        assert all(r["role"] == "system" for r in results)
        assert all("RESULTADO DA FERRAMENTA" in r["content"] for r in results)
    
    def test_extract_preserves_order(self):
        """Should preserve chronological order of tool results."""
        orch = create_orchestrator()
        state = AnalysisState.new("test_session", "test_user")
        
        state.history.append({
            "role": "system",
            "content": "RESULTADO DA FERRAMENTA tool_a: Result A"
        })
        state.history.append({
            "role": "system",
            "content": "RESULTADO DA FERRAMENTA tool_b: Result B"
        })
        state.history.append({
            "role": "system",
            "content": "RESULTADO DA FERRAMENTA tool_c: Result C"
        })
        
        is_follow_up, results = orch._detect_follow_up_and_extract_context(
            "Analise isso",
            state
        )
        
        assert len(results) == 3
        assert "tool_a" in results[0]["content"]
        assert "tool_b" in results[1]["content"]
        assert "tool_c" in results[2]["content"]



@pytest.mark.parametrize("pedido", ["Use isso", "Use the earlier result", "使用之前的结果", "استخدم النتيجة السابقة", "Используй предыдущий результат", "Qual é o significado de API?", "Analise outro arquivo"])
def test_observacoes_sao_candidatas_em_qualquer_idioma(pedido):
    disponiveis, resultados = create_orchestrator()._detect_follow_up_and_extract_context(
        pedido, create_state_with_tool_result(),
    )
    assert disponiveis is True
    assert len(resultados) == 1
    assert "consultar_medida" in resultados[0]["content"]


def test_sem_resultado_nao_inventa_antecedente():
    state = AnalysisState.new("s", "u")
    state.history = [{"role": "user", "content": "e esse?"}, {"role": "system", "content": "Persona"}]
    assert extrair(state, "e esse?") == []


def test_resultado_posterior_ao_pedido_nao_e_antecedente():
    state = AnalysisState.new("s", "u")
    state.history = [
        {"role": "system", "content": "RESULTADO DA FERRAMENTA ler_arquivo: antigo"},
        {"role": "user", "content": "Continue"},
        {"role": "system", "content": "RESULTADO DA FERRAMENTA ler_arquivo: novo"},
    ]
    state.results = {"resultado_002": {"tool": "ler_arquivo", "summary": {"conteudo": "novo"}}}
    resultados = extrair(state, "Continue")
    assert len(resultados) == 1
    assert "antigo" in resultados[0]["content"] and "novo" not in resultados[0]["content"]


def test_resumo_persistido_sobrevive_a_compactacao():
    state = AnalysisState.new("s", "u")
    state.history = [{"role": "system", "content": "Conversa compactada"},
                     {"role": "user", "content": "Use the earlier result"}]
    state.results = {"resultado_001": {"tool": "ler_arquivo", "summary": {"conteudo": "conteúdo confirmado"}}}
    resultados = extrair(state, "Use the earlier result")
    assert len(resultados) == 1
    assert "resultado_001" in resultados[0]["content"]
    assert "conteúdo confirmado" in resultados[0]["content"]


def test_limite_de_contexto_e_deduplicacao():
    state = AnalysisState.new("s", "u")
    state.history = [{"role": "system", "content": "RESULTADO DA FERRAMENTA t" + str(i) + ":" + "x" * 4000}
                     for i in range(MAX_RESULTADOS + 2)]
    state.history.append(dict(state.history[-1]))
    resultados = extrair(state)
    assert len(resultados) == MAX_RESULTADOS
    assert all(len(item["content"]) <= MAX_CARACTERES for item in resultados)
    assert len({item["content"] for item in resultados}) == MAX_RESULTADOS
