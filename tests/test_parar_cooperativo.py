"""O Parar do chat não corta escrita no meio.

Leitura é cortada na hora. Escrita, envio e comando terminam, e o turno para
na saída deles, antes do passo seguinte; passado o prazo, corta mesmo assim.
"""
import asyncio
import json

from fastapi import BackgroundTasks

from sentury.harness import turno_em_curso as turno
from sentury.harness.state import AnalysisState
from sentury.tools.registry import interrompivel


def test_quem_pode_ser_cortado():
    assert interrompivel("ler_arquivo") and interrompivel("status_da_tarefa")
    assert not interrompivel("escrever_arquivo") and not interrompivel("executar_script")
    assert not interrompivel("ferramenta_que_nao_existe")


async def _registrado(sessao, corpo):
    tarefa = asyncio.create_task(corpo())
    turno.registrar(sessao, tarefa)
    await asyncio.sleep(0)
    return tarefa


async def test_sem_ferramenta_de_escrita_corta_na_hora():
    comecou = asyncio.Event()

    async def corpo():
        with turno.na_ferramenta("c1", "ler_arquivo", True):
            comecou.set()
            await asyncio.sleep(3600)

    tarefa = await _registrado("c1", corpo)
    try:
        await comecou.wait()
        assert turno.pedir_parada("c1") == {"havia": True, "esperando": None}
        await asyncio.gather(tarefa, return_exceptions=True)
        assert tarefa.cancelled() and turno.foi_parado(tarefa)
    finally:
        turno.esquecer("c1", tarefa)


async def test_escrita_termina_e_o_passo_seguinte_nao_comeca():
    comecou, soltar = asyncio.Event(), asyncio.Event()
    feito = []

    async def corpo():
        with turno.na_ferramenta("c2", "escrever_arquivo", False):
            comecou.set()
            await soltar.wait()
            feito.append("escreveu")
        with turno.na_ferramenta("c2", "executar_script", False):
            feito.append("rodou o seguinte")

    tarefa = await _registrado("c2", corpo)
    try:
        await comecou.wait()
        assert turno.pedir_parada("c2") == {"havia": True, "esperando": "escrever_arquivo"}
        await asyncio.sleep(0.05)
        assert not tarefa.done(), "cortou a escrita no meio"
        soltar.set()
        await asyncio.gather(tarefa, return_exceptions=True)
        assert feito == ["escreveu"]
        assert tarefa.cancelled() and turno.foi_parado(tarefa)
    finally:
        turno.esquecer("c2", tarefa)
    assert not turno.parada_pedida("c2")


async def test_passado_o_prazo_corta():
    async def corpo():
        with turno.na_ferramenta("c3", "executar_script", False):
            await asyncio.sleep(3600)

    tarefa = await _registrado("c3", corpo)
    try:
        await asyncio.sleep(0)
        assert turno.pedir_parada("c3", prazo=0.1)["esperando"] == "executar_script"
        await asyncio.wait_for(asyncio.gather(tarefa, return_exceptions=True), 5)
        assert tarefa.cancelled()
    finally:
        turno.esquecer("c3", tarefa)


async def test_sem_turno_nada_acontece():
    assert turno.pedir_parada("ninguem") == {"havia": False, "esperando": None}


async def _eventos(resposta):
    async for pedaco in resposta.body_iterator:
        texto = pedaco.decode() if isinstance(pedaco, bytes) else pedaco
        for linha in texto.splitlines():
            if linha.startswith("data: "):
                yield json.loads(linha[6:])


async def test_pelo_endpoint_e_pelo_execute_tool_de_verdade(monkeypatch):
    """O turno escreve um arquivo pelo `execute_tool` real. O Parar chega no
    meio: a escrita acaba, a ferramenta seguinte não roda, o stream termina
    com `parado`."""
    from sentury import main
    from sentury.tools import catalog

    escrevendo, soltar = asyncio.Event(), asyncio.Event()
    rodou = []

    async def executar(store, state, tool, arguments, *a):
        if tool == "escrever_arquivo":
            escrevendo.set()
            await soltar.wait()
        rodou.append(tool)
        return {"status": "ok"}

    monkeypatch.setattr(catalog, "_executar_ferramenta", executar)

    async def handle_message(state, mensagem, progress_cb=None, effort=None):
        await catalog.execute_tool(None, state, "escrever_arquivo", {"caminho": "a.md"})
        await catalog.execute_tool(None, state, "executar_script", {"comando": "rm -rf build"})
        return {"message": "nao devia chegar aqui"}

    async def load_state(sessao, usuario):
        return None, AnalysisState.new(sessao, usuario)

    monkeypatch.setattr(main.orchestrator, "handle_message", handle_message)
    monkeypatch.setattr(main, "_load_state", load_state)
    resposta = await main.chat_stream(main.ChatRequest(session_id="parar-coop", user_id="u", message="grave"),
                                      BackgroundTasks(), None)

    async def parar():
        await escrevendo.wait()
        pedido = await main.chat_parar(main.PararRequest(session_id="parar-coop"), None)
        soltar.set()
        return pedido

    async def coletar():
        return [e async for e in _eventos(resposta)]

    tarefa = asyncio.create_task(parar())
    eventos = await asyncio.wait_for(coletar(), 10)
    assert (await tarefa) == {"havia": True, "esperando": "escrever_arquivo"}
    assert rodou == ["escrever_arquivo"], rodou
    assert eventos[-1] == {"type": "parado"}
    assert not turno.em_curso("parar-coop")
    # O registro do turno diz por que parou e que a escrita terminou.
    from sentury.harness import registro_do_turno

    gravado = registro_do_turno.ler("parar-coop")
    assert gravado["motivo_de_termino"] == "parado_pela_pessoa"
    assert [(p["ferramenta"], p["status"]) for p in gravado["passos"]] == [("escrever_arquivo", "ok")]
