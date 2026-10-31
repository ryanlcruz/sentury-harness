import json

from tests.fixtures.setor_teste.dados import StoreTeste
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.repeticao import skill_ja_carregada
from sentury.harness.state import AnalysisState
from sentury.memory.session_store import InMemorySessionStore
from sentury.memory.skill_store import get_skill_store


class ScriptedPlanner:
    last_model = "scripted"

    def __init__(self, acoes):
        self._acoes = list(acoes)

    async def complete(self, messages):
        return self._acoes.pop(0) if self._acoes else json.dumps({"action": "respond", "message": "fim"})


class Echo:
    last_model = "echo"

    async def complete(self, messages):
        return json.dumps({"action": "respond", "message": "Resumo."})


def _tool(tool, **args):
    return json.dumps({"action": "tool_call", "tool": tool, "arguments": args})


def _store():
    return StoreTeste()


def _orch(planner, skills):
    return SenturyOrchestrator(planner=planner, responder=Echo(), store=_store(), skills=skills)


async def test_save_skill_requires_prior_analysis():
    skills = get_skill_store(InMemorySessionStore())
    orch = _orch(ScriptedPlanner([_tool("salvar_skill", nome="semana")]), skills)
    r = await orch.handle_message(AnalysisState.new("s", "u"), "salva como rotina semana")
    assert "não há" in r["message"].lower() or "rode uma análise" in r["message"].lower()
    assert await skills.all("u") == []


async def test_save_then_list_then_run_skill(setor_teste):
    skills = get_skill_store(InMemorySessionStore())

    # 1) roda uma análise e salva como rotina
    orch = _orch(ScriptedPlanner([_tool("consultar_medida"), _tool("salvar_skill", nome="semanal")]), skills)
    state = AnalysisState.new("s1", "ana")
    r1 = await orch.handle_message(state, "analisa o medida e salva como rotina semanal")
    assert "semanal" in r1["message"]
    salvas = await skills.all("ana")
    assert len(salvas) == 1 and salvas[0]["nome"] == "semanal"
    assert salvas[0]["passos"][0]["tool"] == "consultar_medida"

    # 2) lista
    orch2 = _orch(ScriptedPlanner([_tool("listar_skills")]), skills)
    r2 = await orch2.handle_message(AnalysisState.new("s2", "ana"), "quais rotinas eu tenho")
    assert "semanal" in r2["message"]

    # 3) executa a rotina numa nova sessão (replay) → responder apresenta
    orch3 = _orch(ScriptedPlanner([_tool("executar_skill", nome="semanal")]), skills)
    state3 = AnalysisState.new("s3", "ana")
    r3 = await orch3.handle_message(state3, "roda minha rotina semanal")
    assert r3["message"]  # apresentou algo
    assert any(res["tool"] == "consultar_medida" for res in state3.results.values())


async def test_run_unknown_skill_is_graceful():
    skills = get_skill_store(InMemorySessionStore())
    orch = _orch(ScriptedPlanner([_tool("executar_skill", nome="inexistente")]), skills)
    r = await orch.handle_message(AnalysisState.new("s", "u"), "roda a rotina inexistente")
    assert "não encontrei" in r["message"].lower()


async def test_forget_skill():
    skills = get_skill_store(InMemorySessionStore())
    await skills.save("u", "x", [{"tool": "consultar_medida", "arguments": {}}])
    orch = _orch(ScriptedPlanner([_tool("esquecer_skill", nome="x")]), skills)
    r = await orch.handle_message(AnalysisState.new("s", "u"), "esquece a rotina x")
    assert "removi" in r["message"].lower()
    assert await skills.all("u") == []


async def test_skill_ja_carregada_nao_entra_de_novo():
    """Pedir de novo uma skill que já está no contexto só repetiria o texto e
    empurraria o resto para fora; o modelo recebe onde o texto já está."""
    skills = get_skill_store(InMemorySessionStore())
    orch = _orch(ScriptedPlanner([_tool("executar_skill", nome="bloco-vivo"),
                                  _tool("executar_skill", nome="bloco-vivo")]), skills)
    state = AnalysisState.new("s", "u")
    await orch.handle_message(state, "mostra um painel")
    sistema = [str(m.get("content") or "") for m in state.history if m.get("role") == "system"]
    carregadas = [m for m in sistema if m.startswith("[INSTRUÇÃO PROCEDURAL DE SKILL CARREGADA]")]
    assert len(carregadas) == 1 and "=== SKILL: bloco-vivo ===" in carregadas[0]
    assert any(m.startswith("[SKILL JÁ CARREGADA] A skill `bloco-vivo`") for m in sistema)
    aviso = next(m for m in sistema if m.startswith("[SKILL JÁ CARREGADA]"))
    assert not skill_ja_carregada([{"role": "system", "content": aviso}], "bloco-vivo"),         "o aviso sozinho não conta como skill carregada"
