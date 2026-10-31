"""Falar com a Sentury enquanto ela trabalha: a caixa do turno.

Enter com o turno rodando orienta; a mensagem entra no próximo ponto seguro
e o resto do plano é refeito com ela.
"""
import asyncio
import json

import pytest
from fastapi import BackgroundTasks, HTTPException

from sentury.harness import caixa_do_turno as caixa
from sentury.harness import turno_em_curso
from sentury.harness.emissor import EMISSOR
from sentury.harness.state import AnalysisState


@pytest.fixture(autouse=True)
def _limpa():
    caixa._limpar_para_testes()
    yield
    caixa._limpar_para_testes()


def _com_turno(sessao):
    """Registra a task atual como o turno da sessão, como o /chat/stream faz."""
    tarefa = asyncio.current_task()
    turno_em_curso.registrar(sessao, tarefa)
    return tarefa


async def test_sem_turno_nao_guarda():
    assert caixa.receber("ninguem", "usa a de março") is None
    assert caixa.pendentes("ninguem") == []


async def test_recebida_aplicada_vista():
    tarefa = _com_turno("s1")
    eventos = []
    token = EMISSOR.set(eventos.append)
    try:
        o = caixa.receber("s1", "  usa a planilha de março  ", "c-1")
        assert o and o.texto == "usa a planilha de março" and o.aplicada_em is None

        state = AnalysisState.new("s1", "u")
        assert caixa.aplicar(state) == [o]
        assert caixa.aplicar(state) == [], "aplicou duas vezes"
        nota = state.history[-1]
        assert nota["role"] == "system" and nota[caixa.MARCA] == "usa a planilha de março"
        assert nota["content"].startswith("[INSTRUÇÃO DO SISTEMA:")

        # Vista só quando o texto estava de fato no que foi ao modelo.
        assert caixa.marcar_vistas(state, [{"role": "user", "content": "outra coisa"}]) == []
        assert caixa.marcar_vistas(state, [{"role": "user", "content": nota["content"]}]) == [o]
        assert [e["fase"] for e in eventos] == ["aplicada", "vista"]
        assert eventos[0] == {"type": "mensagem_no_turno", "seq": o.seq, "id_cliente": "c-1", "fase": "aplicada"}
    finally:
        EMISSOR.reset(token)
        turno_em_curso.esquecer("s1", tarefa)


async def test_a_que_chega_tarde_vira_o_proximo_turno():
    tarefa = _com_turno("s2")
    try:
        state = AnalysisState.new("s2", "u")
        caixa.receber("s2", "primeira")
        caixa.aplicar(state)
        tarde = caixa.receber("s2", "chegou na resposta final")
        assert caixa.encerrar("s2") == [tarde]
        assert caixa.pendentes("s2") == [] and caixa.encerrar("s2") == []
    finally:
        turno_em_curso.esquecer("s2", tarefa)


async def test_uma_conversa_nao_recebe_a_da_outra():
    ta = _com_turno("a")
    try:
        caixa.receber("a", "só para a conversa a")
        assert caixa.aplicar(AnalysisState.new("b", "u")) == []
        assert len(caixa.pendentes("a")) == 1
    finally:
        turno_em_curso.esquecer("a", ta)


def _orquestrador(planos, vistas):
    from sentury.data.store import SemDados
    from sentury.harness.orchestrator import SenturyOrchestrator

    class Planner:
        last_model = "planner"

        async def complete(self, messages, *a, **k):
            vistas.append(messages)
            plano = planos.pop(0) if planos else []
            # Sem passo, a resposta vai no próprio objeto, como pede o contrato.
            return json.dumps({"plan": plano, **({} if plano else {"message": "feito"})})


    class Responder:
        last_model = "responder"

        async def complete(self, messages, *a, **k):
            return "feito"

    return SenturyOrchestrator(planner=Planner(), responder=Responder(),
                               store=SemDados(), memory=None, skills=None)


