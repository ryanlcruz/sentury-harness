"""O chat mostra o que o turno guardou, e só o que foi gravado de fato.

A lista sai dos resultados das ferramentas de memória e de skill: uma promessa
no texto da resposta não vira aviso, e uma gravação recusada também não.
"""
import pytest

from sentury.harness.aprendizados import do_turno
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.test_skills import Echo, ScriptedPlanner, _store, _tool


def test_so_entra_o_que_foi_gravado():
    resultados = [
        {"tool": "memoria", "result": {"status": "salvo", "fato": "Prefere PDF."}},
        {"tool": "memoria", "result": {"status": "não salvo", "parecido": {"nome": "pdf"}}},
        {"tool": "aprender_skill", "result": {"status": "criada", "skill": "revisao-de-contrato"}},
        {"tool": "aprender_skill", "result": {"status": "acrescentada", "skill": "revisao-de-contrato"}},
        {"tool": "aprender_skill", "result": {"status": "nada a mudar", "skill": "outra"}},
        {"tool": "ler_arquivo", "result": {"status": "salvo", "fato": "não é memória"}},
    ]
    assert do_turno(resultados) == [
        {"tipo": "memoria", "texto": "Prefere PDF."},
        {"tipo": "skill", "nome": "revisao-de-contrato", "acao": "acrescentada"},
    ]


def test_o_aprendido_do_fechamento_entra_uma_vez():
    resultados = [{"tool": "memoria", "result": {"status": "salvo", "fato": "Prefere PDF."}}]
    assert do_turno(resultados, "Prefere PDF.") == [{"tipo": "memoria", "texto": "Prefere PDF."}]
    assert do_turno([], "Foca no Sul.") == [{"tipo": "memoria", "texto": "Foca no Sul."}]
    assert do_turno([], None) == []


async def test_turno_que_cria_skill_devolve_o_aviso(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    planner = ScriptedPlanner([_tool(
        "aprender_skill", acao="criar", nome="revisao-de-contrato", mesmo_assim=True,
        descricao="revisa contrato de prestação de serviço",
        corpo="Comece pela cláusula de multa e depois pelo prazo.")])
    orch = SenturyOrchestrator(planner=planner, responder=Echo(), store=_store())
    resultado = await orch.handle_message(AnalysisState.new("s", "u"), "lembra de começar contrato pela multa")
    assert resultado["aprendizados"] == [{"tipo": "skill", "nome": "revisao-de-contrato", "acao": "criada"}]


async def test_desfazer_da_skill_pelo_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from fastapi import HTTPException

    from sentury.main import desfazer_skill
    from sentury.skills import escrita

    escrita.criar("revisao-de-contrato", "revisa contrato", "Comece pela multa.", mesmo_assim=True)
    assert (await desfazer_skill("revisao-de-contrato", None))["acao_desfeita"] == "criar"
    assert not (escrita.pasta_do_usuario() / "revisao-de-contrato").exists()
    with pytest.raises(HTTPException):
        await desfazer_skill("revisao-de-contrato", None)
