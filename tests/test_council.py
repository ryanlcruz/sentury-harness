import json

from sentury.harness.council import SenturyCouncil


class CouncilLLM:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return json.dumps(
            {
                "perspectives": {
                    "cx": "O atendimento prioriza recuperar a confiança.",
                    "operations": "Operacoes prioriza a capacidade critica.",
                    "finance": "Financeiro protege o retorno da acao.",
                    "commercial": "Comercial protege as renovacoes.",
                    "strategy": "Estrategia sequencia as frentes.",
                },
                "trade_offs": ["Velocidade versus custo."],
                "consensus_recommendation": "Priorize capacidade e comunicacao.",
            }
        )


async def test_council_uses_one_llm_call_with_five_internal_roles():
    llm = CouncilLLM()
    council = SenturyCouncil(llm)

    result = await council.analyze(
        "Qual frente deve vir primeiro?",
        [{"tool": "consultar_medida", "result": {"medida": -31.2, "volume": 5000}}],
    )

    assert set(result["perspectives"]) == {"cx", "operations", "finance", "commercial", "strategy"}
    assert result["peer_reviews"] == []
    assert result["consensus_recommendation"] == "Priorize capacidade e comunicacao."
    assert len(llm.calls) == 1
    assert "cinco papeis" in llm.calls[0][0][0]["content"].lower()
