import asyncio
import base64
import html as _html
import json
import logging
import re
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple
import httpx

from ..harness import caixa_do_turno, trava_da_sessao, turno_em_curso
from ..harness.state import AnalysisState
from ..harness.orchestrator import SenturyOrchestrator

logger = logging.getLogger(__name__)


class _TelegramTokenRedaction(logging.Filter):
    """Impede que URLs da Bot API levem o token para logs do HTTP client."""

    # O download de arquivo leva o token em `/file/bot<token>/`.
    _pattern = re.compile(r"https://api\.telegram\.org/(file/)?bot[^/\s\"']+", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        sanitized = self._pattern.sub(lambda m: f"https://api.telegram.org/{m.group(1) or ''}bot<redacted>", rendered)
        if sanitized != rendered:
            record.msg = sanitized
            record.args = ()
        from ..exec.logs import proteger_registro

        proteger_registro(record)
        return True


_telegram_token_filter = _TelegramTokenRedaction()
logger.addFilter(_telegram_token_filter)
logging.getLogger("httpx").addFilter(_telegram_token_filter)

# Telegram limita o tamanho e a formatação das mensagens.
# Convertemos para HTML aceito pelo serviço e dividimos respostas longas.
_TG_LIMIT = 4096
# Espera entre tentativas quando o Telegram recusa a leitura.
_ESPERA_INICIAL = 5
_ESPERA_MAXIMA = 300
_TG_CHUNK = 3800  # folga de segurança para o parse HTML


def _table_to_monospace(bloco: List[str]) -> str:
    """Converte uma tabela markdown (linhas com |) em texto alinhado monoespaçado."""
    linhas = []
    for ln in bloco:
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        celulas = [c.strip() for c in ln.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in celulas):  # linha separadora ---
            continue
        linhas.append(celulas)
    if not linhas:
        return ""
    n = max(len(r) for r in linhas)
    linhas = [r + [""] * (n - len(r)) for r in linhas]
    larg = [max(len(r[i]) for r in linhas) for i in range(n)]
    out = ["  ".join(c.ljust(larg[i]) for i, c in enumerate(r)).rstrip() for r in linhas]
    return "\n".join(out)


def markdown_to_telegram_html(md: str) -> str:
    """GFM (o que o painel renderiza) -> HTML seguro do Telegram.
    Tabelas viram <pre> alinhado; ```mermaid vira aviso; **x** -> <b>; `x` -> <code>."""
    linhas = (md or "").split("\n")
    partes: List[str] = []
    i = 0
    while i < len(linhas):
        ln = linhas[i]
        stripped = ln.strip()

        # Bloco de código cercado (``` ... ```)
        if stripped.startswith("```"):
            lang = stripped[3:].strip().lower()
            corpo = []
            i += 1
            while i < len(linhas) and not linhas[i].strip().startswith("```"):
                corpo.append(linhas[i])
                i += 1
            i += 1  # pula o ``` de fechamento
            if lang in ("mermaid", "svg"):
                partes.append("<i>[diagrama enviado como arquivo abaixo]</i>")
            else:
                partes.append("<pre>" + _html.escape("\n".join(corpo)) + "</pre>")
            continue

        # Tabela markdown (linhas consecutivas começando com |)
        if stripped.startswith("|"):
            bloco = []
            while i < len(linhas) and linhas[i].strip().startswith("|"):
                bloco.append(linhas[i])
                i += 1
            texto = _table_to_monospace(bloco)
            if texto:
                partes.append("<pre>" + _html.escape(texto) + "</pre>")
            continue

        # Prosa: escapa HTML e converte marcadores inline
        i += 1
        texto = _html.escape(ln)
        # Cabeçalhos ## / ### -> negrito
        texto = re.sub(r"^\s*#{1,6}\s*(.+?)\s*$", r"<b>\1</b>", texto)
        # Marcadores de lista - / * -> bullet
        texto = re.sub(r"^(\s*)[-*]\s+", r"\1• ", texto)
        # **negrito** e *itálico*/_itálico_ e `código`
        texto = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texto)
        texto = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", texto)
        texto = re.sub(r"`([^`]+)`", r"<code>\1</code>", texto)
        partes.append(texto)

    return "\n".join(partes).strip()


def chunk_telegram(texto: str, tamanho: int = _TG_CHUNK) -> List[str]:
    """Quebra em pedaços < limite, preferindo cortar em quebras de linha/parágrafo
    e nunca no meio de uma tag <pre> (fecha e reabre para não quebrar o HTML)."""
    if len(texto) <= tamanho:
        return [texto] if texto else []
    pedacos: List[str] = []
    atual = ""
    for linha in texto.split("\n"):
        if len(atual) + len(linha) + 1 > tamanho and atual:
            pedacos.append(atual.rstrip("\n"))
            atual = ""
        # Linha isolada maior que o limite: fatia bruta
        while len(linha) > tamanho:
            pedacos.append(linha[:tamanho])
            linha = linha[tamanho:]
        atual += linha + "\n"
    if atual.strip():
        pedacos.append(atual.rstrip("\n"))
    # Conserta <pre> partido entre pedaços
    consertados = []
    for p in pedacos:
        abre = p.count("<pre>")
        fecha = p.count("</pre>")
        if abre > fecha:
            p += "</pre>"
        elif fecha > abre:
            p = "<pre>" + p
        consertados.append(p)
    return consertados


