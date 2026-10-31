import shutil
import subprocess
import uuid

import pytest


@pytest.mark.docker
def test_pagina_publica_e_proxy_isolado():
    if not shutil.which("docker"):
        pytest.skip("Docker não está instalado")
    if subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode:
        pytest.skip("O daemon Docker não está disponível")
    for imagem in ("sentury-hq:local", "sentury-caixa:local"):
        if subprocess.run(["docker", "image", "inspect", imagem], capture_output=True, timeout=20).returncode:
            pytest.skip("Construa as imagens da HQ e da caixa antes da integração")
    nome = "sentury-teste-" + uuid.uuid4().hex[:12]
    criado = subprocess.run(["docker", "run", "-d", "--name", nome, "--label", "sentury.servico=hq",
                            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                            "--sysctl", "net.ipv4.ip_forward=0", "--mount", "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
                            "sentury-hq:local", "sleep", "infinity"], capture_output=True, text=True, timeout=60)
    assert criado.returncode == 0, criado.stderr
    script = '''
import asyncio, base64, json, os, socket, tempfile
from fastapi import FastAPI
import uvicorn
from websockets.asyncio.client import connect
from sentury.residentes import caixa, rede_da_caixa, browser_da_caixa, registro, tarefas, worker, hq, tela_da_caixa
from sentury.tools.browser_contracts import Action
os.environ["SENTURY_HOME"] = tempfile.mkdtemp()
os.environ["SENTURY_HQ_LISTEN_ADDRESS"] = socket.gethostbyname(socket.gethostname())
a = registro.criar({"nome":"teste-browser", "papel":"teste", "objetivo":"ver", "ferramentas":["browser"], "rede":"internet"})

async def testar_tela():
    os.environ["SENTURY_HQ_TOKEN"] = "token-da-fixture"
    app = FastAPI()
    app.include_router(tela_da_caixa.router_hq)
    servidor = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    escuta = socket.socket()
    escuta.bind((os.environ["SENTURY_HQ_LISTEN_ADDRESS"], 0))
    endereco, porta = escuta.getsockname()
    servindo = asyncio.create_task(servidor.serve(sockets=[escuta]))
    async def pronto():
        while not servidor.started:
            if servindo.done():
                await servindo
            await asyncio.sleep(0.01)
    entrou, terminar = asyncio.Event(), asyncio.Event()
    chamadas = []
    async def rodar(agente, tarefa):
        chamadas.append(tarefa)
        if len(chamadas) == 1:
            entrou.set()
            await terminar.wait()
            return {"message":"Resultado anterior", "telemetry":{"custo_usd":0.01}}
        assert "Estado atual observado" in tarefa.retorno
        return {"message":"Página conferida após a pessoa", "telemetry":{"custo_usd":0.01}}
    worker.configurar(rodar)
    try:
        await asyncio.wait_for(pronto(), 10)
        async with connect(f"ws://{endereco}:{porta}/hq/agents/{a.nome}/tela", additional_headers={"Authorization":"Bearer token-da-fixture"}, max_size=4_000_000) as ws:
            async def receber(tipo):
                while True:
                    dado = json.loads(await ws.recv())
                    assert dado.get("tipo") != "erro", dado
                    if dado.get("tipo") == tipo:
                        return dado
            quadro = await asyncio.wait_for(receber("quadro"), 20)
            assert base64.b64decode(quadro["dados"]).startswith(b"\\xff\\xd8")
            tarefa = tarefas.carregar(hq.pedir(a.nome, "Conferir a página", "teste:docker")["id"])
            await asyncio.wait_for(entrou.wait(), 5)
            await ws.send(json.dumps({"tipo":"assumir"}))
            assert (await asyncio.wait_for(receber("controle"), 5))["pessoa"]
            assert tarefas.carregar(tarefa.id).estado == tarefas.ESPERANDO
            assert tarefas.carregar(tarefa.id).motivo == "pessoa no controle"
            await ws.send(json.dumps({"tipo":"clicar", "x":100, "y":100}))
            await ws.send(json.dumps({"tipo":"pressionar", "tecla":"Tab", "codigo":"Tab"}))
            await ws.send(json.dumps({"tipo":"soltar", "tecla":"Tab", "codigo":"Tab"}))
            terminar.set()
            await ws.send(json.dumps({"tipo":"devolver"}))
            assert not (await asyncio.wait_for(receber("controle"), 20))["pessoa"]
            await asyncio.wait_for(worker._LACOS[a.nome], 10)
            assert tarefas.carregar(tarefa.id).estado == tarefas.FEITA
            assert len(chamadas) == 2
    finally:
        await worker.parar_todos()
        worker.configurar(None)
        servidor.should_exit = True
        await asyncio.wait_for(servindo, 10)
        escuta.close()
try:
    resultado = browser_da_caixa.executar(a, Action("navegar", {"url": "https://example.com"}))
    assert resultado["ok"] and "Example Domain" in json.dumps(resultado["dados"])
    for destino in ("http://127.0.0.1/", "http://169.254.169.254/"):
        _, ip_proxy = rede_da_caixa.garantir(a)
        programa = "import http.client; c=http.client.HTTPConnection(" + repr(ip_proxy) + ",3128,timeout=5); c.request('GET'," + repr(destino) + "); assert c.getresponse().status == 403"
        retorno = caixa._docker(["docker", "exec", caixa.nomes(a)[0], "python", "-c", programa])
        assert retorno.returncode == 0, destino
    asyncio.run(testar_tela())
    print("publica, proxy, tela e retomada verificados")
finally:
    rede_da_caixa.encerrar_proxies()
    caixa._docker(["docker", "rm", "-f", caixa.nomes(a)[0]])
    caixa._docker(["docker", "volume", "rm", caixa.nomes(a)[1]])
    caixa._docker(["docker", "network", "disconnect", rede_da_caixa.nome_da_rede(a), os.environ["HOSTNAME"]])
    caixa._docker(["docker", "network", "rm", rede_da_caixa.nome_da_rede(a)])
'''
    try:
        resultado = subprocess.run(["docker", "exec", nome, "python", "-c", script], capture_output=True, text=True, timeout=180)
        assert resultado.returncode == 0, resultado.stderr
        assert "publica, proxy, tela e retomada verificados" in resultado.stdout
    finally:
        subprocess.run(["docker", "rm", "-f", nome], capture_output=True, timeout=30)
