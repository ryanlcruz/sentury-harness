import pytest
from sentury.harness.state import AnalysisState, ConversationState
from sentury.harness.context_budget import ContextBudgetManager, Contextualizer

class MockContextualizerLLM:
    async def complete(self, messages, temperature=0.1):
        return '{"human_summary": "Resumo de teste", "conversation_state": {"current_goal": "Aprender", "completed_tasks": ["Passo 1"], "current_topic": "Testes", "important_decisions": ["Decisao X"], "pending_tasks": [], "known_entities": {}, "user_preferences": {}}}'

@pytest.mark.asyncio
async def test_context_budget_status():
    ctx = Contextualizer(MockContextualizerLLM())
    manager = ContextBudgetManager(ctx, limit_chars=1000, keep_last_n=2)
    
    # Teste de limites
    assert manager.get_status(500) == "OK"
    assert manager.get_status(700) == "MONITOR"
    assert manager.get_status(800) == "WARN"
    assert manager.get_status(900) == "COMPACT"
    assert manager.get_status(960) == "AGGRESSIVE_COMPACT"

@pytest.mark.asyncio
async def test_context_budget_compaction():
    ctx = Contextualizer(MockContextualizerLLM())
    manager = ContextBudgetManager(ctx, limit_chars=100, keep_last_n=2)
    
    state = AnalysisState.new("s1", "u1")
    state.history = [
        {"role": "user", "content": "Mensagem muito longa 1 que vai estourar o limite de caracteres do historico"},
        {"role": "assistant", "content": "Mensagem muito longa 2 que vai estourar o limite de caracteres do historico"},
        {"role": "user", "content": "Mensagem recente 1"},
        {"role": "assistant", "content": "Mensagem recente 2"},
    ]
    
    # Adiciona prioridades
    state.history[0]["priority"] = "CRITICAL"  # Mensagem crítica antiga deve ser preservada
    
    # Executa a compactação
    compacted = await manager.manage(state)
    
    assert compacted is True
    # Resumo + a critica antiga + o que couber no teto de caracteres das
    # recentes. Preservar por contagem devolvia doze mensagens que podiam ser
    # enormes, e a compactacao mal mexia no orcamento.
    assert len(state.history) == 3
    assert state.history[0]["role"] == "system"
    assert "Resumo de teste" in state.history[0]["content"]
    assert state.history[1]["content"] == "Mensagem muito longa 1 que vai estourar o limite de caracteres do historico"
    # A ultima mensagem e a que a resposta precisa: e a que nunca cai.
    assert state.history[2]["content"] == "Mensagem recente 2"
    
    # Verifica o ConversationState atualizado
    assert state.conversation_state.current_goal == "Aprender"
    assert "Decisao X" in state.conversation_state.important_decisions


class _Resumidor:
    def __init__(self, falha=False):
        self.falha, self.chamadas = falha, 0

    async def complete(self, messages, **kwargs):
        self.chamadas += 1
        if self.falha:
            raise RuntimeError("provedor caiu")
        return '{"human_summary": "resumo", "conversation_state": {}}'


def _conversa(falas, resultados=0):
    historico = []
    for n in range(falas):
        historico.append({"role": "user" if n % 2 == 0 else "assistant", "content": f"fala {n}"})
    for n in range(resultados):
        historico.append({"role": "system", "content": f'RESULTADO DA FERRAMENTA "ler_arquivo": {n}'})
    return historico


async def test_resultado_de_ferramenta_nao_conta_no_teto_de_mensagens(tmp_path, monkeypatch):
    """Cada resultado de ferramenta é mensagem; contá-los fazia a conversa com
    ferramentas compactar a cada três turnos, longe do teto de caracteres."""
    from sentury.harness.context_budget import ContextBudgetManager, Contextualizer
    from sentury.harness.state import AnalysisState

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    resumidor = _Resumidor()
    gerente = ContextBudgetManager(Contextualizer(resumidor), limit_messages=30, keep_last_n=12)
    state = AnalysisState.new("ferramentas", "u")
    state.history = _conversa(falas=10, resultados=30)
    assert await gerente.manage(state) is False and resumidor.chamadas == 0


async def test_falha_espera_a_conversa_crescer_antes_de_tentar_de_novo(tmp_path, monkeypatch):
    """Tentar de novo na mensagem seguinte repetia a chamada que acabou de falhar,
    com "Compactando a conversa" na tela, a cada turno."""
    from sentury.harness.context_budget import ContextBudgetManager, Contextualizer
    from sentury.harness.state import AnalysisState

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    resumidor = _Resumidor(falha=True)
    gerente = ContextBudgetManager(Contextualizer(resumidor), limit_messages=10, keep_last_n=6)
    state = AnalysisState.new("falha", "u")
    state.history = _conversa(falas=12)
    avisos = []
    assert await gerente.manage(state, progress_cb=avisos.append) is False
    assert resumidor.chamadas == 1 and state.compactacao_falhou_com == 12

    state.history += _conversa(falas=2)
    assert await gerente.manage(state, progress_cb=avisos.append) is False
    assert resumidor.chamadas == 1, "tentou de novo logo depois de falhar"
    assert len(avisos) == 1, "mostrou Compactando sem compactar"

    resumidor.falha = False
    state.history += _conversa(falas=2)
    assert await gerente.manage(state) is True
    assert resumidor.chamadas == 2 and state.compactacao_falhou_com is None


def test_compactacao_em_curso_aparece_como_marco_da_conversa():
    """Compactar acontece com a conversa: a linha discreta do marco, e não o bloco
    de quem está respondendo, que dizia "Compactando" como se fosse um turno."""
    from pathlib import Path

    chat = Path("sentury/client/src/features/chat")
    indicador = (chat / "ProcessingIndicator.tsx").read_text(encoding="utf-8")
    assert '<MarcoDaConversa texto="Compactando a conversa" emCurso />' in indicador
    assert "<MarcoDaConversa texto={message.content} />" in (chat / "MessageBubble.tsx").read_text(encoding="utf-8")
