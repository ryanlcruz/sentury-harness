"""A versão adaptada do agente no Telegram: markdown do painel -> HTML seguro
do Telegram + chunking < 4096. Sem isto, respostas longas (tabela/plano) falham
no envio e o markdown cru aparece sem formatação."""
from sentury.external.telegram_gateway import (
    _TelegramTokenRedaction,
    chunk_telegram,
    markdown_to_telegram_html,
)


def test_filtro_de_log_remove_token_da_url_do_telegram():
    record = __import__("logging").LogRecord(
        "httpx", 20, __file__, 1,
        "HTTP Request: POST %s", ("https://api.telegram.org/bot123:segredo/getMe",), None,
    )
    assert _TelegramTokenRedaction().filter(record) is True
    rendered = record.getMessage()
    assert "123:segredo" not in rendered
    assert "bot<redacted>/getMe" in rendered


def test_headings_bold_and_bullets():
    h = markdown_to_telegram_html("## Título\nAqui vai **negrito**.\n- item um\n- item dois")
    assert "<b>Título</b>" in h
    assert "<b>negrito</b>" in h
    assert "• item um" in h


def test_escapes_html_special_chars():
    # Um "<" que não é HTML não pode quebrar o parse do Telegram.
    h = markdown_to_telegram_html("NPS < -30 e a & b")
    assert "&lt;" in h
    assert "&amp;" in h
    assert "<" not in h.replace("&lt;", "")  # nenhum '<' cru sobrou


def test_table_becomes_monospace_pre():
    md = "| Filial | SLA |\n| --- | --- |\n| Campinas | 48,1% |\n| Belém | 79,7% |"
    h = markdown_to_telegram_html(md)
    assert "<pre>" in h and "</pre>" in h
    assert "Campinas" in h and "Belém" in h
    assert "---" not in h  # a linha separadora some


def test_mermaid_block_becomes_note():
    h = markdown_to_telegram_html("```mermaid\nflowchart TD\nA --> B\n```")
    assert "[diagrama" in h  # vira aviso, não o código cru
    assert "flowchart" not in h  # o código mermaid cru não vai pro Telegram


def test_svg_block_becomes_note():
    # SVG inline (painel) vira aviso no Telegram: o arquivo vai como anexo.
    h = markdown_to_telegram_html('```svg\n<svg><rect/></svg>\n```')
    assert "[diagrama" in h
    assert "<rect" not in h


def test_chunking_respects_limit_and_covers_content():
    texto = "linha de conteudo. " * 1500  # ~28k chars
    pedacos = chunk_telegram(texto)
    assert len(pedacos) > 1
    assert all(len(p) <= 3800 for p in pedacos)
    assert sum(p.count("linha de conteudo") for p in pedacos) == 1500


def test_short_text_single_chunk():
    assert chunk_telegram("oi") == ["oi"]
    assert chunk_telegram("") == []


def test_pre_block_not_split_broken():
    # Um <pre> grande deve terminar fechado em cada pedaço.
    md = "| A | B |\n| - | - |\n" + "\n".join(f"| v{i} | w{i} |" for i in range(600))
    pedacos = chunk_telegram(markdown_to_telegram_html(md))
    for p in pedacos:
        assert p.count("<pre>") == p.count("</pre>")


# --- Robustez de entrega: retry/429 ---
import httpx
from sentury.external.telegram_gateway import tg_post


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
    def json(self):
        return self._payload


class _FakeClient:
    """Devolve respostas roteirizadas; conta as chamadas."""
    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.calls = 0
    async def post(self, url, **kwargs):
        self.calls += 1
        item = self.roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def test_tg_post_retries_on_429(monkeypatch):
    import sentury.external.telegram_gateway as tg
    slept = []
    async def _fake_sleep(s): slept.append(s)
    monkeypatch.setattr(tg.asyncio, "sleep", _fake_sleep)
    client = _FakeClient([
        _FakeResp(429, {"parameters": {"retry_after": 2}}),
        _FakeResp(200, {"ok": True}),
    ])
    resp = await tg_post(client, "tok", "sendMessage", json={"x": 1})
    assert resp.status_code == 200
    assert client.calls == 2
    assert any(s >= 2 for s in slept)  # respeitou o retry_after


async def test_tg_post_retries_on_network_error(monkeypatch):
    import sentury.external.telegram_gateway as tg
    async def _fake_sleep(s): pass
    monkeypatch.setattr(tg.asyncio, "sleep", _fake_sleep)
    client = _FakeClient([
        httpx.ConnectError("boom"),
        _FakeResp(200, {"ok": True}),
    ])
    resp = await tg_post(client, "tok", "sendMessage", json={"x": 1})
    assert resp is not None and resp.status_code == 200
    assert client.calls == 2


