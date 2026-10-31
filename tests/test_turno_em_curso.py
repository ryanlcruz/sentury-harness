"""O turno em curso de cada sessao, para o atalho do computer use pará-lo.

Hoje o turno so parava quando o cliente fechava o stream. O atalho e ouvido
pelo sistema, em outra thread: ele precisa achar a task e cancela-la.
"""
import asyncio
import json
import threading

import pytest
from fastapi import BackgroundTasks

from sentury.harness import turno_em_curso
from sentury.harness.state import AnalysisState


async def _para_sempre():
    await asyncio.sleep(3600)


class TestRegistro:
    async def test_parar_cancela_e_marca(self):
        tarefa = asyncio.create_task(_para_sempre())
        turno_em_curso.registrar("s1", tarefa)
        try:
            assert turno_em_curso.em_curso("s1")
            assert turno_em_curso.parar("s1") is True
            with pytest.raises(asyncio.CancelledError):
                await tarefa
            assert turno_em_curso.foi_parado(tarefa)
            assert not turno_em_curso.em_curso("s1")
        finally:
            turno_em_curso.esquecer("s1", tarefa)
        assert not turno_em_curso.foi_parado(tarefa)

    async def test_parar_de_outra_thread(self):
        tarefa = asyncio.create_task(_para_sempre())
        turno_em_curso.registrar("s2", tarefa)
        try:
            resultado = []
            t = threading.Thread(target=lambda: resultado.append(turno_em_curso.parar("s2")))
            t.start()
            t.join(2)
            assert resultado == [True]
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(tarefa, 2)
        finally:
            turno_em_curso.esquecer("s2", tarefa)

    async def test_sem_turno_nao_para_nada(self):
        assert turno_em_curso.parar("ninguem") is False

    async def test_turno_acabado_nao_conta(self):
        tarefa = asyncio.create_task(asyncio.sleep(0))
        await tarefa
        turno_em_curso.registrar("s3", tarefa)
        try:
            assert turno_em_curso.parar("s3") is False and not turno_em_curso.foi_parado(tarefa)
        finally:
            turno_em_curso.esquecer("s3", tarefa)

    async def test_esquecer_nao_apaga_o_turno_novo(self):
        velho = asyncio.create_task(_para_sempre())
        novo = asyncio.create_task(_para_sempre())
        turno_em_curso.registrar("s4", velho)
        turno_em_curso.registrar("s4", novo)
        turno_em_curso.esquecer("s4", velho)
        try:
            assert turno_em_curso.em_curso("s4")
            assert turno_em_curso.parar("s4")
            with pytest.raises(asyncio.CancelledError):
                await novo
            assert not velho.done()
        finally:
            velho.cancel()
            turno_em_curso.esquecer("s4", novo)


async def _eventos(resposta):
    async for pedaco in resposta.body_iterator:
        texto = pedaco.decode() if isinstance(pedaco, bytes) else pedaco
        for linha in texto.splitlines():
            if linha.startswith("data: "):
                yield json.loads(linha[6:])


async def test_o_stream_termina_com_parado_e_nao_como_queda(monkeypatch):
    """Pelo endpoint de verdade: o turno comeca, o parar chega de outra
    thread, e o ultimo evento e `parado`: o cliente trata como o botao de
    parar, e nao como "conexao encerrada antes do resultado"."""
    from sentury import main

    comecou = asyncio.Event()
    cancelado = []

    async def handle_message(state, mensagem, progress_cb=None, effort=None):
        progress_cb({"type": "stage", "text": "Clicando…"})
        comecou.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelado.append(True)
            raise

    async def load_state(sessao, usuario):
        return None, AnalysisState.new(sessao, usuario)

    monkeypatch.setattr(main.orchestrator, "handle_message", handle_message)
    monkeypatch.setattr(main, "_load_state", load_state)

    payload = main.ChatRequest(session_id="parar-pelo-atalho", user_id="u", message="jogue pokemon")
    resposta = await main.chat_stream(payload, BackgroundTasks(), None)

    async def apertar_quando_comecar():
        await comecou.wait()
        await asyncio.to_thread(turno_em_curso.parar, "parar-pelo-atalho")

    async def coletar():
        return [e async for e in _eventos(resposta)]

    apertador = asyncio.create_task(apertar_quando_comecar())
    # Sem o turno registrado o parar nao acha nada e o stream nunca acaba:
    # o prazo faz disso uma falha, nao uma suite travada.
    eventos = await asyncio.wait_for(coletar(), 10)
    await apertador

    assert eventos[0] == {"type": "stage", "text": "Clicando…"}
    assert eventos[-1] == {"type": "parado"}
    assert cancelado == [True]
    assert not turno_em_curso.em_curso("parar-pelo-atalho")
