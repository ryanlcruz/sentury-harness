"""Foto e documento mandados pelo Telegram chegam ao turno como o anexo do painel:
a imagem vai ao modelo, o arquivo é lido na chegada e os dois viram artefato."""
import asyncio
import base64
import logging
from types import SimpleNamespace

import pytest

from sentury.external import telegram_gateway as tg
from sentury.harness import caixa_do_turno
from sentury.harness.state import AnalysisState


class _Store:
    def __init__(self):
        self.dados = {}

    async def get(self, chave):
        return self.dados.get(chave)

    async def set(self, chave, valor, ttl=None):
        self.dados[chave] = valor


class _Orquestrador:
    def __init__(self):
        self.turnos = []

    async def handle_message(self, state, texto):
        self.turnos.append((texto, state))
        return {"message": "ok"}


class _Baixado:
    def __init__(self, conteudo):
        self.content = conteudo

    def raise_for_status(self):
        return None


class _Cliente:
    """Só o download do arquivo: o resto da Bot API passa por `tg_post`."""

    def __init__(self, conteudo):
        self.conteudo = conteudo
        self.urls = []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        return _Baixado(self.conteudo)


@pytest.fixture
def bot(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.setattr(tg, "_COALESCE_WINDOW", 0)
    enviados, posts = [], []

    async def _enviar(client, token, chat_id, texto):
        enviados.append(texto)

    async def _post(client, token, metodo, **k):
        posts.append(metodo)
        if metodo == "getFile":
            return SimpleNamespace(json=lambda: {"result": {"file_path": "documentos/arquivo"}})
        return None

    monkeypatch.setattr(tg, "tg_send_text", _enviar)
    monkeypatch.setattr(tg, "tg_post", _post)
    caixa_do_turno._limpar_para_testes()
    orq = _Orquestrador()
    manager = tg.TelegramBotManager(orq, _Store(), SimpleNamespace(SESSION_TTL_SEC=60, telegram_allowed_id_list=[]))
    return manager, orq, enviados, posts


async def _receber(manager, cliente, mensagem):
    await manager._handle_message("t", cliente, {"chat": {"id": 5}, "from": {"id": 5}, "message_id": 31, **mensagem})
    await asyncio.wait_for(manager._buffer_tasks[5], 2)


@pytest.mark.asyncio
async def test_foto_com_legenda_vai_ao_modelo_e_vira_artefato(bot):
    manager, orq, enviados, _ = bot
    foto = b"\x89PNG-foto"
    cliente = _Cliente(foto)
    await _receber(manager, cliente, {"caption": "o que tem nessa tela?",
                                      "photo": [{"file_id": "p", "file_size": 10}, {"file_id": "g", "file_size": 20}]})

    texto, state = orq.turnos[0]
    assert texto.startswith("o que tem nessa tela?") and "foto_31.jpg" in texto
    assert state.imagens_do_turno[0]["data_url"] == "data:image/jpeg;base64," + base64.b64encode(foto).decode()
    assert [a["attachment"]["filename"] for a in state.artifacts.values()] == ["foto_31.jpg"]
    assert enviados == ["ok"]


@pytest.mark.asyncio
async def test_documento_sem_legenda_e_lido_na_chegada(bot):
    manager, orq, _, _ = bot
    cliente = _Cliente("reunião às 15h com o fornecedor".encode("utf-8"))
    await _receber(manager, cliente, {"document": {"file_id": "d", "file_name": "pauta.txt",
                                                   "mime_type": "text/plain", "file_size": 40}})

    texto, state = orq.turnos[0]
    assert texto == "[anexos: pauta.txt]"
    assert any("reunião às 15h" in m["content"] and m["role"] == "system" for m in state.history)
    assert not getattr(state, "imagens_do_turno", None)


@pytest.mark.asyncio
async def test_arquivo_grande_demais_avisa_e_nao_baixa(bot):
    manager, orq, enviados, posts = bot
    cliente = _Cliente(b"x")
    await _receber(manager, cliente, {"document": {"file_id": "d", "file_name": "video.mp4",
                                                   "file_size": tg._TETO_DO_ANEXO + 1}})

    assert "video.mp4 passa de 8 MB" in enviados[0]
    assert cliente.urls == [] and "getFile" not in posts
    assert orq.turnos == []


def test_imagens_alem_do_limite_ficam_de_fora_e_o_modelo_sabe():
    state = AnalysisState.new("telegram_9", "u")
    anexos = [{"nome": f"foto_{i}.jpg", "data_url": "data:image/jpeg;base64,eA=="} for i in range(6)]
    texto = tg._com_anexos(state, "telegram_9", "compare", anexos)
    assert len(state.imagens_do_turno) == tg._IMAGENS_POR_PEDIDO
    assert "2 anexo(s) ficaram de fora" in texto


def test_o_token_nao_aparece_no_log_do_download():
    registro = logging.LogRecord("httpx", logging.INFO, "", 0,
                                 "GET https://api.telegram.org/file/bot123:SEGREDO/documentos/a.txt", (), None)
    tg._telegram_token_filter.filter(registro)
    assert "SEGREDO" not in registro.getMessage()
    assert "https://api.telegram.org/file/bot<redacted>/documentos/a.txt" in registro.getMessage()
