import pytest
from sentury.harness.state import AnalysisState
from sentury.harness.orchestrator import SenturyOrchestrator
from tests.fixtures.setor_teste.dados import StoreTeste


class MockLLM:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.last_model = "mock-model"

    async def complete(self, messages):
        self.calls.append(messages)
        # Se ficarmos sem respostas fictícias, retorna um valor padrão
        if not self.responses:
            return '{"action": "respond", "message": "Olá!"}'
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_history_summarization_on_long_chat():
    # Setup
    store = StoreTeste()
    
    # Simula o responder gerando o resumo ("Esta é uma conversa sobre Medida e chamados.")
    # A saudação final vai direto à LLM depois da compactação.
    planner = MockLLM([])
    responder = MockLLM([
        "Resumo: O usuário tirou dúvidas sobre Medida e obteve insights das filiais do Alfa.",  # Resposta para a sumarização
        "Olá! Como posso ajudar hoje?"  # Resposta final do turno
    ])
    
    orchestrator = SenturyOrchestrator(
        planner=planner,
        responder=responder,
        store=store,
        memory=None,
        skills=None
    )
    
    state = AnalysisState.new("s_long", "u_long")
    
    # 1. Cria um histórico longo fictício (32 mensagens = 16 turnos)
    for idx in range(16):
        state.history.append({"role": "user", "content": f"Mensagem do usuário {idx}"})
        state.history.append({"role": "assistant", "content": f"Mensagem do assistente {idx}"})
        
    assert len(state.history) == 32
    
    # 2. Executa um novo turno. Deve disparar a sumarização das 20 primeiras mensagens
    # antes de processar a nova pergunta.
    await orchestrator.handle_message(state, "oi")
    
    # 3. Verifica se as 20 mensagens antigas foram compactadas em 1 resumo do sistema
    # Histórico final esperado:
    # - 1 mensagem de resumo do sistema (índice 0)
    # - 12 mensagens restantes das 32 originais (32 - 20 = 12)
    # - 1 nova mensagem do usuário ("oi")
    # - 1 nova resposta do assistente
    # Total: 1 + 12 + 1 + 1 = 15 mensagens
    assert len(state.history) == 15
    assert state.history[0]["role"] == "system"
    assert "Resumo:" in state.history[0]["content"]
    assert state.history[-2]["content"] == "oi"
    # Quem responde é o modelo da volta; o responder só resumiu o histórico.
    assert state.history[-1]["content"] == "Olá!"
    assert len(responder.calls) == 1
