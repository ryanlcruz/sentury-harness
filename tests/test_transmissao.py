"""Reconectar quando a conexão cai. Ver harness/transmissao.py.

O turno não morre mais com a conexão: segue rodando por um tempo, a tela
volta de onde parou sem perder nem repetir evento, e só se ninguém voltar é
que ele para, pelo Parar cooperativo.
"""
import asyncio
import json

import pytest
from fastapi import BackgroundTasks, HTTPException

from sentury.harness import transmissao, turno_em_curso
from sentury.harness.state import AnalysisState


@pytest.fixture(autouse=True)
def _limpa():
    transmissao._limpar_para_testes()
    yield
    transmissao._limpar_para_testes()


def _dados(pedaco):
    return [json.loads(linha[6:]) for linha in pedaco.splitlines() if linha.startswith("data: ")]


def _id(pedaco):
    return int(pedaco.split("\n", 1)[0].removeprefix("id: "))


async def test_assistir_de_onde_parou():
    t = transmissao.abrir("t1")
    for i in range(3):
        t.publicar(f'data: {{"n": {i}}}\n\n')
    t.encerrar()
    todos = [p async for p in t.assistir(0)]
    assert [_id(p) for p in todos] == [1, 2, 3]
    depois_do_1 = [p async for p in t.assistir(1)]
    assert [_dados(p)[0]["n"] for p in depois_do_1] == [1, 2]


async def test_sem_ninguem_no_prazo_abandona_e_quem_volta_segura():
    abandonos = []
    t = transmissao.Transmissao("t2", ao_abandonar=lambda: abandonos.append(1), tolerancia=0.1)
    t.publicar("data: {}\n\n")
    assistindo = t.assistir(0)
    await assistindo.__anext__()
    await assistindo.aclose()  # a conexão caiu
    await asyncio.sleep(0.03)
    voltou = t.assistir(1)  # voltou antes do prazo
    espera = asyncio.create_task(voltou.__anext__())
    await asyncio.sleep(0.2)
    assert abandonos == [], "parou o turno com alguém assistindo"
    espera.cancel()
    await asyncio.gather(espera, return_exceptions=True)
    await voltou.aclose()
    await asyncio.sleep(0.2)
    assert abandonos == [1]


async def test_transmissao_de_outro_turno_nao_serve():
    t = transmissao.abrir("t3")
    assert transmissao.da("t3", t.id) is t
    assert transmissao.da("t3", "outro") is None


def _turno_falso(monkeypatch, soltar, cancelado):
    from sentury import main

    async def handle_message(state, mensagem, progress_cb=None, effort=None):
        progress_cb({"type": "stage", "text": "Lendo"})
        try:
            await soltar.wait()
        except asyncio.CancelledError:
            cancelado.append(True)
            raise
        progress_cb({"type": "stage", "text": "Escrevendo"})
        return {"message": "pronto", "attachment": None, "harness": {"events": []}, "telemetry": {}}

    async def load_state(sessao, usuario):
        return None, AnalysisState.new(sessao, usuario)

    async def persist_state(state):
        return {}

    monkeypatch.setattr(main.orchestrator, "handle_message", handle_message)
    monkeypatch.setattr(main, "_load_state", load_state)
    monkeypatch.setattr(main, "_persist_state", persist_state)
    monkeypatch.setattr(main, "_schedule_autotitle", lambda *a, **k: None)
    return main


async def test_a_conexao_cai_e_a_tela_volta_sem_perder_nem_repetir(monkeypatch):
    soltar, cancelado = asyncio.Event(), []
    main = _turno_falso(monkeypatch, soltar, cancelado)
    resposta = await main.chat_stream(main.ChatRequest(session_id="rec", user_id="u", message="x"),
                                      BackgroundTasks(), None)
    id_ = resposta.headers["X-Sentury-Transmissao"]

    corpo = resposta.body_iterator
    primeiro = await asyncio.wait_for(corpo.__anext__(), 5)
    assert _dados(primeiro) == [{"type": "stage", "text": "Lendo"}]
    await corpo.aclose()  # caiu a conexão

    soltar.set()  # o turno segue sem ninguém assistindo
    await asyncio.sleep(0.1)
    assert not cancelado

    volta = await main.chat_stream_retomar("rec", desde=_id(primeiro), transmissao_id=id_, _=None)
    resto = [e for p in [p async for p in volta.body_iterator] for e in _dados(p)]
    assert resto[0] == {"type": "stage", "text": "Escrevendo"}, "perdeu ou repetiu evento"
    assert resto[-1]["type"] == "done"
    assert not turno_em_curso.em_curso("rec")


async def test_ninguem_volta_e_o_turno_para(monkeypatch):
    from sentury.harness import registro_do_turno

    monkeypatch.setattr(transmissao, "TOLERANCIA", 0.1)
    soltar, cancelado = asyncio.Event(), []
    main = _turno_falso(monkeypatch, soltar, cancelado)
    resposta = await main.chat_stream(main.ChatRequest(session_id="rec2", user_id="u", message="x"),
                                      BackgroundTasks(), None)
    corpo = resposta.body_iterator
    await asyncio.wait_for(corpo.__anext__(), 5)
    await corpo.aclose()
    for _ in range(50):
        if cancelado:
            break
        await asyncio.sleep(0.05)
    assert cancelado == [True]
    canal = transmissao.da("rec2")
    await asyncio.wait_for(asyncio.gather(canal.produtor, return_exceptions=True), 5)
    assert registro_do_turno.ler("rec2")["motivo_de_termino"] == "conexao_caiu"


async def test_retomar_sem_turno_da_404():
    from sentury import main

    with pytest.raises(HTTPException) as erro:
        await main.chat_stream_retomar("nenhum", desde=0, transmissao_id="", _=None)
    assert erro.value.status_code == 404
