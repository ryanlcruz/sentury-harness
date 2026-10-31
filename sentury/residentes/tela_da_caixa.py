"""A tela transporta imagens e gestos fechados, sem expor comandos CDP livres."""
import asyncio
import hmac
import json
import os
from urllib.parse import urlsplit, quote

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import caixa, registro, controle_da_tela as controle

router_local = APIRouter()
router_hq = APIRouter()


class Gesto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: str
    x: float = Field(default=0, ge=0, le=1280)
    y: float = Field(default=0, ge=0, le=800)
    tecla: str = Field(default="", max_length=32)
    codigo: str = Field(default="", max_length=32)
    texto: str = Field(default="", max_length=2000)
    delta: float = Field(default=0, ge=-3000, le=3000)
    visivel: bool = True
    modificadores: int = Field(default=0, ge=0, le=15)


def comando(dado):
    gesto = Gesto.model_validate(dado)
    if gesto.tipo == "texto":
        return {"metodo": "Input.insertText", "argumentos": {"text": gesto.texto}}
    if gesto.tipo in ("pressionar", "soltar"):
        return {"metodo": "Input.dispatchKeyEvent", "argumentos": {
            "type": "keyDown" if gesto.tipo == "pressionar" else "keyUp", "key": gesto.tecla,
            "code": gesto.codigo, "modifiers": gesto.modificadores}}
    if gesto.tipo == "clicar":
        return [{"metodo": "Input.dispatchMouseEvent", "argumentos": {
            "type": t, "x": gesto.x, "y": gesto.y, "button": "left", "clickCount": 1}}
                for t in ("mousePressed", "mouseReleased")]
    if gesto.tipo == "rolar":
        return {"metodo": "Input.dispatchMouseEvent", "argumentos": {
            "type": "mouseWheel", "x": gesto.x, "y": gesto.y, "deltaX": 0, "deltaY": gesto.delta}}
    if gesto.tipo == "visibilidade":
        return {"metodo": "Page.startScreencast" if gesto.visivel else "Page.stopScreencast", "argumentos": {
            "format": "jpeg", "quality": 70, "maxWidth": 1280, "maxHeight": 800} if gesto.visivel else {}}
    raise ValueError("Gesto não disponível na tela.")


def origem_permitida(ws):
    origem = ws.headers.get("origin", "")
    if not origem:
        return True
    from ..config import settings

    url = urlsplit(origem)
    return origem in settings.cors_origin_list or (
        url.scheme in ("http", "https") and url.hostname in ("127.0.0.1", "localhost", "::1"))


async def _autenticar(ws, token, *, header=False):
    if not origem_permitida(ws):
        await ws.close(code=1008)
        return False
    if header:
        if not token or not hmac.compare_digest(ws.headers.get("authorization", "").encode(), f"Bearer {token}".encode()):
            await ws.close(code=1008)
            return False
        await ws.accept()
        return True
    await ws.accept()
    try:
        dados = await asyncio.wait_for(ws.receive_json(), timeout=5)
    except (TimeoutError, ValueError, WebSocketDisconnect):
        await ws.close(code=1008)
        return False
    if not isinstance(dados, dict) or not hmac.compare_digest(str(dados.get("token", "")).encode(), token.encode()):
        await ws.close(code=1008)
        return False
    return True


async def _sessao(ws, nome):
    agente = registro.carregar(nome)
    if agente is None or "browser" not in agente.ferramentas:
        await ws.send_json({"tipo": "erro", "mensagem": "O residente não tem navegador."})
        await ws.close()
        return
    if not await asyncio.to_thread(caixa.disponivel):
        await ws.send_json({"tipo": "erro", "mensagem": "Docker indisponível; a tela da caixa não pode ser aberta."})
        await ws.close()
        return
    nome_caixa = await asyncio.to_thread(caixa.garantir, agente)
    processo = await asyncio.create_subprocess_exec("docker", "exec", "-i", nome_caixa, "python", "/opt/sentury/caixa_cdp.py",
                                                     stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.DEVNULL, limit=4_000_000)
    async def escrever(dados):
        processo.stdin.write((json.dumps(dados) + "\n").encode())
        await processo.stdin.drain()

    await escrever({"acao": "screencast"})
    await ws.send_json({"tipo": "controle", **controle.estado(nome)})
    async def enviar():
        while linha := await processo.stdout.readline():
            dado = json.loads(linha)
            if dado.get("ok") is False:
                await ws.send_json({"tipo": "erro", "mensagem": dado.get("erro")})
            else:
                await ws.send_json(dado)

    async def receber():
        while True:
            dado = await ws.receive_json()
            try:
                if dado.get("tipo") == "assumir":
                    await ws.send_json({"tipo": "controle", **await controle.assumir(nome)})
                elif dado.get("tipo") == "devolver":
                    from .browser_da_caixa import executar
                    from ..tools.browser_contracts import Action

                    if not controle.estado(nome).get("pessoa"):
                        raise ValueError("O navegador já está com o residente.")
                    observacao = await asyncio.to_thread(executar, agente, Action("snapshot", {}))
                    fatos = "A pessoa devolveu o navegador. Estado atual observado: " + json.dumps(observacao.get("dados"), ensure_ascii=False)[:5500]
                    await ws.send_json({"tipo": "controle", **await controle.devolver(nome, fatos)})
                else:
                    gestos = comando(dado)
                    if dado.get("tipo") != "visibilidade" and not controle.estado(nome).get("pessoa"):
                        raise ValueError("Assuma o controle antes de enviar gestos.")
                    for gesto in gestos if isinstance(gestos, list) else [gestos]:
                        await escrever(gesto)
            except (ValueError, ValidationError):
                await ws.send_json({"tipo": "erro", "mensagem": "Gesto recusado ou controle ainda não assumido."})

    tarefas = [asyncio.create_task(enviar()), asyncio.create_task(receber())]
    try:
        await asyncio.wait(tarefas, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for tarefa in tarefas:
            tarefa.cancel()
        await asyncio.gather(*tarefas, return_exceptions=True)
        processo.stdin.close()
        try:
            await asyncio.wait_for(processo.wait(), 3)
        except TimeoutError:
            processo.terminate()
            await processo.wait()


@router_hq.websocket("/hq/agents/{nome}/tela")
async def tela_hq(ws: WebSocket, nome: str):
    if await _autenticar(ws, os.environ.get("SENTURY_HQ_TOKEN", ""), header=True):
        await _sessao(ws, nome)


@router_local.websocket("/sentury/residentes/{nome}/tela")
async def tela_local(ws: WebSocket, nome: str):
    from ..config import settings
    from .cliente import url_da_hq

    if not await _autenticar(ws, settings.SENTURY_API_TOKEN or ""):
        return
    if not url_da_hq():
        await _sessao(ws, nome)
        return
    from websockets.asyncio.client import connect

    destino = url_da_hq().replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    token = os.environ.get("SENTURY_HQ_TOKEN", "")
    async with connect(f"{destino}/hq/agents/{quote(nome, safe='')}/tela", additional_headers={"Authorization": f"Bearer {token}"}, max_size=4_000_000) as remoto:
        async def ida():
            while True:
                await remoto.send(json.dumps(await ws.receive_json()))
        async def volta():
            async for mensagem in remoto:
                await ws.send_text(mensagem)
        tarefas = [asyncio.create_task(ida()), asyncio.create_task(volta())]
        try:
            await asyncio.wait(tarefas, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for tarefa in tarefas:
                tarefa.cancel()
            await asyncio.gather(*tarefas, return_exceptions=True)