async def test_orientar_no_meio_refaz_o_resto_do_plano(monkeypatch):
    """Ponta a ponta no orquestrador: o plano é ler A e depois B. Enquanto A
    roda, a pessoa manda "leia C no lugar do B". B não roda; o replanejamento
    vê a orientação e lê C."""
    from sentury.harness import execucao_do_passo as modulo

    rodou = []

    async def execute_tool(store, state, tool, arguments, *a, **k):
        rodou.append(arguments.get("caminho"))
        if arguments.get("caminho") == "a.txt":
            assert caixa.receber(state.session_id, "leia o c.txt no lugar do b.txt", "c-9")
        return {"status": "ok", "conteudo": f"conteúdo de {arguments.get('caminho')}"}

    monkeypatch.setattr(modulo, "execute_tool", execute_tool)
    ler = lambda caminho: {"tool": "ler_arquivo", "arguments": {"caminho": caminho}}  # noqa: E731
    vistas = []
    orq = _orquestrador([[ler("a.txt"), ler("b.txt")], [ler("c.txt")], []], vistas)

    eventos = []
    state = AnalysisState.new("orientar-e2e", "u")
    tarefa = _com_turno("orientar-e2e")
    try:
        await orq.handle_message(state, "leia o a.txt e o b.txt", progress_cb=eventos.append)
    finally:
        turno_em_curso.esquecer("orientar-e2e", tarefa)

    assert rodou == ["a.txt", "c.txt"], rodou
    assert "leia o c.txt no lugar do b.txt" in json.dumps(vistas[1], ensure_ascii=False)
    assert "leia o c.txt" not in json.dumps(vistas[0], ensure_ascii=False)
    fases = [e["fase"] for e in eventos if isinstance(e, dict) and e.get("type") == "mensagem_no_turno"]
    assert fases == ["aplicada", "vista"], fases


async def test_orientar_quando_nao_ha_passo_ganha_mais_uma_volta():
    """O planner decide responder direto (plano vazio) e a orientação chega
    enquanto ele pensava: não há passo onde ela entraria. O fim da volta
    confere a caixa e dá mais uma volta com ela, em vez de responder sem ver."""
    vistas = []
    orq = _orquestrador([[], []], vistas)
    planner_complete = orq.planner.complete

    async def complete(messages, *a, **k):
        if not vistas:
            caixa.receber("orientar-fim", "responda em inglês")
        return await planner_complete(messages, *a, **k)

    orq.planner.complete = complete
    state = AnalysisState.new("orientar-fim", "u")
    tarefa = _com_turno("orientar-fim")
    try:
        await orq.handle_message(state, "o que é uma trava de sessão?")
    finally:
        turno_em_curso.esquecer("orientar-fim", tarefa)
    assert len(vistas) == 2, "não replanejou com a orientação"
    assert "responda em inglês" in json.dumps(vistas[1], ensure_ascii=False)
    assert caixa.pendentes("orientar-fim") == []


async def _eventos(resposta):
    async for pedaco in resposta.body_iterator:
        texto = pedaco.decode() if isinstance(pedaco, bytes) else pedaco
        for linha in texto.splitlines():
            if linha.startswith("data: "):
                yield json.loads(linha[6:])


async def test_pelo_endpoint(monkeypatch):
    """Sem turno, 409. Com o turno rodando, 202; e a orientação que o turno
    não chegou a aplicar sai no stream como `proximo_turno`."""
    from sentury import main

    with pytest.raises(HTTPException) as erro:
        await main.chat_orientar(main.OrientarRequest(session_id="ep", texto="oi"), None)
    assert erro.value.status_code == 409

    comecou, soltar = asyncio.Event(), asyncio.Event()

    async def handle_message(state, mensagem, progress_cb=None, effort=None):
        comecou.set()
        await soltar.wait()
        return {"message": "pronto", "attachment": None, "harness": {"events": []}, "telemetry": {}}

    async def load_state(sessao, usuario):
        return None, AnalysisState.new(sessao, usuario)

    async def persist_state(state):
        return {}

    monkeypatch.setattr(main.orchestrator, "handle_message", handle_message)
    monkeypatch.setattr(main, "_load_state", load_state)
    monkeypatch.setattr(main, "_persist_state", persist_state)
    monkeypatch.setattr(main, "_schedule_autotitle", lambda *a, **k: None)

    resposta = await main.chat_stream(main.ChatRequest(session_id="ep", user_id="u", message="trabalhe"),
                                      BackgroundTasks(), None)

    async def orientar():
        await comecou.wait()
        aceito = await main.chat_orientar(main.OrientarRequest(session_id="ep", texto="e o resumo?",
                                                               id_cliente="c-5"), None)
        soltar.set()
        return aceito

    async def coletar():
        return [e async for e in _eventos(resposta)]

    tarefa = asyncio.create_task(orientar())
    eventos = await asyncio.wait_for(coletar(), 10)
    aceito = await tarefa
    assert aceito["fase"] == "recebida"
    tarde = [e for e in eventos if e.get("type") == "mensagem_no_turno"]
    assert tarde == [{"type": "mensagem_no_turno", "seq": aceito["seq"], "id_cliente": "c-5", "fase": "proximo_turno"}]
    assert eventos[-1]["type"] == "done"
    assert not turno_em_curso.em_curso("ep")
    with pytest.raises(HTTPException):
        await main.chat_orientar(main.OrientarRequest(session_id="ep", texto="oi"), None)
