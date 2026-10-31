import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from sentury.residentes import controle_da_tela as controle, registro, tarefas, worker, tela_da_caixa as tela
from sentury.residentes import browser_da_caixa as navegador
from sentury.tools.browser_contracts import Action


@pytest.fixture
def agente(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    return registro.criar({"nome": "atlas", "papel": "infra", "objetivo": "ver", "ferramentas": ["browser"]})


def test_gestos_nao_aceitam_cdp_livre():
    assert tela.comando({"tipo": "texto", "texto": "oi"})["metodo"] == "Input.insertText"
    assert len(tela.comando({"tipo": "clicar", "x": 100, "y": 50})) == 2
    with pytest.raises(ValueError):
        tela.comando({"tipo": "Runtime.evaluate", "texto": "comando"})
    with pytest.raises(ValueError):
        tela.comando({"tipo": "clicar", "x": 10000})
    with pytest.raises(ValueError):
        tela.comando({"tipo": "texto", "texto": "x", "metodo": "Browser.close"})


def test_visibilidade_para_o_screencast():
    assert tela.comando({"tipo": "visibilidade", "visivel": False})["metodo"] == "Page.stopScreencast"


def test_ws_local_recusa_origem_externa_e_token_errado(monkeypatch):
    from sentury.config import settings

    monkeypatch.setattr(settings, "SENTURY_API_TOKEN", "teste")
    app = FastAPI()
    app.include_router(tela.router_local)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as erro:
            with client.websocket_connect("/sentury/residentes/atlas/tela", headers={"Origin": "https://externo.test"}) as ws:
                ws.send_json({"token": "teste"})
                ws.receive_json()
        assert getattr(erro.value, "code", None) == 1008
        with pytest.raises(WebSocketDisconnect) as erro:
            with client.websocket_connect("/sentury/residentes/atlas/tela", headers={"Origin": "http://127.0.0.1:5173"}) as ws:
                ws.send_json({"token": "errado"})
                ws.receive_json()
        assert getattr(erro.value, "code", None) == 1008


def test_ws_hq_exige_token_no_header(monkeypatch):
    monkeypatch.setenv("SENTURY_HQ_TOKEN", "teste")
    app = FastAPI()
    app.include_router(tela.router_hq)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as erro:
            with client.websocket_connect("/hq/agents/atlas/tela") as ws:
                ws.receive_json()
        assert erro.value.code == 1008


async def test_assumir_espera_acao_e_bloqueia_proxima(agente):
    entrou, sair = asyncio.Event(), asyncio.Event()
    async def acao():
        async with controle.passo(agente.nome):
            entrou.set()
            await sair.wait()
    em_acao = asyncio.create_task(acao())
    await entrou.wait()
    assumir = asyncio.create_task(controle.assumir(agente.nome))
    await asyncio.sleep(0)
    assert not assumir.done()
    sair.set()
    await em_acao
    assert (await assumir)["pessoa"]
    proxima = asyncio.create_task(controle.esperar_devolucao(agente.nome))
    await asyncio.sleep(0)
    assert not proxima.done()
    await controle.devolver(agente.nome, "Página de resultados aberta")
    await asyncio.wait_for(proxima, 1)


async def test_worker_retoma_com_fato_e_nao_fecha_durante_controle(agente):
    primeira, deixar_terminar = asyncio.Event(), asyncio.Event()
    chamadas = []
    async def rodar(a, t):
        chamadas.append(t)
        if len(chamadas) == 1:
            primeira.set()
            await deixar_terminar.wait()
            return {"message": "Estado antigo", "telemetry": {"custo_usd": 0.01}}
        assert "Página de resultados aberta" in t.retorno
        return {"message": "Conferi a página nova", "telemetry": {"custo_usd": 0.01}}
    worker.configurar(rodar)
    tarefa = tarefas.enfileirar(agente.nome, "ver resultados")
    try:
        worker.acordar(agente.nome)
        await asyncio.wait_for(primeira.wait(), 1)
        await controle.assumir(agente.nome)
        assert tarefas.carregar(tarefa.id).estado == tarefas.ESPERANDO
        assert tarefas.carregar(tarefa.id).motivo == "pessoa no controle"
        from sentury.residentes import hq
        with pytest.raises(ValueError, match="aba Tela"):
            hq.responder(tarefa.id, "uma_vez")
        deixar_terminar.set()
        await asyncio.sleep(0)
        assert tarefas.carregar(tarefa.id).estado == tarefas.ESPERANDO
        await controle.devolver(agente.nome, "Página de resultados aberta")
        await asyncio.wait_for(worker._LACOS[agente.nome], 1)
        feita = tarefas.carregar(tarefa.id)
        assert feita.estado == tarefas.FEITA and feita.resposta == "Conferi a página nova"
        assert feita.custo_usd == 0.02
        assert len(chamadas) == 2
        assert registro.carregar(agente.nome).estado == "dormindo"
    finally:
        await worker.parar_todos()
        worker.configurar(None)


async def test_navegador_preserva_action_observation_e_validar_url(agente, monkeypatch):
    chamadas = []
    def executar(a, action):
        chamadas.append(action)
        return {"ok": True, "dados": {"url": "https://publico.test", "arvore": []}}
    monkeypatch.setattr(navegador, "executar", executar)
    monkeypatch.setattr("sentury.tools.web.validar_url", lambda url, **_k: url)
    sessao = navegador.Sessao(agente, "agente:atlas")
    obs = await sessao.execute(Action("navegar", {"url": "https://publico.test"}))
    assert obs.metadados["modo"] == "caixa"
    assert obs.dados["url"] == "https://publico.test" and chamadas[0].tipo == "navegar"
    from sentury.tools.web import UrlRecusada
    def recusar(url, **kwargs):
        # A caixa roda isolada: endereço interno é recusado sempre, também fora do servidor.
        assert kwargs.get("rede_interna") is False
        raise UrlRecusada("interno")
    monkeypatch.setattr("sentury.tools.web.validar_url", recusar)
    with pytest.raises(UrlRecusada):
        await sessao.execute(Action("navegar", {"url": "http://127.0.0.1"}))
    assert len(chamadas) == 1


async def test_cancelamento_durante_controle_nao_vira_conclusao(agente):
    entrou, terminar = asyncio.Event(), asyncio.Event()
    async def rodar(a, t):
        entrou.set()
        await terminar.wait()
        return {"message": "Resultado antigo"}
    tarefa = tarefas.comecar(tarefas.enfileirar(agente.nome, "ver página").id)
    em_turno = asyncio.create_task(controle.rodar(agente, tarefa, rodar))
    await entrou.wait()
    await controle.assumir(agente.nome)
    tarefas.cancelar(tarefa.id)
    terminar.set()
    await controle.devolver(agente.nome, "Página aberta")
    retorno = await asyncio.wait_for(em_turno, 1)
    assert retorno == {"controle_interrompido": True}
    assert worker._fechar(tarefa, retorno).estado == tarefas.CANCELADA


def test_screencast_entrega_ultimo_quadro_mesmo_sem_novo_evento(monkeypatch, capsys):
    import io
    import json
    from types import SimpleNamespace
    from sentury.residentes import caixa_cdp as cdp
    class PrazoDoSocket(TimeoutError):
        pass
    websocket = SimpleNamespace(WebSocketTimeoutException=PrazoDoSocket)
    monkeypatch.setitem(cdp.sys.modules, "websocket", websocket)

    eventos = iter([
        {"method": "Page.screencastFrame", "params": {"sessionId": 1, "data": "primeiro", "metadata": {}}},
        {"method": "Page.screencastFrame", "params": {"sessionId": 2, "data": "último", "metadata": {}}},
        websocket.WebSocketTimeoutException(), EOFError(),
    ])
    def receber():
        dado = next(eventos)
        if isinstance(dado, Exception):
            raise dado
        return json.dumps(dado)
    relogio = iter([1, 1.1, 1.35])
    monkeypatch.setattr(cdp.time, "monotonic", lambda: next(relogio))
    monkeypatch.setattr(cdp.sys, "stdin", io.StringIO(""))
    sessao = SimpleNamespace(ws=SimpleNamespace(recv=receber, close=lambda: None, settimeout=lambda _: None),
                             chamar=lambda *a: None, enviar=lambda *a: None)
    with pytest.raises(EOFError):
        cdp.transmitir(sessao)
    assert [json.loads(l)["dados"] for l in capsys.readouterr().out.splitlines()] == ["primeiro", "último"]
