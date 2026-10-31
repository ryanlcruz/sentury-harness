"""A revisão do aprendizado: quando roda, o que pode usar e o que deixa.

A cadência conta voltas com ferramenta; a revisão é um turno do Sentury sobre
uma cópia da conversa, com o mesmo sistema do turno normal (o cache do
provedor vale) e só as ferramentas de memória e de skill.
"""
import pytest

from sentury.config import settings
from sentury.harness import aprendizado
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.policy import sentury_harness
from sentury.harness.state import AnalysisState
from tests.test_descoberta_multilingue import _Nativo
from tests.test_orchestrator import EchoResponder, _store


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.setattr(settings, "SENTURY_AUTOLEARN", True)
    monkeypatch.setattr(settings, "SENTURY_APRENDER_A_CADA", 3)
    return tmp_path


def _rodou(*ferramentas):
    return {"harness": {"ferramentas": list(ferramentas)}}


def test_conta_voltas_com_ferramenta_e_chega_a_vez():
    estado = AnalysisState.new("s", "u")
    aprendizado.contar(estado, _rodou("ler_arquivo", "executar_comando"))
    assert not aprendizado.chegou_a_vez(estado)
    aprendizado.contar(estado, _rodou())
    aprendizado.contar(estado, _rodou("ler_arquivo"))
    assert aprendizado.chegou_a_vez(estado)
    assert estado.voltas_desde_revisao == 0


def test_turno_que_ja_aprendeu_recomeca_a_contagem():
    estado = AnalysisState.new("s", "u")
    aprendizado.contar(estado, _rodou("ler_arquivo", "ler_arquivo"))
    aprendizado.contar(estado, _rodou("aprender_skill"))
    assert estado.voltas_desde_revisao == 0


@pytest.mark.parametrize("autolearn, a_cada", [(False, 3), (True, 0)])
def test_desligado_nao_revisa(monkeypatch, autolearn, a_cada):
    monkeypatch.setattr(settings, "SENTURY_AUTOLEARN", autolearn)
    monkeypatch.setattr(settings, "SENTURY_APRENDER_A_CADA", a_cada)
    estado = AnalysisState.new("s", "u")
    aprendizado.contar(estado, _rodou(*["ler_arquivo"] * 10))
    assert not aprendizado.chegou_a_vez(estado)


def test_na_revisao_so_memoria_e_skill_respondem():
    estado = AnalysisState.new("s", "u")
    with aprendizado.em_revisao() as permitidas:
        assert {"memoria", "aprender_skill"} <= permitidas
        assert not sentury_harness.evaluate(estado, "executar_comando", "x", {"comando": "dir"}).allowed
        assert sentury_harness.evaluate(estado, "aprender_skill", "x", {"acao": "desfazer", "nome": "x"}).allowed
    assert sentury_harness.evaluate(estado, "executar_comando", "x", {"comando": "dir"}).allowed


async def test_revisao_cria_skill_sem_mudar_a_conversa_e_com_o_mesmo_sistema(casa):
    estado = AnalysisState.new("conversa", "u")
    estado.history = [
        {"role": "user", "content": "converta 10 dólares em reais"},
        {"role": "assistant", "content": "Usei a cotação do dia: R$ 55."},
        {"role": "user", "content": "não, sempre use a cotação de fechamento do dia anterior"},
        {"role": "assistant", "content": "Entendido, refiz com o fechamento: R$ 54,80."},
    ]
    antes = [dict(m) for m in estado.history]

    turno = _Nativo(["Ok."])
    await SenturyOrchestrator(planner=turno, responder=EchoResponder(), store=_store()).handle_message(
        AnalysisState.new("outra", "u"), "oi")

    revisao = _Nativo([
        ("aprender_skill", {"acao": "criar", "nome": "conversao-de-moeda",
                            "descricao": "converte valores entre moedas",
                            "corpo": "## Passos\n1. Use a cotação de fechamento do dia anterior."}),
        "Guardei a skill conversao-de-moeda.",
    ])
    orq = SenturyOrchestrator(planner=revisao, responder=EchoResponder(), store=_store())
    feito = await aprendizado.revisar(orq, estado)

    assert feito["ferramentas"] == ["aprender_skill"]
    assert (casa / "skills" / "conversao-de-moeda" / "SKILL.md").is_file()
    assert estado.history == antes
    sistema = [m for m in revisao.chamadas[0]["messages"] if m["role"] == "system"]
    assert sistema == [m for m in turno.chamadas[0]["messages"] if m["role"] == "system"]
    assert "nada a guardar" in str(revisao.chamadas[0]["messages"][-1]["content"])


def test_turno_so_de_conversa_conta_uma_volta():
    """É na conversa que a pessoa costuma corrigir o jeito de fazer: sem contar
    esses turnos, a revisão nunca olharia para eles."""
    estado = AnalysisState.new("s", "u")
    for _ in range(3):
        aprendizado.contar(estado, _rodou())
    assert aprendizado.chegou_a_vez(estado)
