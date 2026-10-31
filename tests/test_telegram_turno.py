"""O turno do Telegram segue o do painel: uma trava por sessao, mensagem no
meio do turno vira orientacao, /parar para, e /alerta e /cron respondem no chat."""
import asyncio
from types import SimpleNamespace

import pytest

from sentury.external import telegram_gateway as tg
from sentury.harness import caixa_do_turno, turno_em_curso


class _Store:
    def __init__(self):
        self.dados = {}

    async def get(self, chave):
        return self.dados.get(chave)

    async def set(self, chave, valor, ttl=None):
        self.dados[chave] = valor

    async def delete(self, chave):
        self.dados.pop(chave, None)


class _Orquestrador:
    """Segura o turno ate `solto` e guarda o que viu no historico."""

    def __init__(self):
        self.pedidos = []
        self.solto = asyncio.Event()
        self.historicos = []

    async def handle_message(self, state, texto):
        self.pedidos.append(texto)
        await self.solto.wait()
        caixa_do_turno.aplicar(state)
        self.historicos.append([m.get("content", "") for m in state.history])
        return {"message": f"feito: {texto}"}


@pytest.fixture
def bot(monkeypatch):
    enviados = []

    async def _enviar(client, token, chat_id, texto):
        enviados.append(texto)

    async def _post(*a, **k):
        return None

    monkeypatch.setattr(tg, "tg_send_text", _enviar)
    monkeypatch.setattr(tg, "tg_post", _post)
    caixa_do_turno._limpar_para_testes()
    orq = _Orquestrador()
    manager = tg.TelegramBotManager(orq, _Store(), SimpleNamespace(SESSION_TTL_SEC=60))
    return manager, orq, enviados


async def _esperar(condicao):
    for _ in range(200):
        if condicao():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condicao nao aconteceu")


@pytest.mark.asyncio
async def test_mensagem_no_meio_do_turno_orienta_em_vez_de_abrir_outro(bot):
    manager, orq, enviados = bot
    primeiro = asyncio.create_task(manager._process_message("t", None, 7, "resuma a pasta"))
    await _esperar(lambda: turno_em_curso.em_curso("telegram_7"))

    await manager._process_message("t", None, 7, "só os arquivos .md")
    assert orq.pedidos == ["resuma a pasta"]
    assert "Anotado" in enviados[-1]

    orq.solto.set()
    await primeiro
    assert any("só os arquivos .md" in c for c in orq.historicos[0])
    assert enviados[-1] == "feito: resuma a pasta"


@pytest.mark.asyncio
async def test_parar_encerra_o_turno(bot):
    manager, orq, enviados = bot
    turno = asyncio.create_task(manager._process_message("t", None, 8, "tarefa longa"))
    await _esperar(lambda: turno_em_curso.em_curso("telegram_8"))

    await manager._process_message("t", None, 8, "/parar")
    await turno
    assert "Parando" in enviados[0]
    assert "Parei" in enviados[-1]
    assert not turno_em_curso.em_curso("telegram_8")

    await manager._process_message("t", None, 8, "/parar")
    assert "nada rodando" in enviados[-1]


@pytest.mark.asyncio
async def test_alerta_e_cron_usam_os_comandos_do_painel_com_o_chat(bot):
    manager, orq, enviados = bot
    chamadas = []
    manager.comandos = {"/cron": lambda s, u, t, chat_id=None: chamadas.append((s, t, chat_id)) or "agendado"}

    await manager._process_message("t", None, 9, "/cron todo dia às 9h me dê um resumo")
    assert chamadas == [("telegram_9", "/cron todo dia às 9h me dê um resumo", 9)]
    assert enviados == ["agendado"]
    assert orq.pedidos == []


def test_o_menu_tem_parar_e_cron():
    comandos = [c["command"] for c in tg._tg_comandos()]
    assert "parar" in comandos and "cron" in comandos


def test_o_main_registra_alerta_e_cron_no_telegram():
    from sentury import main

    assert set(main.telegram_manager.comandos) == {"/alerta", "/cron"}


