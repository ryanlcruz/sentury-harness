"""Subagente com limite explicado e o trabalho visivel para o usuario.

Restricao sem razao escrita vira regra que alguem remove no futuro sem saber o
que estava protegendo.
"""
from sentury.agents.subagents import ExplicitSubagentCoordinator


class _Provider:
    last_model = "fake"

    def __init__(self):
        self.prompts = []

    async def complete(self, messages, **kw):
        self.prompts.append(messages[0]["content"])
        return "parecer curto"


async def test_limites_do_filho_vem_com_o_porque():
    p = _Provider()
    coord = ExplicitSubagentCoordinator(provider=p)
    await coord._run_one("evidence_analyst", "audite", "por que caiu?", "nps=-31.2")
    prompt = p.prompts[0]
    assert "HARD LIMITS" in prompt
    for proibicao in ("CANNOT delegate", "CANNOT call tools", "CANNOT talk to the user",
                      "CANNOT write to memory", "CANNOT invent numbers"):
        assert proibicao in prompt
    # cada uma acompanhada de razao, nao so a proibicao
    assert "unbounded" in prompt and "race with each other" in prompt


async def test_filho_e_proibido_de_inventar_numero():
    """E o risco mais grave: numero fabricado no filho chega ao usuario como se
    o pai tivesse verificado."""
    p = _Provider()
    await ExplicitSubagentCoordinator(provider=p)._run_one("x", "y", "pergunta", "evidencia")
    assert "as if the parent had verified it" in p.prompts[0]
