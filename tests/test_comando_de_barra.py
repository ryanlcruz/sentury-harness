"""Comando de barra responde sem chamar o modelo."""
from sentury.harness import comando_de_barra
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.test_orchestrator import EchoResponder, _store


class _PlannerProibido:
    last_model = "proibido"

    async def complete(self, *a, **k):
        raise AssertionError("comando de barra não chama o modelo")


def _orq(tmp_path):
    return SenturyOrchestrator(planner=_PlannerProibido(), responder=EchoResponder(), store=_store(), user_skills_dir=tmp_path)


async def test_skills_lista_sem_chamar_o_modelo(tmp_path):
    state = AnalysisState("s", "u")
    saida = await _orq(tmp_path).handle_message(state, "/skills")
    assert saida["harness"]["proposed_tool"] == "listar_skills"
    assert saida["message"]
    assert [m["role"] for m in state.history[-2:]] == ["user", "assistant"]


async def test_learn_grava_a_skill_pelo_caminho_do_aprender_skill(tmp_path, monkeypatch):
    """Com nome, a skill nasce na pasta da pessoa pelo mesmo `criar` do
    aprender_skill, então tem histórico e o desfazer funciona."""
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from sentury.skills import escrita

    orq = _orq(tmp_path)
    saida = await comando_de_barra.responder(
        orq, AnalysisState("s", "u"), "/learn revisao-de-contrato: começar pela cláusula de multa")
    assert saida["learned"] == "revisao-de-contrato"
    # O cartão "Aprendi" é o que dá o desfazer na tela.
    assert saida["aprendizados"] == [{"tipo": "skill", "nome": "revisao-de-contrato", "acao": "criada"}]
    assert "desfazer" in saida["message"]
    arquivo = tmp_path / "skills" / "revisao-de-contrato" / "SKILL.md"
    assert "começar pela cláusula de multa" in arquivo.read_text(encoding="utf-8")
    assert escrita.desfazer("revisao-de-contrato").get("status") == "desfeito"


async def test_learn_sem_nome_explica_em_vez_de_inventar(tmp_path, monkeypatch):
    """Sem nome, o comando não grava `custom-skill-1234`: diz como usar."""
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    saida = await comando_de_barra.responder(_orq(tmp_path), AnalysisState("s", "u"), "/learn sempre responda em tópicos")
    assert saida["learned"] is None
    assert saida["aprendizados"] is None
    assert "/learn revisao-de-contrato:" in saida["message"]
    assert not (tmp_path / "skills").exists() or not any((tmp_path / "skills").iterdir())


async def test_mensagem_comum_e_comando_desconhecido_seguem_o_turno(tmp_path):
    orq = _orq(tmp_path)
    assert await comando_de_barra.responder(orq, AnalysisState("s", "u"), "quantas linhas tem x?") is None
    assert await comando_de_barra.responder(orq, AnalysisState("s", "u"), "/naoexiste") is None