class TestAprovarPeloTelegram:
    """O cartão de aprovação vira botões na conversa: um toque registra a
    resposta como o cartão do painel e, se liberou, a tarefa continua."""

    @pytest.fixture
    def com_permissao(self, monkeypatch):
        posts = []
        enviados = []

        async def _enviar(client, token, chat_id, texto):
            enviados.append(texto)

        async def _post(client, token, metodo, **k):
            posts.append((metodo, k.get("json") or {}))

        class _Orq:
            def __init__(self):
                self.pedidos = []

            async def handle_message(self, state, texto):
                self.pedidos.append(texto)
                if len(self.pedidos) == 1:
                    return {"message": "Parei aqui: `executar_comando rm build` precisa da sua autorização.",
                            "permissao": {"chave": "k", "comando": "executar_comando rm build",
                                          "motivo": "apaga a pasta build"}}
                return {"message": "feito"}

        monkeypatch.setattr(tg, "tg_send_text", _enviar)
        monkeypatch.setattr(tg, "tg_post", _post)
        respostas = []
        from sentury.tools import permissoes

        monkeypatch.setattr(permissoes, "responder", lambda c, r, s="": respostas.append((c, r, s)) or {})
        caixa_do_turno._limpar_para_testes()
        orq = _Orq()
        manager = tg.TelegramBotManager(orq, _Store(), SimpleNamespace(
            SESSION_TTL_SEC=60, telegram_allowed_id_list=[7]))
        return manager, orq, posts, enviados, respostas

    def _botoes(self, posts):
        pedido = next(j for m, j in posts if m == "sendMessage" and "reply_markup" in j)
        return pedido, [b for linha in pedido["reply_markup"]["inline_keyboard"] for b in linha]

    def _toque(self, botao, chat=7, quem=7):
        return {"id": "q1", "data": botao["callback_data"], "from": {"id": quem},
                "message": {"message_id": 99, "chat": {"id": chat}}}

    @pytest.mark.asyncio
    async def test_pedido_vira_botoes_e_o_toque_libera_e_continua(self, com_permissao):
        manager, orq, posts, enviados, respostas = com_permissao
        await manager._process_message("t", None, 7, "limpa o build")
        pedido, botoes = self._botoes(posts)
        assert "executar_comando rm build" in pedido["text"] and "apaga a pasta build" in pedido["text"]
        assert [b["text"] for b in botoes] == ["Nesta conversa", "Só desta vez", "Sempre", "Não"]
        assert all(len(b["callback_data"].encode()) <= 64 for b in botoes), "o Telegram corta em 64 bytes"

        await manager._handle_botao("t", None, self._toque(botoes[0]))
        assert respostas == [("executar_comando rm build", "sessao", "telegram_7")]
        assert ("editMessageReplyMarkup", {"chat_id": 7, "message_id": 99,
                                           "reply_markup": {"inline_keyboard": []}}) in posts
        assert orq.pedidos[-1] == "Autorizado. Pode rodar `executar_comando rm build`."

        # O mesmo botão de novo não vale: o pedido já foi respondido.
        await manager._handle_botao("t", None, self._toque(botoes[0]))
        assert len(respostas) == 1 and len(orq.pedidos) == 2

    @pytest.mark.asyncio
    async def test_o_botao_vale_depois_de_reiniciar(self, com_permissao):
        """A mensagem com os botões fica no Telegram enquanto o Sentury reinicia; o
        toque depois disso ainda libera e continua, e só uma vez."""
        manager, orq, posts, enviados, respostas = com_permissao
        await manager._process_message("t", None, 7, "limpa o build")
        _, botoes = self._botoes(posts)

        reiniciado = tg.TelegramBotManager(orq, manager.session_store, manager.settings)
        await reiniciado._handle_botao("t", None, self._toque(botoes[1]))
        assert respostas == [("executar_comando rm build", "uma_vez", "telegram_7")]
        assert orq.pedidos[-1] == "Autorizado. Pode rodar `executar_comando rm build`."

        de_novo = tg.TelegramBotManager(orq, manager.session_store, manager.settings)
        await de_novo._handle_botao("t", None, self._toque(botoes[1]))
        assert len(respostas) == 1

    @pytest.mark.asyncio
    async def test_negar_nao_continua(self, com_permissao):
        manager, orq, posts, enviados, respostas = com_permissao
        await manager._process_message("t", None, 7, "limpa o build")
        _, botoes = self._botoes(posts)
        await manager._handle_botao("t", None, self._toque(botoes[-1]))
        assert respostas[-1][1] == "negar" and len(orq.pedidos) == 1 and "Não rodei" in enviados[-1]

    @pytest.mark.asyncio
    async def test_quem_esta_fora_da_lista_nao_aprova(self, com_permissao):
        manager, orq, posts, enviados, respostas = com_permissao
        await manager._process_message("t", None, 7, "limpa o build")
        _, botoes = self._botoes(posts)
        await manager._handle_botao("t", None, self._toque(botoes[0], chat=8, quem=8))
        assert respostas == [] and len(orq.pedidos) == 1

    def test_so_desta_vez_mostra_so_o_que_libera(self):
        botoes = [b["text"] for linha in tg.botoes_da_permissao("x", so_desta_vez=True)["inline_keyboard"]
                  for b in linha]
        assert botoes == ["Só desta vez", "Não"]
        assert tg.ler_botao("perm:x:z") is None and tg.ler_botao("outro:x:s") is None