async def test_tg_post_gives_up_after_retries(monkeypatch):
    import sentury.external.telegram_gateway as tg
    async def _fake_sleep(s): pass
    monkeypatch.setattr(tg.asyncio, "sleep", _fake_sleep)
    client = _FakeClient([httpx.ConnectError("x")] * 10)
    resp = await tg_post(client, "tok", "sendMessage", json={"x": 1}, max_retries=2)
    assert resp is None
    assert client.calls == 3  # 1 + 2 retries


# --- Mídia nativa: ![](url) vira sendAnimation/sendPhoto ---
async def test_media_markdown_vira_animation(monkeypatch):
    import sentury.external.telegram_gateway as tg
    chamadas = []
    class _C:
        async def post(self, url, **kw):
            chamadas.append((url.rsplit("/", 1)[-1], kw.get("json", {})))
            return _FakeResp(200)
    resto = await tg._tg_send_media_and_strip(_C(), "tok", 1, "![gif](https://media.tenor.com/x/a.gif)")
    assert chamadas[0][0] == "sendAnimation"
    assert chamadas[0][1]["animation"].endswith(".gif")
    assert resto == ""


async def test_media_png_vira_photo_e_mantem_texto(monkeypatch):
    import sentury.external.telegram_gateway as tg
    chamadas = []
    class _C:
        async def post(self, url, **kw):
            chamadas.append(url.rsplit("/", 1)[-1])
            return _FakeResp(200)
    resto = await tg._tg_send_media_and_strip(_C(), "tok", 1, "veja ![img](http://x/y.png) aqui")
    assert chamadas[0] == "sendPhoto"
    assert "veja" in resto and "aqui" in resto and "![" not in resto


# --- Coalescência: mensagens rápidas viram um turno só ---
async def test_coalesce_mensagens_rapidas(monkeypatch):
    import sentury.external.telegram_gateway as tg
    monkeypatch.setattr(tg, "_COALESCE_WINDOW", 0.2)

    class _S:
        telegram_allowed_id_list = []
    mgr = tg.TelegramBotManager(orchestrator=None, session_store=None, settings=_S())
    capturado = {}
    async def _fake(token, client, chat_id, text, anexos=None):
        capturado["text"] = text
        capturado["anexos"] = anexos
    mgr._process_message = _fake
    import asyncio
    for t in ("parte um", "parte dois", "parte tres"):
        await mgr._handle_message("tok", None, {"chat": {"id": 7}, "text": t, "from": {"id": 7}})
    await asyncio.sleep(0.45)
    assert capturado.get("text") == "parte um\nparte dois\nparte tres"
    assert not capturado.get("anexos")


async def test_coalesce_whitelist_bloqueia(monkeypatch):
    import sentury.external.telegram_gateway as tg
    class _S:
        telegram_allowed_id_list = [123]  # só o 123
    mgr = tg.TelegramBotManager(orchestrator=None, session_store=None, settings=_S())
    posts = []
    async def _fake_post(client, token, method, **kw):
        posts.append(method); return _FakeResp(200)
    monkeypatch.setattr(tg, "tg_post", _fake_post)
    await mgr._handle_message("tok", None, {"chat": {"id": 999}, "text": "oi", "from": {"id": 999}})
    assert 999 not in mgr._buffers  # não bufferizou o não-autorizado
    assert posts and posts[0] == "sendMessage"


# --- Leitura disputada: outro processo lê o mesmo bot ---
async def test_conflito_409_avisa_uma_vez_e_espera_cada_vez_mais(monkeypatch, caplog):
    import asyncio as _asyncio
    import logging
    import sentury.external.telegram_gateway as tg

    respostas = [_FakeResp(409), _FakeResp(409), _FakeResp(409), _FakeResp(200, {"result": []}), _FakeResp(409)]

    class _Cliente:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            if not respostas:
                raise _asyncio.CancelledError()
            return respostas.pop(0)

    esperas = []

    async def _dormir(s):
        esperas.append(s)

    class _S:
        telegram_allowed_id_list = []

    mgr = tg.TelegramBotManager(orchestrator=None, session_store=None, settings=_S())

    async def _info(token):
        return {"username": "teste"}

    async def _comandos(client, token):
        return None

    monkeypatch.setattr(mgr, "get_bot_info", _info)
    monkeypatch.setattr(mgr, "_set_commands", _comandos)
    monkeypatch.setattr(tg.httpx, "AsyncClient", lambda *a, **k: _Cliente())
    monkeypatch.setattr(tg.asyncio, "sleep", _dormir)
    with caplog.at_level(logging.WARNING, logger=tg.logger.name):
        await mgr._loop("tok")

    # Dobra a cada recusa; a leitura que funciona zera a espera.
    assert esperas == [5, 10, 20, 5]
    avisos = [r for r in caplog.records if "outro processo está lendo este bot" in r.getMessage()]
    assert len(avisos) == 2, "um aviso por conflito, não um por tentativa"
