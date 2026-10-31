"""Pedido grande demais para todos os provedores: compactar e tentar de novo.

Antes, o planner engolia a `FalhaDaCadeia` e seguia sem ferramentas, e a
resposta final batia no mesmo limite e virava "tive um problema".
"""
import json

import pytest
from robinbandit import FalhaDaCadeia

from sentury.harness.context_budget import ContextBudgetManager, Contextualizer
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.pedido_grande import chamar_cabendo, pede_compactar
from sentury.harness.state import AnalysisState

GIGANTE = "PDF-GIGANTE"


class TestQuandoCompactar:
    @pytest.mark.parametrize("tipos", [["context_length"], ["request_too_large"],
                                       ["context_length", "request_too_large"]])
    def test_todos_recusaram_por_tamanho(self, tipos):
        assert pede_compactar(FalhaDaCadeia("x", tipos))

    @pytest.mark.parametrize("tipos", [
        ["content_policy"],                    # compactar nao muda o que a politica recusou
        ["context_length", "rate_limit"],      # um provedor so estava sem cota
        ["context_length", "content_policy"],
        [],
    ])
    def test_nao_compacta(self, tipos):
        assert not pede_compactar(FalhaDaCadeia("x", tipos))

    def test_erro_qualquer_nao_compacta(self):
        assert not pede_compactar(RuntimeError("Todos os provedores de LLM falharam: 413"))

    def test_acha_a_falha_embrulhada(self):
        try:
            try:
                raise FalhaDaCadeia("x", ["context_length"])
            except FalhaDaCadeia as falha:
                raise ValueError("embrulho") from falha
        except ValueError as exc:
            assert pede_compactar(exc)


class _Gerente:
    def __init__(self, compacta=True):
        self.compacta = compacta
        self.chamadas = []

    async def manage(self, state, progress_cb=None, forcar=False):
        self.chamadas.append(forcar)
        if self.compacta:
            state.history = state.history[-1:]
        return self.compacta


class TestChamarCabendo:
    async def test_compacta_remonta_e_tenta_de_novo(self):
        state = AnalysisState.new("s", "u")
        state.history = [{"role": "user", "content": GIGANTE}, {"role": "user", "content": "e agora?"}]
        gerente = _Gerente()
        vistas = []

        async def chamar(msgs):
            vistas.append(msgs)
            if GIGANTE in msgs:
                raise FalhaDaCadeia("413", ["request_too_large"])
            return "ok"

        resposta, usadas = await chamar_cabendo(
            state, gerente, lambda: " ".join(m["content"] for m in state.history), chamar)
        assert resposta == "ok" and usadas == "e agora?"
        assert gerente.chamadas == [True]
        assert len(vistas) == 2

    async def test_politica_de_conteudo_nao_compacta(self):
        state = AnalysisState.new("s", "u")
        gerente = _Gerente()

        async def chamar(msgs):
            raise FalhaDaCadeia("politica", ["content_policy"])

        with pytest.raises(FalhaDaCadeia):
            await chamar_cabendo(state, gerente, lambda: [], chamar)
        assert gerente.chamadas == []

    async def test_nada_a_compactar_sobe_a_recusa_original(self):
        state = AnalysisState.new("s", "u")
        gerente = _Gerente(compacta=False)
        tentativas = []

        async def chamar(msgs):
            tentativas.append(msgs)
            raise FalhaDaCadeia("413", ["request_too_large"])

        with pytest.raises(FalhaDaCadeia):
            await chamar_cabendo(state, gerente, lambda: [], chamar)
        assert len(tentativas) == 1

    async def test_uma_tentativa_so(self):
        state = AnalysisState.new("s", "u")
        state.history = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
        tentativas = []

        async def chamar(msgs):
            tentativas.append(msgs)
            raise FalhaDaCadeia("413", ["context_length"])

        with pytest.raises(FalhaDaCadeia):
            await chamar_cabendo(state, _Gerente(), lambda: list(state.history), chamar)
        assert len(tentativas) == 2

    async def test_gerente_que_falha_nao_derruba_e_sobe_a_recusa(self):
        class Quebrado:
            async def manage(self, *a, **k):
                raise OSError("diario")

        async def chamar(msgs):
            raise FalhaDaCadeia("413", ["context_length"])

        with pytest.raises(FalhaDaCadeia):
            await chamar_cabendo(AnalysisState.new("s", "u"), Quebrado(), lambda: [], chamar)


class _Resumidor:
    async def complete(self, messages, **kwargs):
        return json.dumps({"human_summary": "resumo", "conversation_state": {}})


class TestForcar:
    async def test_forcar_compacta_abaixo_da_regua(self):
        """A regua conta caracteres e o provedor conta tokens: quem recusou manda."""
        gerente = ContextBudgetManager(Contextualizer(_Resumidor()), keep_last_n=4)
        state = AnalysisState.new("s", "u")
        state.history = [{"role": "user", "content": f"m{i}"} for i in range(8)]
        assert await gerente.manage(state) is False and len(state.history) == 8
        assert await gerente.manage(state, forcar=True) is True
        assert len(state.history) == 5 and state.history[-1]["content"] == "m7"

    async def test_forcar_com_conversa_curta_nao_compacta(self):
        gerente = ContextBudgetManager(Contextualizer(_Resumidor()), keep_last_n=4)
        state = AnalysisState.new("s", "u")
        state.history = [{"role": "user", "content": "m"}] * 3
        assert await gerente.manage(state, forcar=True) is False


def _conversa_com_gigante():
    """16 mensagens; a gigante cai na janela de 15 do responder, mas fora das
    12 que a compactacao preserva."""
    historico = []
    for i in range(16):
        papel = "user" if i % 2 == 0 else "assistant"
        historico.append({"role": papel, "content": GIGANTE if i == 3 else f"mensagem {i}"})
    return historico


class _ProvedorComLimite:
    """Recusa o pedido que carrega o PDF gigante, como a cadeia faz quando
    todos os provedores dizem 413. O resumo da compactacao ele aceita."""

    def __init__(self, resposta):
        self.resposta = resposta
        self.last_model = "duplo"
        self.pedidos = []

    async def complete(self, messages, **kwargs):
        if "Sentury Contextualizer" in str(messages[0].get("content")):
            return json.dumps({"human_summary": "o usuario mandou um PDF", "conversation_state": {}})
        self.pedidos.append(messages)
        if any(GIGANTE in str(m.get("content")) for m in messages):
            raise FalhaDaCadeia("Todos os provedores de LLM falharam: 413", ["request_too_large"] * 3)
        return self.resposta


class _Store:
    async def load_chat_history(self, *a): return []
    async def save_chat_message(self, *a): pass
    async def load_session_memory(self, *a): return None
    async def remember(self, *a): pass


class TestNoOrquestrador:
    async def test_o_plano_compacta_em_vez_de_seguir_sem_ferramentas(self):
        plano = json.dumps({"plan": [{"tool": "listar_arquivos", "arguments": {}}]})
        planner = _ProvedorComLimite(plano)
        orq = SenturyOrchestrator(planner=planner, responder=_ProvedorComLimite("x"), store=_Store())
        orq.context_budget_manager = ContextBudgetManager(Contextualizer(_Resumidor()))
        state = AnalysisState.new("s", "u")
        state.history = _conversa_com_gigante()

        passos = await orq._generate_plan("liste os arquivos", state, None, "")
        assert [p.get("tool") for p in passos] == ["listar_arquivos"]
        assert len(planner.pedidos) == 2