async def tg_post(client: httpx.AsyncClient, token: str, method: str, *,
                  json: Any = None, data: Any = None, files: Any = None,
                  max_retries: int = 3) -> Optional[httpx.Response]:
    """Respeita `retry_after` do Telegram e repete falhas transitórias de rede."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    backoff = 1.0
    for attempt in range(max_retries + 1):
        try:
            resp = await client.post(url, json=json, data=data, files=files, timeout=20.0)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt >= max_retries:
                logger.warning("Telegram %s falhou após %d tentativas: %s", method, attempt + 1, exc)
                return None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10)
            continue
        if resp.status_code == 429:
            retry_after = 1.0
            try:
                retry_after = float(resp.json().get("parameters", {}).get("retry_after", 1))
            except Exception:
                pass
            logger.info("Telegram 429 (flood): aguardando %ss e reenviando %s", retry_after, method)
            await asyncio.sleep(min(retry_after, 30) + 0.3)
            continue
        return resp
    return None


# Imagem/gif em markdown: ![alt](url)
_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)")


async def _tg_send_media_and_strip(client: httpx.AsyncClient, token: str, chat_id: Any, text: str) -> str:
    """Envia como MÍDIA NATIVA cada ![](url) do texto (gif -> sendAnimation,
    imagem -> sendPhoto; o Telegram baixa a URL, sem storage local) e devolve o
    texto sem esses marcadores."""
    for m in _MD_IMG_RE.finditer(text or ""):
        url = m.group(1)
        base = url.lower().split("?")[0]
        if base.endswith(".gif"):
            metodo, chave = "sendAnimation", "animation"
        else:
            metodo, chave = "sendPhoto", "photo"
        await tg_post(client, token, metodo, json={"chat_id": chat_id, chave: url})
    return _MD_IMG_RE.sub("", text or "").strip()


async def tg_send_text(client: httpx.AsyncClient, token: str, chat_id: Any, text: str) -> None:
    """Envia texto ADAPTADO (HTML + chunk < 4096) com retry, caindo para texto
    puro se o Telegram rejeitar a formatação: nunca deixa o usuário sem resposta.
    Imagens/gifs em markdown ![](url) viram mídia NATIVA (sendAnimation/sendPhoto);
    o Telegram baixa a URL: não guardamos nada localmente."""
    text = await _tg_send_media_and_strip(client, token, chat_id, text)
    if not text.strip():
        return
    html_text = markdown_to_telegram_html(text)
    for pedaco in chunk_telegram(html_text) or [text]:
        resp = await tg_post(client, token, "sendMessage", json={
            "chat_id": chat_id, "text": pedaco, "parse_mode": "HTML", "disable_web_page_preview": True,
        })
        if resp is None or resp.status_code != 200:
            code = resp.status_code if resp is not None else "sem resposta"
            logger.warning("Telegram rejeitou HTML (%s); reenviando como texto puro.", code)
            await tg_post(client, token, "sendMessage", json={
                "chat_id": chat_id, "text": re.sub(r"<[^>]+>", "", pedaco),
            })


# Janela de coalescência: mensagens do mesmo chat dentro desse intervalo (s) são
# agrupadas num turno só. Curto o bastante para não parecer lento.
_COALESCE_WINDOW = 1.5

# Os mesmos limites do painel: tamanho de cada anexo e quantos vão num pedido.
_TETO_DO_ANEXO = 8 * 1024 * 1024
_IMAGENS_POR_PEDIDO = 4
_ARQUIVOS_POR_PEDIDO = 6


def _com_anexos(state: Any, session_id: str, texto: str, anexos: List[Dict[str, str]]) -> str:
    """Foto e documento entram no turno pelo mesmo caminho do anexo do painel. Devolve
    a mensagem do turno, com os nomes do que chegou e do que ficou de fora."""
    from ..tools.recebidos import entregar_ao_turno

    imagens = [a for a in anexos if a["data_url"].startswith("data:image/")]
    arquivos = [a for a in anexos if not a["data_url"].startswith("data:image/")]
    entregues = imagens[:_IMAGENS_POR_PEDIDO]
    caminhos = entregar_ao_turno(state, session_id, entregues, arquivos[:_ARQUIVOS_POR_PEDIDO])
    nomes = [a["nome"] for a in entregues] + [c.name for c in caminhos]
    linha = f"[anexos: {', '.join(nomes)}]" if nomes else ""
    sobra = max(0, len(imagens) - _IMAGENS_POR_PEDIDO) + max(0, len(arquivos) - _ARQUIVOS_POR_PEDIDO)
    if sobra:
        linha += (f" [{sobra} anexo(s) ficaram de fora: até {_IMAGENS_POR_PEDIDO} imagens "
                  f"e {_ARQUIVOS_POR_PEDIDO} arquivos por pedido]")
    return "\n\n".join(p for p in (texto, linha.strip()) if p)

# Exemplos da ajuda quando o setor ativo não traz os seus.
_EXEMPLOS_NEUTROS = (
    "resuma as tarefas abertas",
    "pesquise na web e me traga as fontes",
    "monte um plano em etapas",
)


def _tg_comandos() -> List[Dict[str, str]]:
    """O menu do bot: os comandos do motor mais os atalhos do setor ativo."""
    from ..domains.do_setor import atalhos

    from ..domains.do_setor import metricas_vigiaveis

    do_setor = [{"command": a["comando"], "description": a["descricao"] or a["pergunta"]} for a in atalhos()]
    alerta = [{"command": "alerta", "description": "Avisar quando uma métrica passar do limite"}] if metricas_vigiaveis() else []
    return [
        {"command": "start", "description": "Iniciar conversa"},
        *do_setor,
        {"command": "parar", "description": "Parar o que está rodando"},
        {"command": "cron", "description": "Agendar um pedido"},
        {"command": "mesa", "description": "Abrir um assunto para os residentes conversarem"},
        *alerta,
        {"command": "skills", "description": "Skills disponíveis"},
        {"command": "help", "description": "O que posso fazer"},
        {"command": "reset", "description": "Nova conversa"},
    ]


def _tg_ajuda() -> str:
    from ..domains.do_setor import exemplos_de_pedido

    linhas = [f"• /{c['command']} — {c['description'][:1].lower()}{c['description'][1:]}" for c in _tg_comandos()
              if c["command"] != "help"]
    exemplos = exemplos_de_pedido() or _EXEMPLOS_NEUTROS
    return (
        "**Sou o Sentury.** Pergunte direto ou use os comandos:\n\n"
        + "\n".join(linhas)
        + "\n\nExemplos: " + ", ".join(f'"{e}"' for e in exemplos) + "."
        + "\n\nSe eu estiver trabalhando, o que você mandar entra no próximo passo."
    )


def _pergunta_do_atalho(cmd: str) -> Optional[str]:
    from ..domains.do_setor import atalhos

    nome = cmd.lstrip("/").split("@", 1)[0]
    return next((a["pergunta"] for a in atalhos() if a["comando"] == nome), None)


# As respostas do cartão de aprovação, como botões. O código de uma letra cabe
# no `callback_data` (64 bytes); o comando fica guardado do nosso lado.
_BOTOES_DA_PERMISSAO = (("s", "sessao", "Nesta conversa"), ("u", "uma_vez", "Só desta vez"),
                        ("a", "sempre", "Sempre"), ("n", "negar", "Não"))
_PEDIDOS_GUARDADOS = 50


def _arquivo_dos_pedidos():
    from ..tools.arquivos import casa_do_sentury

    return casa_do_sentury() / "telegram_pedidos.json"


def _ler_pedidos() -> Dict[str, Dict[str, Any]]:
    """Os pedidos ficam em disco: a mensagem com os botões continua no Telegram
    quando o Sentury reinicia, e o toque depois disso ainda precisa valer."""
    try:
        dados = json.loads(_arquivo_dos_pedidos().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar_pedidos(pedidos: Dict[str, Dict[str, Any]]) -> None:
    alvo = _arquivo_dos_pedidos()
    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tmp = alvo.with_suffix(".tmp")
        tmp.write_text(json.dumps(pedidos, ensure_ascii=False), encoding="utf-8")
        tmp.replace(alvo)
    except OSError:
        logger.warning("Não consegui guardar os pedidos de aprovação do Telegram.", exc_info=True)


def botoes_da_permissao(pedido_id: str, so_desta_vez: bool = False) -> Dict[str, Any]:
    """O `reply_markup` do pedido. Candidatura e envio de dado só liberam
    "só desta vez", como no cartão do painel."""
    botoes = [{"text": rotulo, "callback_data": f"perm:{pedido_id}:{codigo}"}
              for codigo, resposta, rotulo in _BOTOES_DA_PERMISSAO
              if not so_desta_vez or resposta in ("uma_vez", "negar")]
    return {"inline_keyboard": [botoes[:2], botoes[2:]] if len(botoes) > 2 else [botoes]}


def ler_botao(dados: str) -> Optional[Tuple[str, str]]:
    """`perm:<id>:<código>` → (id, resposta), ou None se não é nosso."""
    partes = str(dados or "").split(":")
    if len(partes) != 3 or partes[0] != "perm":
        return None
    resposta = next((r for codigo, r, _ in _BOTOES_DA_PERMISSAO if codigo == partes[2]), None)
    return (partes[1], resposta) if resposta else None


class TelegramBotManager:
    """Gerencia o ciclo de vida do bot de Telegram e o loop de Long Polling em background."""

    async def _set_commands(self, client: httpx.AsyncClient, token: str) -> None:
        """Registra o menu nativo do bot (o botão '/' passa a listar os comandos)."""
        await tg_post(client, token, "setMyCommands", json={"commands": _tg_comandos()})

    async def _tg_start(self, client: httpx.AsyncClient, token: str, chat_id: Any) -> None:
        """/start: saudação inicial e orientações de uso."""
        await tg_post(client, token, "sendChatAction", json={"chat_id": chat_id, "action": "typing"})
        saudacao = (
            "Olá! Sou o Sentury. "
            "Como posso te ajudar hoje?"
        )
        await tg_send_text(client, token, chat_id, saudacao)
        await tg_send_text(client, token, chat_id, "Toque em / para ver os comandos, ou me pergunte direto.")

    async def _keep_typing(self, client: httpx.AsyncClient, token: str, chat_id: Any) -> None:
        """Re-arma o 'digitando…' do Telegram (expira em ~5s) enquanto o agente
        processa uma resposta longa. Cancelado assim que a resposta fica pronta."""
        try:
            while True:
                await tg_post(client, token, "sendChatAction", json={"chat_id": chat_id, "action": "typing"})
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    def __init__(self, orchestrator: SenturyOrchestrator, session_store: Any, settings: Any):
        self.orchestrator = orchestrator
        self.session_store = session_store
        self.settings = settings
        self.running_task: Optional[asyncio.Task] = None
        self._status = "offline"  # offline, connecting, online
        self._current_token: Optional[str] = None
        # Coalescência de mensagens rápidas por chat.
        self._buffers: Dict[Any, List[str]] = {}
        self._anexos: Dict[Any, List[Dict[str, str]]] = {}
        self._buffer_tasks: Dict[Any, asyncio.Task] = {}
        # Comandos deterministicos do painel (/alerta, /cron), registrados pelo main.
        self.comandos: Dict[str, Any] = {}
        # Pedidos de aprovação esperando um toque nos botões: id → sessão e comando.
        self._pedidos: Dict[str, Dict[str, Any]] = _ler_pedidos()
        from .telegram_perguntas import PerguntasTelegram
        self._perguntas = PerguntasTelegram()
        # O que o painel faz depois de uma resposta (retomar o goal parado), ligado pelo main.
        self.depois_da_permissao: Optional[Callable[[str, str], None]] = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def current_token(self) -> Optional[str]:
        return self._current_token

    async def send_message(self, chat_id: Any, text: str) -> bool:
        """Envia uma mensagem avulsa (usado pelo cron/agendador) para um chat,
        já com a formatação adaptada (HTML + chunking). Retorna True se enviou."""
        token = self._current_token or getattr(self.settings, "TELEGRAM_TOKEN", None)
        if not token:
            return False
        try:
            async with httpx.AsyncClient() as client:
                await tg_send_text(client, token, chat_id, text)
            return True
        except Exception as exc:
            logger.error("Falha ao enviar mensagem de cron no Telegram: %s", exc)
            return False

    async def avisar_residente(self, chat_id: Any, texto: str, botoes: Optional[Dict[str, Any]] = None) -> bool:
        """O aviso de um residente (terminou, parou, quer aprovação). Os botões vão
        numa mensagem curta à parte: o texto longo pode virar vários pedaços."""
        token = self._current_token or getattr(self.settings, "TELEGRAM_TOKEN", None)
        if not token:
            return False
        try:
            async with httpx.AsyncClient() as client:
                await tg_send_text(client, token, chat_id, texto)
                if botoes:
                    await tg_post(client, token, "sendMessage", json={
                        "chat_id": chat_id, "text": "Posso?", "reply_markup": botoes})
            return True
        except Exception as exc:
            logger.error("Falha ao avisar o residente no Telegram: %s", exc)
            return False

    async def get_bot_info(self, token: str) -> Optional[Dict[str, Any]]:
        """Busca as informações básicas do bot no Telegram para validar o Token."""
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(url, timeout=5.0)
                if res.status_code == 200:
                    return res.json().get("result")
        except Exception as e:
            logger.error("Erro ao validar token do Telegram: %s", e)
        return None

    def start(self, token: str):
        """Inicia a tarefa de polling em background se já não estiver rodando com o mesmo token."""
        if self.running_task:
            if self._current_token == token:
                logger.info("Bot de Telegram já está rodando com este token.")
                return
            self.stop()

        self._current_token = token
        self._status = "connecting"
        self.running_task = asyncio.create_task(self._loop(token))

    def stop(self):
        """Cancela a execução da tarefa em background do bot."""
        if self.running_task:
            self.running_task.cancel()
            self.running_task = None
        self._status = "offline"
        self._current_token = None
        logger.info("Bot de Telegram parado com sucesso.")

    async def _loop(self, token: str):
        info = await self.get_bot_info(token)
        if not info:
            logger.error("Telegram Bot Token inválido ou rede indisponível. Encerrando bot.")
            self._status = "offline"
            self._current_token = None
            return

        bot_username = info.get("username", "SenturyBot")
        logger.info("Telegram Bot @%s ativado com sucesso! Iniciando Long Polling...", bot_username)
        self._status = "online"

        offset = 0
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        espera, avisou_conflito = _ESPERA_INICIAL, False

        async with httpx.AsyncClient() as client:
            await self._set_commands(client, token)  # menu nativo do "/"
            while True:
                try:
                    # Long polling com timeout de 20s
                    params = {"offset": offset, "timeout": 20}
                    response = await client.get(url, params=params, timeout=25.0)

                    if response.status_code != 200:
                        # 409: outro processo já lê este bot, e o Telegram só deixa um.
                        # Repetir a cada 5 s não muda isso; espera mais e avisa uma vez.
                        if response.status_code == 409:
                            if not avisou_conflito:
                                logger.warning(
                                    "Telegram: outro processo está lendo este bot (HTTP 409); só um pode "
                                    "ler por vez. Confira se a HQ ou outra cópia do Sentury usa o mesmo token. "
                                    "Tentando de novo com espera crescente, até %d s.", _ESPERA_MAXIMA)
                                avisou_conflito = True
                        else:
                            logger.warning("Telegram API retornou HTTP %d. Re-tentando em %d s.",
                                           response.status_code, espera)
                        await asyncio.sleep(espera)
                        espera = min(espera * 2, _ESPERA_MAXIMA)
                        continue
                    if avisou_conflito:
                        logger.info("Telegram: a leitura do bot voltou.")
                    espera, avisou_conflito = _ESPERA_INICIAL, False

                    updates = response.json().get("result", [])
                    for update in updates:
                        offset = update["update_id"] + 1
                        message = update.get("message")
                        if message and any(chave in message for chave in ("text", "photo", "document")):
                            await self._handle_message(token, client, message)
                        elif update.get("callback_query"):
                            await self._handle_botao(token, client, update["callback_query"])

                except asyncio.CancelledError:
                    logger.info("Tarefa de Long Polling do Telegram cancelada.")
                    break
                except Exception as e:
                    logger.error("Erro na leitura de updates do Telegram: %s. Tentando novamente em 5s...", e)
                    await asyncio.sleep(5)

    def _autorizado(self, chat_id: Any, from_id: Any) -> bool:
        allowed_ids = self.settings.telegram_allowed_id_list
        return not allowed_ids or chat_id in allowed_ids or from_id in allowed_ids

    async def _perguntar_permissao(self, client: httpx.AsyncClient, token: str, chat_id: Any,
                                   session_id: str, permissao: Dict[str, Any]) -> None:
        """O cartão de aprovação do painel, como botões na conversa."""
        import uuid

        pedido_id = uuid.uuid4().hex[:10]
        self._pedidos[pedido_id] = {"chat_id": chat_id, "session_id": session_id,
                                    "comando": str(permissao.get("comando") or "")}
        while len(self._pedidos) > _PEDIDOS_GUARDADOS:
            self._pedidos.pop(next(iter(self._pedidos)))
        _gravar_pedidos(self._pedidos)
        texto = f"<b>Precisa da sua autorização</b>\n<code>{_html.escape(self._pedidos[pedido_id]['comando'])}</code>"
        if permissao.get("motivo"):
            texto += f"\n{_html.escape(str(permissao['motivo']))}"
        await tg_post(client, token, "sendMessage", json={
            "chat_id": chat_id, "text": texto, "parse_mode": "HTML",
            "reply_markup": botoes_da_permissao(pedido_id, bool(permissao.get("so_desta_vez"))),
        })

    async def _handle_botao(self, token: str, client: httpx.AsyncClient, toque: Dict[str, Any]) -> None:
        """Um toque num botão de aprovação: registra a resposta como o cartão do
        painel registraria e, se liberou, a tarefa continua."""
        from ..residentes import telegram as _residentes
        from ..tools.permissoes import responder

        mensagem = toque.get("message") or {}
        chat_id = (mensagem.get("chat") or {}).get("id")
        if str(toque.get("data") or "").startswith("sq:"):
            if not self._autorizado(chat_id, (toque.get("from") or {}).get("id")):
                return
            evento = self._perguntas.tocar(toque.get("data"), chat_id)
            if evento is None:
                await tg_post(client, token, "answerCallbackQuery", json={
                    "callback_query_id": toque.get("id"), "text": "Esse pedido não vale mais."})
                return
            chave, texto, aviso = evento
            await tg_post(client, token, "answerCallbackQuery", json={
                "callback_query_id": toque.get("id"), "text": aviso})
            await tg_post(client, token, "editMessageReplyMarkup", json={
                "chat_id": chat_id, "message_id": mensagem.get("message_id"),
                "reply_markup": {"inline_keyboard": []}})
            if texto is not None:
                await self._process_message(token, client, chat_id, texto)
            elif self._perguntas.obter(chave, chat_id)["livre"]:
                await tg_send_text(client, token, chat_id, aviso)
            else:
                await tg_post(client, token, "sendMessage", json=self._perguntas.mensagem(chave, chat_id))
            return
        do_residente = _residentes.ler_botao(toque.get("data"))
        if do_residente is not None:
            await self._handle_botao_do_residente(token, client, toque, chat_id, do_residente)
            return
        lido = ler_botao(toque.get("data"))
        pedido = self._pedidos.get(lido[0]) if lido else None
        if not self._autorizado(chat_id, (toque.get("from") or {}).get("id")) or pedido is None \
                or pedido["chat_id"] != chat_id:
            await tg_post(client, token, "answerCallbackQuery", json={
                "callback_query_id": toque.get("id"), "text": "Esse pedido não vale mais."})
            return
        self._pedidos.pop(lido[0], None)
        _gravar_pedidos(self._pedidos)
        resposta = lido[1]
        responder(pedido["comando"], resposta, pedido["session_id"])
        if self.depois_da_permissao is not None:
            self.depois_da_permissao(pedido["session_id"], resposta)
        rotulo = next(r for _, valor, r in _BOTOES_DA_PERMISSAO if valor == resposta)
        await tg_post(client, token, "answerCallbackQuery", json={"callback_query_id": toque.get("id"), "text": rotulo})
        # Os botões saem da mensagem, para o mesmo pedido não ser respondido duas vezes.
        await tg_post(client, token, "editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": mensagem.get("message_id"), "reply_markup": {"inline_keyboard": []}})
        if resposta == "negar":
            await tg_send_text(client, token, chat_id, f"Não rodei `{pedido['comando']}`.")
            return
        await tg_send_text(client, token, chat_id, f"{rotulo}. Continuando…")
        await self._process_message(token, client, chat_id, f"Autorizado. Pode rodar `{pedido['comando']}`.")

    async def _handle_botao_do_residente(self, token: str, client: httpx.AsyncClient, toque: Dict[str, Any],
                                         chat_id: Any, lido: Tuple[str, str, str]) -> None:
        from ..residentes import telegram as _residentes

        tarefa_id, resposta, rotulo = lido
        mensagem = toque.get("message") or {}
        if not self._autorizado(chat_id, (toque.get("from") or {}).get("id")):
            await tg_post(client, token, "answerCallbackQuery", json={
                "callback_query_id": toque.get("id"), "text": "Esse pedido não vale mais."})
            return
        try:
            await _residentes.responder_botao(tarefa_id, resposta)
        except Exception as exc:
            await tg_post(client, token, "answerCallbackQuery", json={
                "callback_query_id": toque.get("id"), "text": f"Não deu: {exc}"[:180]})
            return
        await tg_post(client, token, "answerCallbackQuery", json={"callback_query_id": toque.get("id"), "text": rotulo})
        await tg_post(client, token, "editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": mensagem.get("message_id"), "reply_markup": {"inline_keyboard": []}})
        await tg_send_text(client, token, chat_id,
                           "Negado. A tarefa foi cancelada." if resposta == "negar" else "Autorizado. Ele continua daqui.")

    async def _handle_message(self, token: str, client: httpx.AsyncClient, message: Dict[str, Any]):
        """Entrada do polling: valida a whitelist e ENFILEIRA a mensagem (não
        processa na hora). Mensagens rápidas do mesmo chat são coalescidas."""
        chat_id = message["chat"]["id"]
        # Foto e documento trazem o texto na legenda.
        text = (message.get("text") or message.get("caption") or "").strip()
        from_id = message.get("from", {}).get("id")

        allowed_ids = self.settings.telegram_allowed_id_list
        if allowed_ids and chat_id not in allowed_ids and from_id not in allowed_ids:
            logger.warning("Mensagem ignorada do chat_id=%s, de=%s (fora da whitelist).", chat_id, from_id)
            await tg_post(client, token, "sendMessage", json={
                "chat_id": chat_id,
                "text": "Olá! Este assistente Sentury está no modo restrito de segurança. Seu ID não está autorizado. Fale com o administrador.",
            })
            return

        if message.get("photo") or message.get("document"):
            anexo, aviso = await self._baixar_anexo(client, token, message)
            if anexo is not None:
                self._anexos.setdefault(chat_id, []).append(anexo)
            else:
                await tg_send_text(client, token, chat_id, aviso)

        # Agrupa balões enviados em sequência para formar um único turno.
        self._buffers.setdefault(chat_id, []).append(text)
        antiga = self._buffer_tasks.get(chat_id)
        if antiga and not antiga.done():
            antiga.cancel()
        self._buffer_tasks[chat_id] = asyncio.create_task(self._flush_buffer(token, client, chat_id))

    async def _flush_buffer(self, token: str, client: httpx.AsyncClient, chat_id: Any) -> None:
        """Espera a janela de coalescência; se nenhuma msg nova chegou, processa
        o buffer junto. Cada msg nova cancela e reinicia este timer."""
        try:
            await asyncio.sleep(_COALESCE_WINDOW)
        except asyncio.CancelledError:
            return
        textos = self._buffers.pop(chat_id, [])
        anexos = self._anexos.pop(chat_id, [])
        self._buffer_tasks.pop(chat_id, None)
        texto = "\n".join(t for t in textos if t).strip()
        if not texto and not anexos:
            return
        try:
            await self._process_message(token, client, chat_id, texto, anexos)
        except Exception as e:
            logger.error("Falha ao processar mensagens coalescidas (chat %s): %s", chat_id, e)

    async def _process_message(self, token: str, client: httpx.AsyncClient, chat_id: Any, text: str,
                               anexos: Optional[List[Dict[str, str]]] = None):
        session_id = f"telegram_{chat_id}"
        user_id = f"telegram_user_{chat_id}"
        if anexos:
            # Com anexo, o pedido vai direto a um turno: a orientação de um turno em
            # curso, a menção e a Mesa levam só texto, e o arquivo se perderia ali.
            # A trava da sessão põe este turno depois do que estiver rodando.
            await self._rodar_ou_avisar(token, client, chat_id, session_id, user_id, text, anexos)
            return

        # Comandos nativos do Telegram: /start, /help, /reset e /parar respondem
        # direto; /alerta e /cron sao os mesmos do painel; os atalhos do setor
        # viram uma pergunta e seguem pro agente normalmente.
        cmd = text.split()[0].lower().split("@", 1)[0] if text.startswith("/") else ""
        if cmd == "/start":
            await self._tg_start(client, token, chat_id)
            return
        if cmd == "/help":
            await tg_send_text(client, token, chat_id, _tg_ajuda())
            return
        if cmd == "/reset":
            self._perguntas.cancelar(chat_id)
            await self.session_store.delete(session_id)
            await tg_send_text(client, token, chat_id, "Conversa reiniciada. Manda sua pergunta quando quiser.")
            return
        if cmd == "/parar":
            self._perguntas.cancelar(chat_id)
            havia = turno_em_curso.pedir_parada(session_id)["havia"]
            await tg_send_text(client, token, chat_id, "Parando…" if havia else "Não tem nada rodando agora.")
            return
        comando = self.comandos.get(cmd)
        if comando is not None:
            await tg_send_text(client, token, chat_id, comando(session_id, user_id, text, chat_id=chat_id))
            return
        if not cmd:
            livre = self._perguntas.texto_livre(chat_id, text)
            if livre:
                chave, texto, aviso = livre
                if texto is not None:
                    text = texto
                else:
                    await tg_send_text(client, token, chat_id, aviso)
                    mensagem = self._perguntas.mensagem(chave, chat_id)
                    if mensagem and not self._perguntas.obter(chave, chat_id)["livre"]:
                        await tg_post(client, token, "sendMessage", json=mensagem)
                    return
        pergunta = _pergunta_do_atalho(cmd) if cmd else None
        if pergunta:
            text = pergunta

        from ..residentes import telegram as _residentes

        assunto = _residentes.ler_assunto(text) if cmd == "/mesa" else None
        if assunto is not None:
            try:
                resposta = await _residentes.abrir_na_mesa(chat_id, *assunto)
            except Exception as exc:
                logger.warning("Abrir assunto na Mesa falhou no Telegram: %s", exc)
                resposta = f"Não consegui abrir na Mesa: {exc}"
            await tg_send_text(client, token, chat_id, resposta)
            return

        mencao = _residentes.ler_mencao(text)
        if mencao is not None:
            try:
                resposta = await _residentes.encaminhar(chat_id, *mencao)
            except Exception as exc:
                logger.warning("Menção a residente falhou no Telegram: %s", exc)
                resposta = f"Não consegui falar com {mencao[0]}: a HQ não respondeu."
            if resposta is not None:
                await tg_send_text(client, token, chat_id, resposta)
                return

        # Com um turno rodando, a mensagem orienta esse turno, como o Enter no
        # painel (harness/caixa_do_turno.py). Sem isso, abria um segundo turno
        # na mesma sessao e o ultimo a salvar apagava o outro.
        if caixa_do_turno.receber(session_id, text) is not None:
            await tg_send_text(client, token, chat_id, "Anotado: entra no próximo passo.")
            return

        await self._rodar_ou_avisar(token, client, chat_id, session_id, user_id, text)

    async def _rodar_ou_avisar(self, token: str, client: httpx.AsyncClient, chat_id: Any, session_id: str,
                               user_id: str, text: str, anexos: Optional[List[Dict[str, str]]] = None) -> None:
        try:
            await self._rodar_turno(token, client, chat_id, session_id, user_id, text, anexos)
        except Exception as e:
            logger.error("Falha ao processar comando para Telegram chat_id=%s: %s", chat_id, e)
            await tg_post(token=token, client=client, method="sendMessage", json={
                "chat_id": chat_id,
                "text": "Ocorreu um erro no processamento da sua solicitação. Pode tentar novamente?"
            })

    async def _rodar_turno(self, token: str, client: httpx.AsyncClient, chat_id: Any,
                           session_id: str, user_id: str, text: str,
                           anexos: Optional[List[Dict[str, str]]] = None) -> None:
        """Um turno do agente, com a mesma trava, o mesmo Parar e a mesma caixa
        de orientacoes do painel."""
        atrasadas: List[Any] = []
        # "digitando…" enquanto processa (re-armado em loop, senão expira em ~5s).
        typing_task = asyncio.create_task(self._keep_typing(client, token, chat_id))
        try:
            async with trava_da_sessao.da(session_id):
                raw_state = await self.session_store.get(session_id)
                state = (
                    AnalysisState.from_dict(raw_state) if raw_state else AnalysisState.new(session_id, user_id)
                )
                state.user_id = user_id
                if anexos:
                    text = _com_anexos(state, session_id, text, anexos)
                tarefa = asyncio.create_task(self.orchestrator.handle_message(state, text))
                turno_em_curso.registrar(session_id, tarefa)
                try:
                    result = await tarefa
                except asyncio.CancelledError:
                    if not (tarefa.cancelled() and turno_em_curso.foi_parado(tarefa)):
                        raise
                    result = {"message": "Parei. Manda o próximo passo quando quiser."}
                finally:
                    turno_em_curso.esquecer(session_id, tarefa)
                    atrasadas = caixa_do_turno.encerrar(session_id)
                state.trim_history()
                await self.session_store.set(session_id, state.to_dict(), self.settings.SESSION_TTL_SEC)
        finally:
            typing_task.cancel()

        # Resposta ADAPTADA (HTML + chunk < 4096 + retry/flood control).
        reply_text = result.get("message") or "Não consegui obter uma resposta para este pedido."
        await tg_send_text(client, token, chat_id, reply_text)
        await self._enviar_anexo(client, token, chat_id, result.get("attachment"))
        clarification = result.get("clarification")
        if isinstance(clarification, dict) and clarification.get("questions"):
            chave = self._perguntas.abrir(chat_id, session_id, clarification)
            await tg_post(client, token, "sendMessage", json=self._perguntas.mensagem(chave, chat_id))
        permissao = result.get("permissao")
        if isinstance(permissao, dict) and permissao.get("comando"):
            await self._perguntar_permissao(client, token, chat_id, session_id, permissao)

        # O que chegou tarde demais para este turno vira o próximo.
        if atrasadas:
            await self._rodar_turno(token, client, chat_id, session_id, user_id,
                                    "\n".join(o.texto for o in atrasadas))

    async def _baixar_anexo(self, client: httpx.AsyncClient, token: str,
                            message: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], str]:
        """A foto ou o documento da mensagem no formato do anexo do painel, ou o aviso
        para a pessoa de por que ele não chegou."""
        if message.get("photo"):
            # A foto chega em vários tamanhos, do menor ao maior.
            item = message["photo"][-1]
            nome, mime = f"foto_{message.get('message_id', '')}.jpg", "image/jpeg"
        else:
            item = message.get("document") or {}
            nome = str(item.get("file_name") or "documento")
            mime = str(item.get("mime_type") or "application/octet-stream")
        grande = f"{nome} passa de 8 MB e não chegou ao Sentury. Mande um arquivo menor."
        if int(item.get("file_size") or 0) > _TETO_DO_ANEXO:
            return None, grande
        try:
            resposta = await tg_post(client, token, "getFile", json={"file_id": item.get("file_id")})
            caminho = (resposta.json().get("result") or {}).get("file_path") if resposta is not None else None
            if not caminho:
                raise ValueError("o Telegram não devolveu o caminho do arquivo")
            baixado = await client.get(f"https://api.telegram.org/file/bot{token}/{caminho}", timeout=60.0)
            baixado.raise_for_status()
            conteudo = baixado.content
        except Exception as exc:
            logger.warning("Não consegui baixar o anexo do Telegram: %s", exc)
            return None, f"Não consegui baixar {nome} do Telegram. Pode mandar de novo?"
        if len(conteudo) > _TETO_DO_ANEXO:
            return None, grande
        if not conteudo:
            return None, f"{nome} chegou vazio. Pode mandar de novo?"
        return {"nome": nome, "data_url": f"data:{mime};base64,{base64.b64encode(conteudo).decode('ascii')}"}, ""

    async def _enviar_anexo(self, client: httpx.AsyncClient, token: str, chat_id: Any, attachment: Any) -> None:
        """PDFs, tabelas geradas ou gráficos que vieram com a resposta."""
        if attachment and isinstance(attachment, dict):
            att_type = attachment.get("type")
            filename = attachment.get("filename", "documento")
            content_base64 = attachment.get("content_base64")
            content_text = attachment.get("content")

            file_bytes = None
            if content_base64:
                file_bytes = base64.b64decode(content_base64)
            elif content_text:
                file_bytes = content_text.encode("utf-8")

            if file_bytes:
                data = {"chat_id": chat_id}
                # Se for imagem ou tiver extensão de imagem
                if att_type in ("image/png", "image/jpeg", "image") or filename.lower().endswith((".png", ".jpg", ".jpeg")):
                    files = {"photo": (filename, BytesIO(file_bytes))}
                    await tg_post(client, token, "sendPhoto", data=data, files=files)
                else:
                    files = {"document": (filename, BytesIO(file_bytes))}
                    await tg_post(client, token, "sendDocument", data=data, files=files)
