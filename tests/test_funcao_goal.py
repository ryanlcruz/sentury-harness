"""`@goal`: a função expõe a ferramenta; o modelo decide se a propõe.

A funcao liga a instrucao de propor e poe a ferramenta `goal` na mesa, mesmo
quando a mensagem nao tem a palavra "goal". O goal nasce proposto: o
"Começar" continua sendo da pessoa, no cartao.
"""
import json

import pytest

from sentury.harness.funcoes import (
    aplicar_no_turno, ferramentas_ligadas, instrucoes_do_turno,
)
from sentury.harness.state import AnalysisState
from sentury.memory import goals


@pytest.fixture(autouse=True)
def casa(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    yield


class Llm:
    def __init__(self):
        self.chamadas = []
        self.last_model = self.last_provider = "t"
        self.last_usage = self.last_tool_calls = None

    async def complete(self, messages, *a, **k):
        self.chamadas.append(messages)
        texto = "\n".join(str(m.get("content")) for m in messages)
        if "Request Classifier" in texto:
            return json.dumps({"intent": "ANALYSIS", "complexity": "SIMPLE", "priority": "NORMAL",
                               "confidence": 0.9, "events": ["NEED_PLANNER"]})
        if "@goal" in texto and goals.em_aberto("s1") is None:
            return json.dumps({"action": "tool_call", "tool": "goal", "arguments": {
                "acao": "propor", "objetivo": "Zerar o Pokémon Red",
                "criterio": "créditos finais na tela"}})
        return json.dumps({"action": "respond", "message": "Vou zerar o jogo; termina nos créditos."})


def test_goal_e_outros_badges_poe_ferramentas_na_mesa():
    assert ferramentas_ligadas(["goal"]) == {"goal"}
    assert ferramentas_ligadas(["plano", "image"]) == {"criar_plano", "gerar_imagem"}


def test_combina_com_plano():
    instrucoes = instrucoes_do_turno(["plano", "goal"])
    assert len(instrucoes) == 2 and "@goal" in instrucoes[1]


async def test_chamada_explicita_do_modelo_vira_proposta():
    from tests.fixtures.setor_teste.dados import StoreTeste
    from sentury.harness.orchestrator import SenturyOrchestrator

    llm = Llm()
    orq = SenturyOrchestrator(planner=llm, responder=llm,
                              store=StoreTeste())
    estado = AnalysisState.new("s1", "dono")
    estado.funcoes_ativas = ["goal"]
    await orq.handle_message(estado, "zerar o Pokémon Red")

    assert "goal" in orq.turno.capacidades, "a mensagem nao diz goal; a funcao poe na mesa"
    g = goals.em_aberto("s1")
    assert g is not None and g.estado == goals.PROPOSTO and g.criterio == "créditos finais na tela"


async def test_harness_nao_converte_campos_em_chamada_goal():
    from tests.fixtures.setor_teste.dados import StoreTeste
    from sentury.harness.orchestrator import SenturyOrchestrator

    class CamposSemChamada(Llm):
        async def complete(self, messages, *a, **k):
            self.chamadas.append(messages)
            texto = "\n".join(str(m.get("content")) for m in messages)
            if "Request Classifier" in texto:
                return json.dumps({"intent": "ANALYSIS", "complexity": "SIMPLE",
                                   "priority": "NORMAL", "confidence": 0.9,
                                   "events": ["NEED_PLANNER"]})
            return json.dumps({"objetivo": "Listar os projetos e explicar cada um",
                               "criterio": "Relação dos projetos entregue"})

    class Responder(Llm):
        async def complete(self, messages, *a, **k):
            return "Não registrei um objetivo neste turno."

    llm = CamposSemChamada()
    orq = SenturyOrchestrator(planner=llm, responder=Responder(),
                              store=StoreTeste())
    estado = AnalysisState.new("s1", "dono")
    estado.funcoes_ativas = ["goal"]
    await orq.handle_message(estado, "acesse meus projetos e me diga o que cada um faz")

    assert goals.em_aberto("s1") is None, "campos JSON não são uma chamada de ferramenta"


async def test_resposta_sem_chamada_nao_cria_goal():
    from tests.fixtures.setor_teste.dados import StoreTeste
    from sentury.harness.orchestrator import SenturyOrchestrator

    class SoPromete(Llm):
        async def complete(self, messages, *a, **k):
            texto = "\n".join(str(m.get("content")) for m in messages)
            if "Request Classifier" in texto:
                return json.dumps({"intent": "ANALYSIS", "complexity": "SIMPLE",
                                   "priority": "NORMAL", "confidence": 0.9,
                                   "events": ["NEED_PLANNER"]})
            return json.dumps({"action": "respond", "message": "Vou acessar seus projetos."})

    llm = SoPromete()
    orq = SenturyOrchestrator(planner=llm, responder=llm,
                              store=StoreTeste())
    estado = AnalysisState.new("s1", "dono")
    estado.funcoes_ativas = ["goal"]
    resultado = await orq.handle_message(estado, "acesse meus projetos")

    assert goals.em_aberto("s1") is None
    assert "goal" not in resultado["harness"].get("ferramentas", [])


def test_goal_aprovado_nao_recebe_instrucao_de_propor_novamente():
    goal = goals.aprovar(goals.propor("s1", "dono", "Zerar o jogo", "créditos na tela").id)
    estado = AnalysisState.new("s1", "dono")
    estado.funcoes_ativas = ["goal", "computador"]
    aplicar_no_turno(estado)
    textos = [m["content"] for m in estado.history if m.get("funcao_do_turno")]
    assert not any("@goal" in texto for texto in textos)
    assert any("@computador" in texto for texto in textos)
    assert goal.estado == goals.ATIVO


def test_continuar_no_limite_estende():
    g = goals.aprovar(goals.propor("s1", "dono", "x", "y", limite_turnos=2).id)
    goals.contar_turno(g.id)
    goals.contar_turno(g.id)
    goals.pausar(g.id, "limite", por="limite")
    assert goals.continuar(g.id).limite_turnos == 12


def test_a_instrucao_vale_so_no_turno():
    """O planner so ve mensagem de sistema marcada; e a do turno anterior sai,
    senao um `@goal` antigo mandaria propor goal em toda mensagem."""
    from sentury.harness.funcoes import aplicar_no_turno

    estado = AnalysisState.new("s1", "dono")
    estado.funcoes_ativas = ["goal"]
    aplicar_no_turno(estado)
    assert estado.history[-1]["content"].startswith("[INSTRUÇÃO DO SISTEMA: O usuário ligou @goal")

    estado.funcoes_ativas = []
    aplicar_no_turno(estado)
    assert not any("@goal" in str(m.get("content")) for m in estado.history)


async def test_o_planner_recebe_a_instrucao():
    from tests.fixtures.setor_teste.dados import StoreTeste
    from sentury.harness.orchestrator import SenturyOrchestrator

    llm = Llm()
    orq = SenturyOrchestrator(planner=llm, responder=llm,
                              store=StoreTeste())
    estado = AnalysisState.new("s1", "dono")
    estado.funcoes_ativas = ["plano"]
    await orq.handle_message(estado, "lista os arquivos daqui")
    do_planner = [msgs for msgs in llm.chamadas if "Request Classifier" not in str(msgs[0].get("content"))][0]
    assert any("ligou @plano" in str(m.get("content")) for m in do_planner)
