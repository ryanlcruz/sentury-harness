"""O executor continua o goal sozinho, e sabe parar.

O turno de verdade e do `main`; aqui ele e trocado por um falso que devolve o
resultado que cada caso precisa. O ultimo teste roda o turno de verdade, com o
orquestrador e um modelo falso, do "aprovado" ao "aguardando confirmacao".
"""
import asyncio
import json

import pytest

from sentury.harness import executor_de_goal, trava_da_sessao
from sentury.memory import goals


@pytest.fixture(autouse=True)
def casa(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_GOAL_INTERVALO_SEG", "0")
    yield
    executor_de_goal.configurar(None)


def _ativo(**kw):
    g = goals.propor("s1", "dono", "Zerar Pokemon Red", "creditos finais", ["insignia 1"], **kw)
    return goals.aprovar(g.id)


async def _ate_parar(goal_id, tempo=5):
    for _ in range(int(tempo / 0.01)):
        if not executor_de_goal.rodando(goal_id):
            return goals.carregar(goal_id)
        await asyncio.sleep(0.01)
    pytest.fail("o executor nao parou")


def _agiu(*ferramentas):
    return {"message": "ok", "harness": {"ferramentas": list(ferramentas)}}


async def test_continua_ate_o_agente_declarar_cumprido():
    g = _ativo()
    mensagens = []

    async def rodar(goal, mensagem):
        mensagens.append(mensagem)
        if len(mensagens) == 3:
            goals.declarar_cumprido(goal.id, "print dos creditos")
        return _agiu("browser")

    executor_de_goal.configurar(rodar)
    assert executor_de_goal.iniciar(g.id)
    assert not executor_de_goal.iniciar(g.id), "um goal nunca tem dois lacos"
    fim = await _ate_parar(g.id)

    assert fim.estado == goals.AGUARDANDO and fim.turnos == 3
    assert mensagens[0].startswith("[continuacao automatica do goal, turno 1 de 60]")
    assert mensagens[2].startswith("[continuacao automatica do goal, turno 3 de 60]")


async def test_pausa_quando_o_turno_pede_autorizacao():
    g = _ativo()

    async def rodar(goal, mensagem):
        return {**_agiu("browser"), "permissao": {"comando": "acessar_pasta /jogos"}}

    executor_de_goal.configurar(rodar)
    executor_de_goal.iniciar(g.id)
    fim = await _ate_parar(g.id)
    assert fim.estado == goals.PAUSADO and fim.pausado_por == "permissao"
    assert "acessar_pasta /jogos" in fim.motivo and fim.turnos == 1


async def test_pausa_quando_o_agente_pergunta():
    g = _ativo()

    async def rodar(goal, mensagem):
        return {**_agiu(), "clarification": {"intro": "Qual save?"}}

    executor_de_goal.configurar(rodar)
    executor_de_goal.iniciar(g.id)
    fim = await _ate_parar(g.id)
    assert fim.pausado_por == "pergunta"


async def test_pausa_depois_de_falhas_seguidas():
    g = _ativo()
    turnos = []

    async def rodar(goal, mensagem):
        turnos.append(1)
        if len(turnos) == 1:
            return {"falhou": True}
        raise RuntimeError("cota esgotada")

    executor_de_goal.configurar(rodar)
    executor_de_goal.iniciar(g.id)
    fim = await _ate_parar(g.id)
    assert fim.pausado_por == "falha" and "cota esgotada" in fim.motivo
    assert len(turnos) == executor_de_goal.MAX_FALHAS


async def test_pausa_quando_o_agente_so_conversa():
    """Turnos sem ferramenta nem marco queimam cota sem sair do lugar. Olhar o
    placar (`goal ver`) tambem nao conta."""
    g = _ativo()

    async def rodar(goal, mensagem):
        return _agiu("goal")

    executor_de_goal.configurar(rodar)
    executor_de_goal.iniciar(g.id)
    fim = await _ate_parar(g.id)
    assert fim.pausado_por == "parado" and fim.turnos == executor_de_goal.MAX_SEM_PROGRESSO


async def test_marco_conta_como_progresso():
    g = _ativo()
    n = []

    async def rodar(goal, mensagem):
        n.append(1)
        goals.marcar(goal.id, f"marco {len(n)}", "print")
        if len(n) == 5:
            goals.pausar(goal.id, "chega")
        return _agiu()

    executor_de_goal.configurar(rodar)
    executor_de_goal.iniciar(g.id)
    fim = await _ate_parar(g.id)
    assert fim.pausado_por == "pessoa" and fim.turnos == 5


async def test_para_no_limite_de_turnos():
    g = _ativo(limite_turnos=2)

    async def rodar(goal, mensagem):
        return _agiu("browser")

    executor_de_goal.configurar(rodar)
    executor_de_goal.iniciar(g.id)
    fim = await _ate_parar(g.id)
    assert fim.pausado_por == "limite" and fim.turnos == 2


async def test_rearmar_liga_so_os_ativos():
    ativo = _ativo()
    goals.propor("s2", "dono", "outro", "criterio")  # proposto: nao liga
    parado = asyncio.Event()

    async def rodar(goal, mensagem):
        await parado.wait()
        return _agiu("browser")

    executor_de_goal.configurar(rodar)
    assert executor_de_goal.rearmar() == 1 and executor_de_goal.rodando(ativo.id)
    await executor_de_goal.parar_todos()
    assert not executor_de_goal.rodando(ativo.id)
    assert goals.carregar(ativo.id).estado == goals.ATIVO, "parar o servidor nao encerra o goal"


async def test_a_trava_poe_um_turno_de_cada_vez():
    ordem = []

    async def turno(nome):
        async with trava_da_sessao.da("s1"):
            ordem.append(f"{nome}:entra")
            await asyncio.sleep(0.02)
            ordem.append(f"{nome}:sai")

    await asyncio.gather(turno("goal"), turno("pessoa"))
    assert ordem == ["goal:entra", "goal:sai", "pessoa:entra", "pessoa:sai"]


class TestEndpoints:
    @pytest.fixture
    def cliente(self, monkeypatch):
        from fastapi.testclient import TestClient

        import sentury.main as main

        ligados = []
        monkeypatch.setattr(executor_de_goal, "iniciar", lambda gid: ligados.append(gid) or True)
        main.app.dependency_overrides[main.verify_api_token] = lambda: None
        try:
            yield TestClient(main.app), ligados
        finally:
            main.app.dependency_overrides.clear()

    def test_aprovar_liga_e_nao_cumpriu_religa(self, cliente):
        http, ligados = cliente
        g = goals.propor("s1", "dono", "Zerar", "creditos")

        corpo = http.get("/sentury/goals?session_id=s1").json()
        assert corpo["goal"]["estado"] == "proposto" and ligados == []

        r = http.post(f"/sentury/goals/{g.id}/aprovar", json={"modo": "ultra_max"}).json()
        assert r["goal"]["estado"] == "ativo" and r["goal"]["modo"] == "ultra_max"
        assert ligados == [g.id]

        goals.declarar_cumprido(g.id, "print")
        r = http.post(f"/sentury/goals/{g.id}/confirmar",
                      json={"cumprido": False, "nota": "falta a Elite"}).json()
        assert r["goal"]["estado"] == "ativo" and r["goal"]["nota_do_dono"] == "falta a Elite"
        assert ligados == [g.id, g.id]

    def test_transicao_invalida_e_409(self, cliente):
        http, _ = cliente
        g = goals.propor("s1", "dono", "Zerar", "creditos")
        assert http.post(f"/sentury/goals/{g.id}/confirmar", json={"cumprido": True}).status_code == 409

    def test_continuar_depois_do_limite_da_mais_turnos(self, cliente):
        http, ligados = cliente
        g = _ativo(limite_turnos=1)
        goals.contar_turno(g.id)
        goals.pausar(g.id, "limite", por="limite")
        r = http.post(f"/sentury/goals/{g.id}/retomar", json={}).json()
        assert r["goal"]["estado"] == "ativo" and r["goal"]["limite_turnos"] > 1

    def test_permissao_liberada_retoma_e_negada_nao(self, cliente, monkeypatch):
        http, ligados = cliente
        monkeypatch.setattr("sentury.tools.permissoes.responder", lambda *a: {"ok": True})
        g = _ativo()
        goals.pausar(g.id, "precisa da sua autorização: x", por="permissao")

        http.post("/sentury/permissoes", json={"comando": "x", "resposta": "negar", "session_id": "s1"})
        assert goals.carregar(g.id).estado == goals.PAUSADO and ligados == []

        http.post("/sentury/permissoes", json={"comando": "x", "resposta": "uma_vez", "session_id": "s1"})
        assert goals.carregar(g.id).estado == goals.ATIVO and ligados == [g.id]


async def test_turno_de_verdade_do_aprovado_ao_aguardando(monkeypatch):
    """O turno do `main`, com o orquestrador e um modelo falso que declara
    cumprido pela ferramenta `goal`. A mensagem automatica fica marcada."""
    import sentury.main as main
    from tests.fixtures.setor_teste.dados import StoreTeste
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState

    class Llm:
        last_model = last_provider = "t"
        last_usage = last_tool_calls = None
        chamadas = 0

        async def complete(self, messages, *a, **k):
            Llm.chamadas += 1
            if Llm.chamadas == 1:
                return json.dumps({"action": "tool_call", "tool": "goal",
                                   "arguments": {"acao": "cumprido", "evidencia": "print dos creditos"}})
            return json.dumps({"action": "respond", "message": "Zerei: os creditos estao na tela."})

    orq = SenturyOrchestrator(planner=Llm(), responder=Llm(),
                              store=StoreTeste())
    guardado = {}

    async def carregar(session_id, user_id):
        return None, guardado.get(session_id) or AnalysisState.new(session_id, user_id)

    async def gravar(state):
        guardado[state.session_id] = state
        return {}

    monkeypatch.setattr(main, "orchestrator", orq)
    monkeypatch.setattr(main, "_load_state", carregar)
    monkeypatch.setattr(main, "_persist_state", gravar)

    g = _ativo()
    executor_de_goal.configurar(main._rodar_turno_do_goal)
    executor_de_goal.iniciar(g.id)
    fim = await _ate_parar(g.id, tempo=20)

    assert fim.estado == goals.AGUARDANDO and fim.evidencia_final == "print dos creditos"
    automaticas = [m for m in guardado["s1"].history if m.get("origem") == "goal"]
    assert len(automaticas) == 1 and automaticas[0]["role"] == "user"


async def test_goal_parado_pedindo_aprovacao_aparece_esperando_na_lista(monkeypatch, tmp_path):
    """O turno do goal passa pelo registro do turno como o do painel: parado
    pedindo aprovação em segundo plano, a conversa fica "aguardando" na lista."""
    import sentury.main as main
    from sentury.harness import registro_do_turno
    from sentury.harness.state import AnalysisState

    class Orq:
        async def handle_message(self, state, mensagem):
            assert registro_do_turno.estado_na_lista("s1") == "trabalhando"
            return {"message": "Parei aqui.", "permissao": {"chave": "k", "comando": "executar_comando make"}}

    async def carregar(session_id, user_id):
        return None, AnalysisState.new(session_id, user_id)

    async def gravar(state):
        return {}

    monkeypatch.setattr(main, "orchestrator", Orq())
    monkeypatch.setattr(main, "_load_state", carregar)
    monkeypatch.setattr(main, "_persist_state", gravar)
    monkeypatch.setattr(registro_do_turno, "pasta", lambda: tmp_path / "turnos")
    registro_do_turno._limpar_para_testes()

    g = _ativo()
    executor_de_goal.configurar(main._rodar_turno_do_goal)
    executor_de_goal.iniciar(g.id)
    fim = await _ate_parar(g.id)
    assert fim.estado == goals.PAUSADO and fim.pausado_por == "permissao"
    assert registro_do_turno.estado_na_lista("s1") == "aguardando_aprovacao"
