"""Dado sensivel na conversa: o agente avisa, e segue. Nada e redigido.

O dado pode ser de teste ou da propria pessoa; trocar o valor quebraria o que
ela pediu. E aviso demais e aviso que ninguem le: telefone e e-mail nao contam,
e CPF e cartao so com digito verificador valido.
"""
import json

import pytest

from sentury.harness.aviso_de_sensivel import detectar, nota_para_o_modelo

CPF_VALIDO = "529.982.247-25"
CARTAO_VALIDO = "4111 1111 1111 1111"


class TestDetectar:
    @pytest.mark.parametrize("texto,esperado", [
        ("minha chave: OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz", ["credencial"]),
        ("usa esse token ghp_abcdefghijklmnopqrstuvwxyz0123456789", ["credencial"]),
        (f"meu cpf e {CPF_VALIDO}", ["cpf"]),
        (f"meu cpf e {CPF_VALIDO.replace('.', '').replace('-', '')}", ["cpf"]),
        (f"paga com {CARTAO_VALIDO}", ["cartao"]),
        (f"cpf {CPF_VALIDO} e cartao {CARTAO_VALIDO}", ["cpf", "cartao"]),
    ])
    def test_o_que_avisa(self, texto, esperado):
        assert detectar(texto) == esperado

    @pytest.mark.parametrize("texto", [
        "me liga em (11) 98765-4321",
        "manda para maria.souza@exemplo.com.br",
        "o pedido 12345678900 chegou",           # 11 digitos, mas nao e CPF
        "111.111.111-11",                         # digitos iguais nao e CPF
        "protocolo 1234 5678 9012 3456",          # 16 digitos que nao passam no Luhn
        "vagas remotas de python em sao paulo",
    ])
    def test_o_que_nao_avisa(self, texto):
        assert detectar(texto) == []

    def test_nota_vazia_quando_nao_ha_nada(self):
        assert nota_para_o_modelo([]) == ""

    def test_a_nota_manda_avisar_e_seguir_sem_repetir_o_valor(self):
        nota = nota_para_o_modelo(["credencial", "cpf"])
        assert "uma chave ou senha, um CPF" in nota
        assert "sem repetir o valor" in nota and "Nao recuse" in nota


class TestNoTurno:
    async def _turno(self, mensagem):
        from tests.fixtures.setor_teste.dados import StoreTeste
        from sentury.harness.orchestrator import SenturyOrchestrator
        from sentury.harness.state import AnalysisState

        class Llm:
            last_model = last_provider = "t"
            last_usage = last_tool_calls = None

            async def complete(self, messages, *a, **k):
                return json.dumps({"action": "respond", "message": "ok"})

        llm = Llm()
        estado = AnalysisState.new("s", "u")
        orq = SenturyOrchestrator(planner=llm, responder=llm,
                                  store=StoreTeste())
        return estado, await orq.handle_message(estado, mensagem)

    async def test_a_nota_entra_logo_depois_da_mensagem_e_o_valor_fica(self):
        mensagem = "configura com OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz"
        estado, resultado = await self._turno(mensagem)

        indice = next(i for i, m in enumerate(estado.history) if m.get("content") == mensagem)
        seguinte = estado.history[indice + 1]
        assert seguinte["role"] == "system" and "[AVISO DE DADO SENSIVEL]" in seguinte["content"]
        assert resultado["harness"]["dado_sensivel"] == ["credencial"]

    async def test_mensagem_comum_nao_ganha_nota(self):
        estado, resultado = await self._turno("me manda o resumo em maria@exemplo.com")

        assert not any("[AVISO DE DADO SENSIVEL]" in str(m.get("content")) for m in estado.history)
        assert resultado["harness"]["dado_sensivel"] == []
