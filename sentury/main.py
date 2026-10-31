import json
import logging
import pathlib
import os
import sys as _sys
import time as _time
from pathlib import Path
from typing import Any, Optional, List, Dict

# No Windows, stdout/stderr podem usar cp1252 e falhar ao registrar caracteres
# do modelo. UTF-8 evita que uma linha de log interrompa a requisição.
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from fastapi import Body, Depends, FastAPI, Header, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings
from .data.store import get_store
from .harness.orchestrator import SenturyOrchestrator
from .harness import executor_de_goal, trava_da_sessao
from .harness.state import AnalysisState, is_transient_failure_message
from .llm.effort import (
    active_effort, clear_effort, normalize as normalize_effort,
    provider_effort_for,
)
from .llm.auxiliar import MotorAuxiliar
from robinbandit.sentury import (
    ChainProvider,
    use_ultra_provider,
    clear_ultra_provider,
    use_ultra_classify_provider,
    clear_ultra_classify_provider,
    no_ultra,
)
from robinbandit import RobinConfig, RobinGateway
from robinbandit.credentials import KeyRotator, is_quota_error, parse_keys
from robinbandit.providers import (
    build_provider,
    build_provider_set,
    build_tier_provider,
    describe_from_config,
)
from .knowledge.retriever import get_knowledge_base
from .memory.session_store import get_session_store
from .memory.session_index import (
    SessionIndex,
    clean_ai_title,
    first_assistant_message,
    first_user_message,
    user_message_count,
)
from .memory.skill_store import get_skill_store
from .memory.user_memory import get_user_memory_store
from .validators.input_guard import validate_message
from .context.engine import (
    ContextDocumentError,
    ContextDocumentValidationError,
    ContextRevisionConflict,
    UnknownContextDocument,
)

# Módulos de Skills e Curator
from .skills.curator import SkillCurator
from .external import mcp_registry
from .external.channels import catalogo as channel_catalog, declaracao as channel_declaration
from .external.telegram_gateway import TelegramBotManager
from .external.cron_scheduler import CronScheduler, parse_cron_command, parse_alert_command

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
from .exec.logs import instalar_redacao

instalar_redacao()
# URLs de APIs podem conter credenciais (por exemplo, tokens de bots no path).
# Os providers do Sentury ja registram sucesso/erro sem expor o destino completo.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.APP_NAME, version=settings.APP_VERSION,
    docs_url="/docs" if settings.SENTURY_DOCS else None,
    redoc_url="/redoc" if settings.SENTURY_DOCS else None,
    openapi_url="/openapi.json" if settings.SENTURY_DOCS else None,
)
# A API da HQ dos agentes residentes. Sem SENTURY_HQ_TOKEN ela responde 503.
from .residentes.api import montar as _montar_hq  # noqa: E402

_montar_hq(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

session_store = get_session_store(settings)
data_store = get_store(settings)
_gemini_live_keys = KeyRotator(parse_keys(settings.GEMINI_API_KEY))


def _gemini_key_pool() -> str:
    from robinbandit import secrets
    return secrets.ler("GEMINI_API_KEY") or str(settings.GEMINI_API_KEY or "")


def get_gemini_live_api_key() -> Optional[str]:
    """Gemini Live recebe uma unica chave; GEMINI_API_KEY pode vir como pool CSV."""
    raw = _gemini_key_pool()
    for candidate in str(raw).split(","):
        key = candidate.strip()
        if key:
            return key
    return None


def get_gemini_live_api_keys() -> List[str]:
    """Ordem round-robin de chaves para a Gemini Live.

    O endpoint de voz ainda usa uma chave por conexao, mas agora tenta as
    chaves do pool em ordem rotativa quando houver falha de cota/autenticacao.
    """
    global _gemini_live_keys
    parsed = parse_keys(_gemini_key_pool())
    current_keys = list(getattr(_gemini_live_keys, "keys", []) or [])
    if parsed != current_keys:
        _gemini_live_keys = KeyRotator(parsed)
    return _gemini_live_keys.order()


def _is_live_key_retryable(exc: Exception) -> bool:
    if is_quota_error(exc):
        return True
    lowered = str(exc).lower()
    return any(token in lowered for token in ("api key not valid", "invalid api key", "permission denied"))

# O catálogo executável pertence ao RobinBandit. O Sentury fornece apenas suas
# Settings como fonte opcional dos valores já carregados do `.env`.
_robin_config_path = Path(settings.SENTURY_ROBINBANDIT_CONFIG)
if not _robin_config_path.is_absolute():
    _robin_config_path = Path(__file__).resolve().parents[1] / _robin_config_path
_robin_config = RobinConfig.from_yaml(_robin_config_path)
_provider_set = build_provider_set(_robin_config, settings)
_groq = _provider_set.get("groq")
_groq_planner = build_provider(
    _robin_config, "groq", settings,
    model_role="planner", name="groq",
)
_fallback = _provider_set["fallback"]

def _tier_provider_for(mode: str):
    """Resolve a conta do modo no Robin a cada request.

    A resolução dinâmica faz uma troca no painel valer imediatamente. Se a
    conta estiver indisponível, o próprio Robin devolve um alvo que falha:
    Reforçado então cai no Router; Dedicado termina sem fallback.
    """
    return build_tier_provider(_robin_config, mode, settings) if mode in {
        "ultra", "ultra_max"
    } else None


def _effort_da_barra(payload) -> Optional[str]:
    """Só a escolha MANUAL da barra. O Auto (e o skip do caso trivial) são
    resolvidos dentro do handle_message, pra valer também no Telegram, no cron
    e na eval — quando isso morava aqui, cada porta de entrada se comportava
    de um jeito."""
    return normalize_effort(payload.effort)

# Perfis de tarefa: ativa o mapa do .env (SENTURY_*_MODELS) no roteador.
# Vazio → DEFAULT_PROFILE_MODELS. É o que faz o override por .env valer de verdade.
from robinbandit.profiles import set_active_profiles, resolve_profile_models
set_active_profiles(resolve_profile_models(settings, _robin_config.profiles))

# O RobinBandit é o único dono do roteamento de provedores.
robin = RobinGateway(_robin_config)
from robinbandit.state.atividade import Atividade

_atividade_rb = Atividade(persistir=True)

def _chain_for(primary):
    """Monta a cadeia na ordem declarada pelo YAML RobinBandit."""
    by_key = dict(_provider_set)
    by_key["groq"] = primary
    ordered = [by_key.get(k) for k in _robin_config.chain_order]
    return ChainProvider(
        [p for p in ordered if p is not None],
        router=robin,
        active_effort=active_effort,
        provider_effort_for=provider_effort_for,
        activity=_atividade_rb,
    )

planner_llm = _chain_for(_groq_planner)
responder_llm = _chain_for(_groq)
auxiliar_llm = MotorAuxiliar(_robin_config, settings, atual=responder_llm)
from .tools import web as _web

_web.registrar_auxiliar(auxiliar_llm)
# O print do computer use descrito por quem enxerga quando o da frente não enxerga.
from .harness.visao_auxiliar import registrar as _registrar_visao_auxiliar

_registrar_visao_auxiliar(responder_llm)
# A API headless do RobinBandit e o chat compartilham a lista de provedores.
# Alterar a cadeia pela API passa a valer no responder sem reiniciar o Sentury.
_robin_api_providers = responder_llm.providers


def _refresh_provider_chains() -> None:
    """Reconstrói os adaptadores após mudança de chave, sem reiniciar o app."""
    global _provider_set, _groq, _groq_planner, _fallback
    _provider_set = build_provider_set(_robin_config, settings)
    _groq = _provider_set.get("groq")
    _groq_planner = build_provider(
        _robin_config, "groq", settings, model_role="planner", name="groq"
    )
    _fallback = _provider_set["fallback"]

    def ordered(primary):
        by_key = dict(_provider_set)
        by_key["groq"] = primary
        return [
            by_key[key] for key in _robin_config.chain_order
            if by_key.get(key) is not None
        ]

    planner_llm.providers[:] = ordered(_groq_planner)
    responder_llm.providers[:] = ordered(_groq)
    auxiliar_llm.invalidar()

knowledge_base = get_knowledge_base(settings)
user_memory = get_user_memory_store(session_store)
skill_store = get_skill_store(session_store)

from .harness.context_budget import ContextBudgetManager, Contextualizer
from .harness import caixa_do_turno, registro_do_turno, transmissao, turno_em_curso
from .harness.council import SenturyCouncil
from .memory.experience_library import ExperienceLibrary

ctx_budget = ContextBudgetManager(Contextualizer(auxiliar_llm))
exp_lib = ExperienceLibrary(session_store)
council = SenturyCouncil(planner_llm)

orchestrator = SenturyOrchestrator(
    planner=planner_llm,
    responder=responder_llm,
    store=data_store,
    knowledge=knowledge_base,
    memory=user_memory,
    skills=skill_store,
    context_budget_manager=ctx_budget,
    experience_library=exp_lib,
    council=council,
    provider_router_backend=robin,
)

curator = SkillCurator(orchestrator.user_skills_dir, orchestrator.skill_usage_tracker)

telegram_manager = TelegramBotManager(orchestrator, session_store, settings)
cron_scheduler = CronScheduler(orchestrator, session_store, settings, telegram_manager)
# As ferramentas de agendamento vivem noutro modulo e nao conhecem o main:
# o agendador se registra para elas alcancarem esta instancia.
from .external import agendador as _agendador
_agendador.registrar(cron_scheduler)
session_index = SessionIndex(
    session_store,
    ttl=settings.SENTURY_SESSION_ARCHIVE_TTL,
    max_items=settings.SENTURY_SESSION_MAX_INDEX,
)
cron_scheduler.session_index = session_index
# O agente precisa do indice pra `buscar_conversas` (memoria episodica).
orchestrator.session_index = session_index

_ROBIN_STATE_KEY = "__provider_router_state__"
_router_saver_task = None

def _attach_result_to_last_assistant(state: AnalysisState, result: Dict[str, Any]) -> None:
    # Processo Analitico: o stream mostra ao vivo e some ao recarregar. Guardar
    # os passos na propria mensagem faz o painel voltar igual depois do reload.
    processo = getattr(state, "processo_do_turno", None)
    if processo:
        for message in reversed(state.history):
            if message.get("role") == "assistant":
                message["processo"] = [dict(passo) for passo in processo]
                break
        state.processo_do_turno = None
    # O cartao do navegador tambem: sem isto ele sumia ao recarregar.
    from .harness.cartao_do_navegador import para_guardar

    cartao = para_guardar(getattr(state, "navegador_do_turno", None))
    state.navegador_do_turno = None
    if cartao:
        for message in reversed(state.history):
            if message.get("role") == "assistant":
                message["navegador"] = cartao
                break

    from .harness.cartao_do_computador import para_guardar as _guardar_computador

    cartao_computador = _guardar_computador(getattr(state, "computador_do_turno", None))
    state.computador_do_turno = None
    if cartao_computador:
        for message in reversed(state.history):
            if message.get("role") == "assistant":
                message["computador"] = cartao_computador
                break

    # Cada anexo vira artefato: o payload nao pode viver no historico, e sem
    # isto so o ultimo arquivo do turno sobreviveria ao recarregar a pagina.
    varios = [
        guardado
        for bruto in (result.get("attachments") or [])
        for guardado in [state.store_artifact(bruto)]
        if guardado
    ]
    attachment = state.store_artifact(result.get("attachment"))
    if varios:
        for message in reversed(state.history):
            if message.get("role") == "assistant":
                message["attachments"] = varios
                break
    if not attachment:
        return
    validation = None
    harness = result.get("harness")
    if isinstance(harness, dict):
        validation = harness.get("artifact_validation")
    for message in reversed(state.history):
        if message.get("role") == "assistant":
            message["attachment"] = attachment
            if validation:
                message["attachment_validation"] = validation
            return


async def _load_state(session_id: str, user_id: str):
    raw_state = await session_store.get(session_id)
    if isinstance(raw_state, dict):
        owner = raw_state.get("user_id")
        if owner and user_id and owner != user_id:
            raw_state = None
    if not raw_state or (isinstance(raw_state, dict) and raw_state.get("recovered")):
        archived = await session_index.load(user_id, session_id)
        if archived:
            raw_state = archived
    state = AnalysisState.from_dict(raw_state) if raw_state else AnalysisState.new(session_id, user_id)
    state.session_id = session_id
    state.user_id = user_id
    state.prune_transient_failures()
    return raw_state, state


def _prepare_regeneration(state: AnalysisState, user_message: str) -> None:
    state.prune_transient_failures()
    state.remove_latest_user_turn(user_message)


async def _persist_state(state: AnalysisState) -> Dict[str, Any]:
    state.trim_history()
    persisted_state = state.to_persisted_dict()
    await session_store.set(state.session_id, persisted_state, settings.SESSION_TTL_SEC)
    archived_state = AnalysisState.from_dict(persisted_state)
    await session_index.remember(archived_state)
    return state.to_dict()


def _should_autotitle(state: AnalysisState) -> bool:
    return bool(settings.SENTURY_SESSION_AI_TITLES and user_message_count(state.history) == 1)


async def _auto_title_session(session_id: str, user_id: str, user_text: str, assistant_text: str,
                              tier: Any = None) -> None:
    # Roda depois da resposta, quando o modo do turno já foi desligado: sem
    # religá-lo, o título cairia no roteamento automático, que pode nem existir.
    token = use_ultra_provider(tier) if tier is not None else None
    try:
        meta = await session_index.get_meta(user_id, session_id)
        if meta and meta.get("title_source") in ("manual", "ai"):
            return
        raw = await session_index.load(user_id, session_id)
        if not raw:
            return
        state = AnalysisState.from_dict(raw)
        if user_message_count(state.history) != 1:
            return
        messages = [
            {
                "role": "system",
                "content": (
                    "Crie um titulo curto em portugues para esta conversa. "
                    "Use 3 a 7 palavras, sem aspas, sem ponto final, sem prefixo."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Mensagem do usuario:\n{user_text[:900]}\n\n"
                    f"Primeira resposta da assistente:\n{assistant_text[:900]}"
                ),
            },
        ]
        if token is None:
            with no_ultra():
                raw_title = await auxiliar_llm.complete(messages, temperature=0.0, complexity="simple")
        else:
            raw_title = await auxiliar_llm.complete(messages, temperature=0.0, complexity="simple")
        title = clean_ai_title(raw_title)
        if title:
            await session_index.remember(state, title=title, title_source="ai")
    except Exception as exc:
        logger.warning("Titulo automatico da sessao falhou: %s", exc)
    finally:
        if token is not None:
            clear_ultra_provider(token)


def _schedule_autotitle(background_tasks: BackgroundTasks, state: AnalysisState, tier: Any = None) -> None:
    if not _should_autotitle(state):
        return
    user_text = first_user_message(state.history)
    assistant_text = first_assistant_message(state.history)
    if user_text and assistant_text:
        background_tasks.add_task(_auto_title_session, state.session_id, state.user_id, user_text,
                                  assistant_text, tier)


async def _persist_router_loop():
    """Salva o estado aprendido do roteador (bandit/latência) a cada 120s, no
    store de sessão local. Não chama LLM, então não gasta cota."""
    import asyncio as _asyncio
    while True:
        await _asyncio.sleep(120)
        # Onde o aprendizado mora é assunto do RobinBandit; aqui só pedimos
        # que ele guarde.
        try:
            robin.gravar_aprendizado()
        except Exception as exc:
            logger.warning("Falha ao gravar o aprendizado do robin: %s", exc)
        try:
            await session_store.set(_ROBIN_STATE_KEY, robin.dump(), hot_ttl=604800, warm_ttl=2592000)
        except Exception as exc:
            logger.warning("Falha ao persistir o robin: %s", exc)


@app.on_event("startup")
async def startup_event():
    if settings.SENTURY_PY_CHILD:
        from .exec.provider_python import iniciar_pool

        await iniciar_pool()
    if settings.TELEGRAM_TOKEN and settings.TELEGRAM_BOT_ACTIVE:
        telegram_manager.start(settings.TELEGRAM_TOKEN)
    # Recarrega os agendamentos (cron) que sobreviveram ao restart.
    await cron_scheduler.load_persisted()
    # Turno que o servidor derrubou ao cair: a conversa oferece Continuar.
    registro_do_turno.recuperar_no_inicio()
    # O navegador entra quando o Playwright esta instalado; sem ele a
    # ferramenta responde "nenhum provedor" em vez de quebrar a subida.
    try:
        from .tools import browser_registry
        from .tools.browser_chrome_provider import ChromeTabProvider
        from .tools.browser_playwright_provider import PlaywrightBrowserProvider

        browser_registry.registrar(ChromeTabProvider())
        _navegador = PlaywrightBrowserProvider()
        if _navegador.is_available():
            browser_registry.registrar(_navegador)
    except Exception as exc:
        logger.warning("Navegador indisponivel: %s", exc)
    # Recarrega o que o roteador já aprendeu (qual provedor rende melhor).
    try:
        saved = None
        try:
            saved = await session_store.get(_ROBIN_STATE_KEY)
        except Exception as exc:
            logger.warning("Aprendizado do robin indisponível no store (%s).", exc)
        if saved:
            robin.load(saved)
        else:
            robin.recuperar_aprendizado()
    except Exception as exc:
        logger.warning("Falha ao recarregar o robin: %s", exc)
    import asyncio as _asyncio
    global _router_saver_task, _navegador_ocioso_task
    _router_saver_task = _asyncio.create_task(_persist_router_loop())
    _navegador_ocioso_task = _asyncio.create_task(_fechar_navegador_ocioso_loop())
    # O goal que estava ativo quando o servidor caiu continua de onde parou.
    executor_de_goal.configurar(_rodar_turno_do_goal)
    executor_de_goal.rearmar()
    # Agentes residentes: o que caiu no meio volta para a fila e quem tem fila acorda.
    from .residentes import worker as _residentes

    _residentes.configurar(_rodar_turno_do_residente)
    _residentes.observar(_resposta_do_residente_na_conversa)
    _residentes.observar(_aviso_do_residente_no_telegram)
    from .residentes import hq as _hq_residentes  # noqa: F401  (liga a Mesa ao fim das tarefas)
    from .residentes import mesa as _mesa

    _mesa.configurar(_decidir_entrada_na_mesa)
    _mesa.ao_fechar(_resumo_da_mesa_no_telegram)
    _mesa.ao_fechar(_resumo_da_mesa_na_conversa)
    _residentes.rearmar()


_navegador_ocioso_task = None


async def _fechar_navegador_ocioso_loop():
    """Chromium de conversa parada fecha sozinho (SENTURY_BROWSER_OCIOSO_MIN)."""
    import asyncio as _asyncio
    from .tools import browser_registry

    while True:
        await _asyncio.sleep(60)
        try:
            browser_registry.fechar_ociosos()
        except Exception:
            logger.warning("Falha ao fechar navegador ocioso.", exc_info=True)

@app.on_event("shutdown")
async def shutdown_event():
    if settings.SENTURY_PY_CHILD:
        from .exec.provider_python import encerrar_pool

        await encerrar_pool()
    from asyncio import to_thread

    telegram_manager.stop()
    await to_thread(_robinbandit_api.state.logins.fechar)
    await cron_scheduler.shutdown()
    if _router_saver_task:
        _router_saver_task.cancel()
    if _navegador_ocioso_task:
        _navegador_ocioso_task.cancel()
    # O goal continua ativo em disco: o proximo startup rearma.
    await executor_de_goal.parar_todos()
    from .residentes import worker as _residentes

    await _residentes.parar_todos()
    from .residentes.rede_da_caixa import encerrar_proxies
    await to_thread(encerrar_proxies)
    try:
        from .tools import browser_registry

        browser_registry.encerrar_todos()
    except Exception:
        logger.warning("Falha ao fechar os navegadores na saida.", exc_info=True)
    try:
        from .tools.computador import encerrar_todos as _encerrar_computador

        _encerrar_computador()
    except Exception:
        logger.warning("Falha ao fechar o computer use na saida.", exc_info=True)
    try:
        await session_store.set(_ROBIN_STATE_KEY, robin.dump(), hot_ttl=604800, warm_ttl=2592000)
    except Exception:
        pass


class ImagemAnexada(BaseModel):
    """Imagem recebida como data URL, enviada ao modelo e preservada como artefato."""
    nome: str = Field(default="imagem", max_length=200)
    data_url: str = Field(..., max_length=8_000_000)


from .artifacts.arquivo_anexado import ArquivoAnexado


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    user_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=8000)
    imagens: List[ImagemAnexada] = Field(default_factory=list, max_length=4)
    arquivos: List[ArquivoAnexado] = Field(default_factory=list, max_length=6)
    # Funcoes nativas ligadas pelo badge `@` na interface. Ativacao e estado
    # visivel, nao palavra que o texto precisa conter em todo turno.
    funcoes: List[str] = Field(default_factory=list, max_length=8)
    # Seleção de provedor: Router, Reforçado (id legado ultra) ou Dedicado
    # (id legado ultra_max). `auto` ainda é aceito pelo Robin como alias antigo.
    mode: str = Field(default="router", max_length=16)
    # Barra de esforço: "auto" (o agente calibra) ou um nível fixo do usuário.
    # Não troca o `mode` — só o quanto se raciocina dentro dele.
    effort: str = Field(default="auto", max_length=8)
    regenerate: bool = False


def _anexar_imagens(state, payload) -> None:
    """Guarda as imagens do turno para a proxima mensagem do usuario.

    O texto continua sendo texto no historico; a chain converte para o formato
    multimodal so no payload que sai para o provedor, e o Router entao exige
    `vision` e nao tenta quem nao enxerga.
    """
    from .tools.recebidos import entregar_ao_turno

    imagens = [{"nome": item.nome, "data_url": item.data_url} for item in (getattr(payload, "imagens", None) or [])]
    entregar_ao_turno(state, getattr(payload, "session_id", "") or state.session_id, imagens, [])
    state.funcoes_ativas = [
        str(nome).strip().lower()
        for nome in (getattr(payload, "funcoes", None) or [])
        if str(nome).strip()
    ]


def _preparar_turno(state, payload) -> str:
    """O que o pedido traz alem do texto: imagens, funcoes do `@` e arquivos.

    Os dois endpoints passam por aqui. So o `/chat` aplicava imagens e funcoes,
    e o cliente usa o `/chat/stream`: a imagem anexada e o badge `@` eram
    descartados em silencio.

    Devolve a mensagem do turno. O arquivo e lido aqui, na chegada, e entra no
    historico com fronteira de terceiro; a mensagem leva so os nomes (teto de
    2.000 caracteres). Anexo nao depende de o modelo chamar `ler_arquivo`.
    """
    from .tools.recebidos import entregar_ao_turno, linha_para_a_mensagem

    _anexar_imagens(state, payload)
    arquivos = [a.model_dump() for a in (getattr(payload, "arquivos", None) or [])]
    caminhos = entregar_ao_turno(state, payload.session_id, [], arquivos)
    return payload.message + linha_para_a_mensagem(caminhos)


class OrientarRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    texto: str = Field(..., min_length=1, max_length=4000)
    id_cliente: str = Field("", max_length=80)


class ResetRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)


class SessionTitleRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=100)


class InterfacePrefsRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    pastas: List[Dict[str, Any]] = Field(default_factory=list)
    sessoes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    raiz_recolhida: bool = False


class SkillCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    category: Optional[str] = None
    content: str = Field(..., min_length=1)


class SkillUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1)


class PinRequest(BaseModel):
    pinned: bool


class ContextDocumentUpdateRequest(BaseModel):
    content: str
    expected_revision: Optional[str] = Field(default=None, max_length=128)
    accept_warnings: bool = False


async def verify_api_token(authorization: Optional[str] = Header(None)) -> None:
    if not settings.SENTURY_API_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="token ausente")
    token = authorization[len("Bearer "):].strip()
    # Tempo constante: `!=` para no primeiro caractere diferente, e o tempo da
    # resposta conta quantos acertaram.
    import hmac as _hmac

    if not _hmac.compare_digest(token.encode(), str(settings.SENTURY_API_TOKEN).encode()):
        raise HTTPException(status_code=401, detail="token inválido")


# A tela da HQ: as mesmas operações da API da HQ, pela autenticação do Sentury.
from .residentes.api_local import router as _rotas_dos_residentes  # noqa: E402

app.include_router(_rotas_dos_residentes, dependencies=[Depends(verify_api_token)])
from .residentes.tela_da_caixa import router_local as _tela_local, router_hq as _tela_hq

app.include_router(_tela_local)
app.include_router(_tela_hq)
# A aba do Mutation: propor, medir e decidir cada mutação.
from .mutation.api import router as _rotas_do_mutation  # noqa: E402

app.include_router(_rotas_do_mutation, dependencies=[Depends(verify_api_token)])
# As escolhas da instalação feitas pela tela (embeddings, voz).
from .ajustes_api import escolha_de_voz, router as _rotas_dos_ajustes  # noqa: E402

app.include_router(_rotas_dos_ajustes, dependencies=[Depends(verify_api_token)])


# RobinBandit roda embutido como API, sem expor a interface /painel nem as UIs
# de documentacao. O client do Sentury consome estes contratos e continua sendo
# a unica interface do produto. A dependencia global aplica a mesma protecao
# dos demais endpoints do Sentury a todas as rotas do subaplicativo.
from robinbandit.server import create_app as _create_robinbandit_app

_robinbandit_api = _create_robinbandit_app(
    _robin_api_providers,
    robin.router,
    config=_robin_config,
    include_interface=False,
    dependencies=[Depends(verify_api_token)],
    on_accounts_changed=_refresh_provider_chains,
    activity=_atividade_rb,
)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/sentury/status")
async def status():
    # Cadeia real (ordem de tiers), só os provedores com chave + o demo no fim.
    configured = describe_from_config(_robin_config, settings)
    llm_chain = [p["key"] for p in configured if p["configured"] and p["key"] != "fallback"]
    llm_chain.append("fallback (demo)")
    return {
        "llm_chain": llm_chain,
        "data_store": (getattr(settings, "SENTURY_DATA_BACKEND", "") or "memory"),
        "session_store": getattr(session_store, "backend_name", session_store.__class__.__name__),
        "knowledge_base": knowledge_base.modo if knowledge_base else "desabilitada",
    }


async def get_all_api_keys_info(settings) -> list:
    """Estado de cada credencial, para o painel.

    Quem responde é o RobinBandit: credencial é assunto de provedor, e provedor
    é dele. Aqui havia uma lista com onze nomes de variável escritos à mão —
    declarar um provedor novo no YAML não bastava, era preciso lembrar de vir
    editar isto também, e esquecer significava a chave nova nunca aparecer.

    Os nomes de campo mudam de propósito (`label_type` → `rotulo`): o formato
    é do dono do dado.
    """
    from robinbandit import saldo

    try:
        return await saldo.consultar(_robin_config, settings)
    except Exception as exc:
        logger.warning("Falha ao consultar o estado das credenciais: %s", exc)
        return []


@app.get("/sentury/providers")
async def providers(_: None = Depends(verify_api_token)):
    """Painel multi-provider: cada provedor com tier, se está configurado, seus
    modelos e o ESTADO em runtime vindo do robin — saúde, latência,
    cooldown, cota restante e a qualidade que o bandit já aprendeu. Alimenta o
    modal de disponibilidade no frontend."""
    health = robin.snapshot()
    # Contas declaradas e qual serve cada tier. `para_painel()` nunca
    # devolve o valor da chave: só o NOME da variável e se está preenchida.
    try:
        from robinbandit.accounts import catalogo_efetivo
        from robinbandit import account_config
        contas = catalogo_efetivo(settings, _robin_config).para_painel()
        contas["selecoes"] = {
            modo: account_config.selecao_do_modo(modo)
            for modo in ("reforcado", "dedicado")
        }
        # O painel precisa saber presença, origem e quantidade, não reconhecer
        # o segredo. Nem prefixo nem sufixo atravessam a fronteira HTTP.
        for conta in contas.get("contas", []):
            conta.pop("dica", None)
            conta["chaves"] = [
                {"i": item.get("i")}
                for item in conta.get("chaves", [])
                if isinstance(item, dict) and isinstance(item.get("i"), int)
            ]
    except ValueError as exc:
        contas = {"erro": str(exc), "contas": [], "tiers": {}}
    out = []
    for p in describe_from_config(_robin_config, settings):
        h = health.get(p["key"], {})
        raw = h.get("status", "idle")
        cooldown = h.get("cooldown", 0) or 0
        if not p["configured"]:
            estado = "off"          # sem chave
        elif cooldown > 0:
            estado = "limit"        # em cooldown (429/crédito/erro) — fora da fila por ora
        elif raw == "ok":
            estado = "ok"           # respondeu
        elif raw == "rate_limit":
            estado = "limit"
        elif raw == "error":
            estado = "error"        # falhou (auth/rede/modelo inválido/etc.)
        else:
            estado = "idle"         # configurado, ainda não usado nesta sessão
        out.append({
            **p,
            "estado": estado,
            "last_model": h.get("last_model"),
            "detail": h.get("detail"),
            "seconds_ago": h.get("seconds_ago"),
            "latency_ms": h.get("latency_ms"),
            "cooldown": round(cooldown) if cooldown else 0,
            "rpm_remaining": h.get("rpm_remaining"),
            "rpd_remaining": h.get("rpd_remaining"),
            "quality": h.get("quality_mean"),
            "samples": h.get("samples", 0),
            "ok": h.get("ok", 0),
            "err": h.get("err", 0),
            "rpm_used": h.get("rpm_used", 0),
            # Rede de seguranca do sistema, nao escolha do usuario: sem isso o
            # card aparece na lista como se alguem tivesse configurado.
            "ultimo_recurso": p["key"] == getattr(_robin_config, "last_resort", None),
        })
    # Ordena por tier (1→3), configurados primeiro dentro do tier.
    out.sort(key=lambda x: (x["tier"], not x["configured"]))
    
    # Status do Ultra separado
    ultra_info = None
    if settings.API_KEY_ULTRA:
        uh = health.get("ultra", {})
        raw = uh.get("status", "idle")
        cooldown = uh.get("cooldown", 0) or 0
        estado = "idle"
        if cooldown > 0:
            estado = "limit"
        elif raw == "ok":
            estado = "ok"
        elif raw == "rate_limit":
            estado = "limit"
        elif raw == "error":
            estado = "error"
            
        ultra_info = {
            "key": "ultra",
            "label": "Modo Reforçado",
            "tier": 0,
            "configured": True,
            "models": settings.ultra_model_list or [],
            "kinds": ["text", "midia"],
            "estado": estado,
            "last_model": uh.get("last_model"),
            "detail": uh.get("detail"),
            "seconds_ago": uh.get("seconds_ago"),
            "latency_ms": uh.get("latency_ms"),
            "cooldown": round(cooldown) if cooldown else 0,
            "rpm_remaining": uh.get("rpm_remaining"),
            "rpd_remaining": uh.get("rpd_remaining"),
            "quality": uh.get("quality_mean"),
            "samples": uh.get("samples", 0),
            "ok": uh.get("ok", 0),
            "err": uh.get("err", 0),
            "rpm_used": uh.get("rpm_used", 0)
        }
    
    # Coleta de todas as chaves e saldos
    openrouter_balances = await get_all_api_keys_info(settings)
    
    # Varias chaves num provedor gratuito multiplicam cota; num provedor
    # misto/pago, juntas na mesma variavel, viram sorteio entre paga e gratis.
    from robinbandit.account_health import diagnosticar

    try:
        avisos = diagnosticar(_robin_config, settings, (contas or {}).get("contas") or [])
    except Exception as exc:
        logger.warning("Diagnostico de contas indisponivel: %s", exc)
        avisos = []

    return {
        "router_backend": robin.backend_name,
        "providers": out,
        "ultra_info": ultra_info,
        "openrouter_balances": openrouter_balances,
        "accounts": contas,
        "avisos": avisos,
    }


@app.get("/sentury/tools")
async def tools():
    from .tools.registry import tools_by_category
    return {"tools_por_categoria": tools_by_category()}


@app.get("/sentury/domains")
async def domains():
    """Setores (DomainPack) registrados + o ativo, com o catálogo de métricas.
    Read-only (v1.5): a página só mostra; trocar/subir setor é v2."""
    from .domains import DOMAIN_REGISTRY, get_active_domain

    ativo = get_active_domain()

    def _serialize(pack):
        metricas = []
        for nome in sorted(pack.metric_names):
            meta = pack.metric_meta.get(nome, {})
            metricas.append({
                "nome": nome,
                "label": meta.get("label", nome),
                "unidade": meta.get("unidade", ""),
                "fonte": meta.get("fonte", ""),
                "descricao": meta.get("descricao", ""),
                "maior_melhor": pack.higher_is_better.get(nome),
                "grupo": "experiência" if nome in pack.cx_metrics else "operação",
            })
        return {
            "nome": pack.name,
            "ativo": pack.name == ativo.name,
            "total_metricas": len(pack.metric_names),
            "metricas": metricas,
        }

    from .domains.escolha import GENERALISTA, PACK_GENERALISTA

    lista = [_serialize(PACK_GENERALISTA)] + [_serialize(p) for p in DOMAIN_REGISTRY.values()]
    return {"ativo": ativo.name, "generalista": GENERALISTA, "setores": lista}


class DomainChoiceRequest(BaseModel):
    setor: str = Field("", max_length=64)


@app.put("/sentury/domains/ativo")
async def trocar_setor(payload: DomainChoiceRequest, _: None = Depends(verify_api_token)):
    """Liga um setor, ou o generalista quando vem vazio."""
    from .domains import DOMAIN_REGISTRY
    from .domains.escolha import GENERALISTA, gravar

    alvo = str(payload.setor or "").strip() or GENERALISTA
    if alvo != GENERALISTA and alvo not in DOMAIN_REGISTRY:
        raise HTTPException(status_code=404, detail=f"setor '{alvo}' nao esta registrado")

    gravar(alvo)
    # A persona do sistema e montada uma vez no arranque: sem refazer, a troca
    # so valeria depois de reiniciar.
    try:
        from .llm import prompts

        prompts.SYSTEM_PERSONA = prompts.system_persona_do_dominio()
    except Exception as exc:
        logger.warning("Setor trocado, mas a persona nao recarregou: %s", exc)
    return {"ativo": alvo}


@app.get("/sentury/context-engine")
async def context_engine_status(_: None = Depends(verify_api_token)):
    """Return editable prompt overlays and the protected composition contract."""
    try:
        return orchestrator.prompt_context_engine.status(include_content=True)
    except ContextDocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/sentury/context-engine/reload")
async def context_engine_reload(_: None = Depends(verify_api_token)):
    """Clear the in-memory document cache and read the current files again."""
    try:
        return orchestrator.prompt_context_engine.reload()
    except ContextDocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/sentury/context-engine/{document_key}")
async def context_engine_update(
    document_key: str,
    payload: ContextDocumentUpdateRequest,
    _: None = Depends(verify_api_token),
):
    """Validate and atomically update one allowlisted context document."""
    try:
        document = orchestrator.prompt_context_engine.save_document(
            document_key,
            payload.content,
            expected_revision=payload.expected_revision,
            accept_warnings=payload.accept_warnings,
        )
        return {"ok": True, "document": document}
    except UnknownContextDocument as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ContextRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContextDocumentValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "warnings": exc.warnings},
        ) from exc
    except ContextDocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ChaveRequest(BaseModel):
    """A chave chega, é guardada e não volta. Nenhuma resposta deste endpoint
    contém o valor, prefixo ou sufixo — só o nome da variável e a quantidade."""
    key_env: str
    valor: str
    # Uma conta pode ter várias chaves: o rotador alterna entre elas quando uma
    # bate a cota. `adicionar` acrescenta em vez de substituir.
    adicionar: bool = False


@app.post("/sentury/providers/keys")
async def guardar_chave(req: ChaveRequest, _: None = Depends(verify_api_token)):
    """Cofre de segredos: grava a chave que o usuário digitou no painel.

    Três coisas que o endpoint garante e por quê:
      - **A resposta não devolve o valor.** Se devolvesse, a chave passaria a
        existir no log do navegador, no histórico de rede e em qualquer
        proxy no caminho.
      - **Só variável conhecida entra** (lista branca do catálogo), senão um
        POST autenticado viraria escrita arbitrária na configuração do processo.
      - **O Robin passa a enxergar a chave na hora** diretamente no cofre e
        reconstrói os adaptadores; a conta entra na cadeia sem reiniciar.
    """
    from robinbandit import secrets
    from robinbandit.accounts import variaveis_conhecidas

    nome = str(req.key_env or "").strip()
    atual = str(getattr(settings, nome, "") or "")
    try:
        # A semente preserva o que o ambiente já tinha: sem ela, acrescentar a
        # terceira chave a uma variável com duas no `.env` deixaria a conta com
        # uma só, porque o cofre vence o ambiente.
        chaves = secrets.guardar(nome, req.valor, permitidos=variaveis_conhecidas(settings, _robin_config),
                               adicionar=req.adicionar, semente=atual)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from .exec.segredos import registrar_configuracao

    registrar_configuracao({"SECRET": chaves})
    _refresh_provider_chains()
    logger.info("Cofre: %s agora tem %d chave(s)", nome, len(chaves))
    return {
        "ok": True,
        "key_env": nome,
        "total": len(chaves),
        "requer_reinicio": False,
    }


@app.post("/sentury/providers/{provider_key}/testar")
async def testar_provedor(provider_key: str, _: None = Depends(verify_api_token)):
    """Uma chamada mínima ao provedor, para quem acabou de colar a chave saber
    na hora se ela funciona. O resultado entra no roteador como qualquer outra
    chamada. O provedor de demonstração não conta: ele sempre responde."""
    from robinbandit.quota_ping import pingar

    provedor = _provider_set.get(provider_key)
    if provedor is None or provider_key == "fallback":
        raise HTTPException(status_code=404, detail="Provedor sem chave ou desconhecido.")
    return await pingar(robin.router, provedor)


@app.delete("/sentury/providers/keys/{key_env}/{indice}")
async def remover_uma_chave(key_env: str, indice: int, _: None = Depends(verify_api_token)):
    """Tira UMA das chaves da variável. Por índice porque o valor nunca sai do
    servidor: o painel conhece só a posição e a dica."""
    from robinbandit import secrets
    removida = secrets.remover_chave(key_env, indice)
    _refresh_provider_chains()
    return {"ok": True, "removida": removida}


@app.delete("/sentury/providers/keys/{key_env}")
async def remover_chave(key_env: str, _: None = Depends(verify_api_token)):
    """Tira a chave do cofre. O ambiente NÃO é limpo: se a variável veio do
    `.env`, ela continua valendo — remover do cofre não pode apagar o que o
    deploy configurou."""
    from robinbandit import secrets
    removida = secrets.remover(key_env)
    _refresh_provider_chains()
    return {"ok": True, "removida": removida, "key_env": str(key_env or "").strip()}


class ContaRequest(BaseModel):
    """Uma conta declarada pelo painel. Configuração, não segredo: `key_env` é
    o NOME da variável onde a chave mora, e a chave vai pelo endpoint do cofre."""
    id: str
    provider: str
    key_env: str
    label: str = ""
    models: List[str] = Field(default_factory=list)
    paga: bool = False


class AlvoDoModoRequest(BaseModel):
    conta: str
    modelos: List[str] = Field(default_factory=list, max_length=50)


class SelecaoDoModoRequest(BaseModel):
    modo: str
    alvos: List[AlvoDoModoRequest] = Field(default_factory=list, max_length=30)


@app.post("/sentury/providers/accounts")
async def salvar_conta(req: ContaRequest, _: None = Depends(verify_api_token)):
    """Cria ou atualiza uma conta. Serve pra ter DUAS contas do mesmo provedor
    (uma paga, uma gratuita) e poder dizer qual delas serve o tier caro.

    Só grava configuração. Depois disso o `key_env` entra na lista branca do
    cofre e a chave pode ser gravada pelo card da conta."""
    from robinbandit import account_config

    try:
        if req.provider not in _robin_config.providers:
            raise ValueError(
                f"provedor '{req.provider}' não existe no YAML do RobinBandit"
            )
        conta = account_config.salvar_conta(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "conta": conta}


@app.delete("/sentury/providers/accounts/{conta_id}")
async def remover_conta(conta_id: str, _: None = Depends(verify_api_token)):
    """Remove uma conta declarada. Conta que veio do ambiente não some por
    aqui: o painel não apaga o que o deploy configurou."""
    from robinbandit import account_config

    removida = account_config.remover_conta(conta_id)
    return {"ok": True, "removida": removida}


@app.get("/sentury/providers/tiers")
async def resolver_tiers(_: None = Depends(verify_api_token)):
    """O que Reforçado e Dedicado vão usar de fato: provedor, chave e modelos.

    A conta escolhida ja define os tres; sem mostrar isso resolvido, o painel
    pede uma escolha e nao diz no que ela deu.
    """
    from robinbandit import account_config
    from robinbandit.accounts import catalogo_efetivo

    catalogo = catalogo_efetivo(settings, _robin_config)
    saida = {}
    for tier, modo in (("ultra", "reforcado"), ("ultra_max", "dedicado")):
        alvos = account_config.selecao_do_modo(modo)
        if not alvos:
            saida[tier] = {
                "origem": "nao_configurado", "conta_id": None,
                "provider": "", "key_env": None, "modelos": [],
                "configurado": False,
            }
            continue
        primeiro = alvos[0]
        conta = catalogo.obter(primeiro["conta"])
        if conta is None:
            saida[tier] = {
                "origem": "conta_ausente", "conta_id": primeiro["conta"],
                "provider": "", "key_env": None,
                "modelos": list(primeiro["modelos"]), "configurado": False,
            }
            continue
        saida[tier] = {
            "origem": "selecao_explicita", "conta_id": conta.id,
            "label": conta.label, "provider": conta.provider,
            "key_env": conta.key_env, "paga": bool(conta.paga),
            "modelos": list(primeiro["modelos"]), "modelos_da_conta": True,
            "configurado": bool(conta.configurada), "total_alvos": len(alvos),
        }
    return {"tiers": saida}


@app.get("/sentury/providers/modes")
async def modos_de_provedor(_: None = Depends(verify_api_token)):
    """Seleções explícitas de Reforçado e Dedicado.

    Conta paga/gratuita é apenas informação; cada alvo precisa trazer os
    modelos escolhidos pelo usuário. Dedicado pode ter vários alvos, mas nunca
    cai no Router porque sua política de execução é estrita.
    """
    from robinbandit import account_config

    return {
        "modes": {
            "ultra": account_config.selecao_do_modo("reforcado"),
            "ultra_max": account_config.selecao_do_modo("dedicado"),
        }
    }


@app.post("/sentury/providers/modes")
async def salvar_modo_de_provedor(
    req: SelecaoDoModoRequest,
    _: None = Depends(verify_api_token),
):
    from robinbandit import account_config
    from robinbandit import account_config
    from robinbandit import account_config
    from robinbandit.accounts import catalogo_efetivo

    modo = {"ultra": "reforcado", "ultra_max": "dedicado"}.get(req.modo, req.modo)
    ids = [c.id for c in catalogo_efetivo(settings, _robin_config).listar()]
    try:
        alvos = account_config.definir_selecao_do_modo(
            modo,
            [alvo.model_dump() for alvo in req.alvos],
            ids_validos=ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "modo": req.modo, "alvos": alvos}


class RoteamentoRequest(BaseModel):
    """Em que tier de roteamento um provedor entra. `tier` vazio devolve ao
    padrão do código."""
    provider: str
    tier: Optional[int] = None


class ModelosDoProvedorRequest(BaseModel):
    """Ordem de modelos que o Router pode tentar neste provedor.

    Lista vazia remove a preferencia do painel e volta ao ambiente/YAML.
    """
    models: List[str] = Field(default_factory=list, max_length=50)
    # Papel do modelo: texto e a cadeia do Router; imagem e escolhida a parte.
    role: str = Field(default="texto")
    # IDs manuais podem existir fora do catálogo (que nem todo provedor expõe).
    allow_unlisted: bool = False


@app.post("/sentury/providers/routing")
async def mover_provedor_de_tier(req: RoteamentoRequest, _: None = Depends(verify_api_token)):
    """Move um provedor entre os tiers de roteamento.

    Não é arrumação de tela: o tier entra no score de toda escolha de provedor
    (RobinBandit), então subir alguém pro Tier
    1 muda de verdade quem o Router tenta primeiro.
    """
    from robinbandit import account_config

    try:
        account_config.definir_tier_de_provedor(req.provider, req.tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "provider": req.provider, "tier": req.tier}


@app.get("/sentury/providers/{provider_key}/models")
async def catalogo_de_modelos(
    provider_key: str,
    force: bool = False,
    _: None = Depends(verify_api_token),
):
    """Catalogo normalizado do RobinBandit, sem credenciais na resposta."""
    from robinbandit.model_catalog import fetch_model_catalog

    try:
        catalog = await fetch_model_catalog(
            _robin_config, provider_key, settings, force=force
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    configured = next(
        (item for item in describe_from_config(_robin_config, settings)
         if item["key"] == provider_key),
        None,
    )
    from robinbandit import account_config

    catalog["selected_models"] = list((configured or {}).get("models") or [])
    catalog["models_overridden"] = bool((configured or {}).get("models_overridden"))
    # Escolhas por papel: a interface monta as abas com o que o catalogo trouxer.
    catalog["selected_by_role"] = {
        papel: list(mapa.get(provider_key, []))
        for papel, mapa in account_config.papeis_configurados().items()
        if mapa.get(provider_key)
    }
    catalog["selected_by_role"].setdefault("texto", catalog["selected_models"])
    return catalog


@app.post("/sentury/providers/{provider_key}/models")
async def escolher_modelos_do_provedor(
    provider_key: str,
    req: ModelosDoProvedorRequest,
    _: None = Depends(verify_api_token),
):
    """Salva a ordem escolhida e reconstrui a cadeia Router imediatamente."""
    from robinbandit import account_config
    from robinbandit.model_catalog import fetch_model_catalog

    key = str(provider_key or "").strip().lower()
    if key not in _robin_config.providers:
        raise HTTPException(status_code=404, detail=f"provedor '{key}' nao existe")
    papel = (str(req.role or "").strip().lower() or "texto")
    selected: List[str] = []
    for raw in req.models:
        model = str(raw or "").strip()
        if model and (len(model) > 200 or any(char.isspace() for char in model)):
            raise HTTPException(status_code=400, detail="ID de modelo deve ter até 200 caracteres e não conter espaços")
        if model and model not in selected:
            selected.append(model)
    if selected and not req.allow_unlisted:
        try:
            catalog = await fetch_model_catalog(_robin_config, key, settings)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        available = {
            str(item.get("id")) for item in catalog.get("models", [])
            if item.get("selectable") and papel in (item.get("roles") or ["texto"])
        }
        unavailable = [model for model in selected if model not in available]
        if unavailable:
            raise HTTPException(
                status_code=400,
                detail=f"modelos indisponiveis no catalogo atual: {', '.join(unavailable)}",
            )
    try:
        saved = account_config.definir_modelos_de_provedor(key, selected, papel)
        # So a cadeia de texto alimenta o Router; imagem e escolha de tarefa.
        if papel == "texto":
            _refresh_provider_chains()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "provider": key, "role": papel, "models": saved, "requer_reinicio": False}


@app.post("/sentury/providers/reset")
async def providers_reset(_: None = Depends(verify_api_token)):
    """Zera os contadores, a latência e o bandit do painel, e o estado persistido."""
    robin.reset()
    try:
        await session_store.set(_ROBIN_STATE_KEY, {}, hot_ttl=604800, warm_ttl=2592000)
    except Exception:
        pass
    return {"ok": True}


@app.get("/sentury/live/status")
async def live_status():
    """Diz se a ligação por voz (Gemini Live) está disponível: precisa da
    GEMINI_API_KEY e da lib google-genai instalada."""
    tem_lib = False
    live_key = get_gemini_live_api_key()
    try:
        import google.genai  # noqa: F401
        tem_lib = True
    except Exception:
        pass
    return {"available": bool(live_key) and tem_lib, "has_key": bool(live_key), "has_lib": tem_lib}


@app.websocket("/sentury/live")
async def live_ws(websocket: WebSocket):
    """Ligação de voz com a Sentury (proxy pra Gemini Live). A chave fica no
    servidor; o browser só troca áudio."""
    await websocket.accept()
    live_keys = get_gemini_live_api_keys()
    if not live_keys:
        await websocket.send_json({"type": "error", "detail": "GEMINI_API_KEY não configurada"})
        await websocket.close()
        return
    try:
        from .external.live_gateway import run_live_bridge
    except Exception as exc:
        await websocket.send_json({"type": "error", "detail": f"google-genai indisponível: {exc}"})
        await websocket.close()
        return
    last_exc = None
    for index, live_key in enumerate(live_keys):
        try:
            voz = escolha_de_voz()
            await run_live_bridge(websocket, data_store, live_key,
                                  model=voz["modelo"] or settings.GEMINI_LIVE_MODEL, voz=voz["voz"] or None)
            return
        except WebSocketDisconnect:
            logger.info("Ligação Live: browser desconectou")
            return
        except Exception as exc:
            last_exc = exc
            retryable = _is_live_key_retryable(exc) and index < len(live_keys) - 1
            logger.warning(
                "Ligação Live falhou com a chave %d/%d: %s%s",
                index + 1,
                len(live_keys),
                exc,
                " — tentando próxima chave" if retryable else "",
            )
            if retryable:
                continue
            break

    if last_exc is not None:
        try:
            await websocket.send_json({"type": "error", "detail": str(last_exc)[:200]})
        except Exception:
            pass


class FlagsRequest(BaseModel):
    autolearn: Optional[bool] = None
    aprender_a_cada: Optional[int] = Field(default=None, ge=0, le=1000)
    gemini_embeddings: Optional[bool] = None
    fastembed_embeddings: Optional[bool] = None
    native_tools: Optional[bool] = None


def _refresh_knowledge_base() -> None:
    global knowledge_base, orchestrator
    knowledge_base = get_knowledge_base(settings)
    orchestrator.knowledge = knowledge_base


@app.get("/sentury/flags")
async def get_flags(_: None = Depends(verify_api_token)):
    """Flags de execução que mudam ao vivo: o settings é lido a cada request."""
    return {
        "autolearn": settings.SENTURY_AUTOLEARN,
        "aprender_a_cada": settings.SENTURY_APRENDER_A_CADA,
        "gemini_embeddings": settings.SENTURY_GEMINI_EMBEDDINGS,
        "fastembed_embeddings": settings.SENTURY_EMBEDDINGS,
        "native_tools": settings.SENTURY_NATIVE_TOOLS,
        "knowledge_mode": knowledge_base.modo if knowledge_base else "desabilitada",
    }


@app.post("/sentury/flags")
async def set_flags(payload: FlagsRequest, _: None = Depends(verify_api_token)):
    rebuild_knowledge = False
    if payload.native_tools is not None:
        settings.SENTURY_NATIVE_TOOLS = payload.native_tools
    if payload.autolearn is not None:
        settings.SENTURY_AUTOLEARN = payload.autolearn
    if payload.aprender_a_cada is not None:
        settings.SENTURY_APRENDER_A_CADA = payload.aprender_a_cada
    if payload.gemini_embeddings is not None and payload.gemini_embeddings != settings.SENTURY_GEMINI_EMBEDDINGS:
        settings.SENTURY_GEMINI_EMBEDDINGS = payload.gemini_embeddings
        rebuild_knowledge = True
    if payload.fastembed_embeddings is not None and payload.fastembed_embeddings != settings.SENTURY_EMBEDDINGS:
        settings.SENTURY_EMBEDDINGS = payload.fastembed_embeddings
        rebuild_knowledge = True
    if rebuild_knowledge:
        _refresh_knowledge_base()
    logger.info(
        "Flags atualizadas: autolearn=%s gemini_embeddings=%s fastembed_embeddings=%s knowledge_mode=%s",
        settings.SENTURY_AUTOLEARN,
        settings.SENTURY_GEMINI_EMBEDDINGS,
        settings.SENTURY_EMBEDDINGS,
        knowledge_base.modo if knowledge_base else "desabilitada",
    )
    return {
        "autolearn": settings.SENTURY_AUTOLEARN,
        "aprender_a_cada": settings.SENTURY_APRENDER_A_CADA,
        "gemini_embeddings": settings.SENTURY_GEMINI_EMBEDDINGS,
        "fastembed_embeddings": settings.SENTURY_EMBEDDINGS,
        "native_tools": settings.SENTURY_NATIVE_TOOLS,
        "knowledge_mode": knowledge_base.modo if knowledge_base else "desabilitada",
    }


@app.get("/sentury/sessions")
async def sessions(user_id: str, limit: int = 30, _: None = Depends(verify_api_token)):
    limit = max(1, min(int(limit or 30), 100))
    items = await session_index.list(user_id)
    # Como o último turno de cada uma terminou: a lista mostra o que espera a
    # pessoa (aprovação, pergunta, turno interrompido) sem ela abrir conversa
    # por conversa.
    return {"sessions": [{**item, "estado_do_turno": registro_do_turno.estado_na_lista(item["session_id"])}
                         for item in items[:limit]]}


@app.get("/sentury/sessions/{session_id}")
async def session_detail(session_id: str, user_id: str, _: None = Depends(verify_api_token)):
    raw = await session_index.load(user_id, session_id)
    if not raw:
        raise HTTPException(status_code=404, detail="sessao nao encontrada")
    state = AnalysisState.from_dict(raw)
    state.prune_transient_failures()
    meta = await session_index.get_meta(user_id, session_id)
    return {"session": meta, "state": state.to_dict()}


@app.get("/sentury/sessions/{session_id}/artifacts/{artifact_id}")
async def session_artifact(
    session_id: str,
    artifact_id: str,
    user_id: str,
    _: None = Depends(verify_api_token),
):
    raw = await session_index.load(user_id, session_id)
    if not raw:
        raise HTTPException(status_code=404, detail="sessao nao encontrada")
    state = AnalysisState.from_dict(raw)
    attachment = state.get_artifact(artifact_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="artefato nao encontrado")
    return {"attachment": attachment}


@app.get("/sentury/artefatos")
async def artefatos(user_id: str, limite: int = 200, _: None = Depends(verify_api_token)):
    """Tudo que o Sentury produziu, de todas as conversas deste usuario.

    A aba Artefatos lia so a memoria do client: o que nao tinha sido aberto
    nesta janela nao existia. Um artefato de terca some porque voce nao clicou
    na conversa de terca — e a biblioteca fica sendo um cache da sessao aberta
    em vez da biblioteca.

    Aqui vai so o metadado; o corpo continua saindo por
    `/sentury/sessions/{id}/artifacts/{artifact_id}`, que e o que evita
    carregar base64 de cem anexos para desenhar uma grade de cartoes.
    """
    limite = max(1, min(int(limite or 200), 500))
    sessoes = await session_index.list(user_id)
    saida: List[Dict[str, Any]] = []
    for meta in sessoes:
        session_id = str((meta or {}).get("session_id") or (meta or {}).get("id") or "")
        if not session_id:
            continue
        try:
            raw = await session_index.load(user_id, session_id)
        except Exception:
            logger.warning("Nao consegui ler a sessao %s para listar artefatos.", session_id)
            continue
        guardados = (raw or {}).get("artifacts")
        if not isinstance(guardados, dict):
            continue
        for artifact_id, registro in guardados.items():
            anexo = (registro or {}).get("attachment")
            if not isinstance(anexo, dict):
                continue
            saida.append({
                "id": str(artifact_id),
                "session_id": session_id,
                "session_title": (meta or {}).get("title") or session_id,
                "titulo": anexo.get("titulo") or anexo.get("title") or anexo.get("nome")
                or anexo.get("filename") or "artefato",
                "tipo": anexo.get("tipo") or anexo.get("type") or "file",
                "criado_em": (registro or {}).get("created_at") or 0,
            })
    # Mais novo primeiro: a biblioteca e consultada de tras para frente.
    saida.sort(key=lambda item: item.get("criado_em") or 0, reverse=True)
    return {"artefatos": saida[:limite], "total": len(saida)}


@app.delete("/sentury/sessions/{session_id}")
async def apagar_sessao(session_id: str, user_id: str, _: None = Depends(verify_api_token)):
    """Apaga a conversa e tira do indice. O `user_id` e obrigatorio: sem ele um
    usuario apagaria a sessao de outro."""
    await session_store.delete(session_id)
    try:
        await session_index.remove(user_id, session_id)
    except Exception:
        logger.warning("Sessao %s apagada, mas o indice de %s nao atualizou.", session_id, user_id)
    # O navegador, os anexos e o trabalho intermediario da conversa vao junto.
    from .tools import browser_registry
    from .tools.computador import encerrar_sessao as _encerrar_computador
    from .tools.arquivos import apagar_rascunho

    browser_registry.encerrar(session_id)
    _encerrar_computador(session_id)
    from .memory import goals as _goals

    aberto = _goals.em_aberto(session_id)
    if aberto is not None:
        _goals.abandonar(aberto.id, "conversa apagada")
    trava_da_sessao.esquecer(session_id)
    registro_do_turno.apagar(session_id)

    rascunho_apagado = apagar_rascunho(session_id)
    return {"ok": True, "session_id": session_id, "rascunho_apagado": rascunho_apagado}


@app.post("/sentury/sessions/{session_id}/title")
async def session_title(session_id: str, payload: SessionTitleRequest, _: None = Depends(verify_api_token)):
    meta = await session_index.rename(payload.user_id, session_id, payload.title, source="manual")
    if not meta:
        raise HTTPException(status_code=404, detail="sessao nao encontrada")
    return {"session": meta}


class TarefasLateraisRequest(BaseModel):
    modelo: str = Field(..., pattern="^(atual|auxiliar)$")


@app.get("/sentury/tarefas-laterais")
async def ler_tarefas_laterais(_: None = Depends(verify_api_token)):
    """Quem compacta o histórico e dá título: o modelo da conversa ou um auxiliar."""
    from .llm.auxiliar import modelo_lateral

    return {"modelo": modelo_lateral(), "rota_declarada": auxiliar_llm.rota_declarada()}


@app.put("/sentury/tarefas-laterais")
async def salvar_tarefas_laterais(payload: TarefasLateraisRequest, _: None = Depends(verify_api_token)):
    from .llm.auxiliar import definir_modelo_lateral

    return {"modelo": definir_modelo_lateral(payload.modelo), "rota_declarada": auxiliar_llm.rota_declarada()}


@app.get("/sentury/interface/preferencias")
async def ler_preferencias(user_id: str, _: None = Depends(verify_api_token)):
    """Pastas, fixados e recolhidos da barra lateral."""
    from .memory import preferencias_ui

    return await preferencias_ui.ler(session_store, user_id)


@app.put("/sentury/interface/preferencias")
async def salvar_preferencias(payload: InterfacePrefsRequest,
                              _: None = Depends(verify_api_token)):
    from .memory import preferencias_ui

    return await preferencias_ui.gravar(
        session_store, payload.user_id,
        {"pastas": payload.pastas, "sessoes": payload.sessoes,
         "raiz_recolhida": payload.raiz_recolhida},
    )


class PastaRequest(BaseModel):
    caminho: str = Field(..., min_length=1, max_length=4096)


class TrabalhoRequest(BaseModel):
    caminho: str = Field("", max_length=4096)
    universal: Optional[bool] = None


@app.get("/sentury/pastas")
async def listar_pastas(_: None = Depends(verify_api_token)):
    """Onde o agente pode ler e escrever."""
    from .tools.arquivos import (
        instalacao_do_sentury, pastas_extras, raiz_de_trabalho, tudo_liberado,
    )

    trabalho = raiz_de_trabalho()
    return {
        "projeto": str(trabalho),
        "extras": [str(p) for p in pastas_extras()],
        "universal": tudo_liberado(),
        "instalacao": str(instalacao_do_sentury()),
        "trabalhando_na_instalacao": trabalho == instalacao_do_sentury(),
    }


class ShellRequest(BaseModel):
    ligado: bool


@app.put("/sentury/shell")
async def ligar_shell(payload: ShellRequest, _: None = Depends(verify_api_token)):
    """Liga ou desliga a execucao de comandos, sem reiniciar."""
    settings.SENTURY_SHELL = bool(payload.ligado)
    return {"ligado": bool(settings.SENTURY_SHELL)}


@app.get("/sentury/pastas/navegar")
async def navegar_pastas(caminho: str = "", _: None = Depends(verify_api_token)):
    """Subpastas de um caminho, para escolher sem digitar.

    O navegador nao entrega o caminho absoluto de uma pasta escolhida — por
    seguranca dele —, entao quem lista e o servidor.
    """
    from pathlib import Path as _Path

    alvo = _Path(caminho).expanduser() if caminho.strip() else _Path.home()
    try:
        alvo = alvo.resolve()
    except Exception:
        alvo = _Path.home()
    if not alvo.is_dir():
        alvo = _Path.home()

    filhas = []
    try:
        for item in sorted(alvo.iterdir(), key=lambda i: i.name.lower()):
            if item.is_dir() and not item.name.startswith("."):
                filhas.append({"nome": item.name, "caminho": str(item)})
    except PermissionError:
        pass
    return {
        "atual": str(alvo),
        "pai": str(alvo.parent) if alvo.parent != alvo else "",
        "pastas": filhas[:400],
    }


@app.put("/sentury/pastas/trabalho")
async def trocar_trabalho(payload: TrabalhoRequest, _: None = Depends(verify_api_token)):
    """Troca a pasta de trabalho, ou liga/desliga o acesso irrestrito."""
    from .tools.arquivos import definir_trabalho, definir_universal

    if payload.universal is not None:
        return definir_universal(payload.universal)
    resultado = definir_trabalho(payload.caminho)
    if not resultado.get("ok"):
        raise HTTPException(status_code=400, detail=resultado.get("erro") or "caminho invalido")
    return resultado


@app.post("/sentury/pastas")
async def liberar_pasta_extra(payload: PastaRequest, _: None = Depends(verify_api_token)):
    from .tools.arquivos import liberar_pasta

    resultado = liberar_pasta(payload.caminho)
    if not resultado.get("ok"):
        raise HTTPException(status_code=400, detail=resultado.get("erro") or "caminho invalido")
    return resultado


@app.delete("/sentury/pastas")
async def tirar_pasta_extra(caminho: str, _: None = Depends(verify_api_token)):
    from .tools.arquivos import esquecer_pasta

    return esquecer_pasta(caminho)


@app.get("/sentury/identidade")
async def identidade_local(_: None = Depends(verify_api_token)):
    """Quem e o usuario desta instalacao: a maquina decide, nao o navegador."""
    from .memory import identidade as _identidade

    return {"user_id": await _identidade.resolver(session_store), "origem": "maquina"}


async def _revisar_o_aprendizado(state: AnalysisState, tier: Any) -> None:
    """A pausa de revisão no mesmo modo do turno: o modelo é o mesmo e o cache
    do prefixo ainda está quente."""
    from .harness.aprendizado import revisar

    token = use_ultra_provider(tier) if tier is not None else None
    try:
        await revisar(orchestrator, state)
        curator.run_curator(stale_days=30, archive_days=90)
    except Exception as exc:
        logger.error("Falha na revisão do aprendizado: %s", exc)
    finally:
        if token is not None:
            clear_ultra_provider(token)


def _agendar_aprendizado(background_tasks: BackgroundTasks, state: AnalysisState,
                         result: Dict[str, Any], tier: Any) -> None:
    """Conta as voltas do turno e, quando chega a vez, agenda a revisão.

    Roda antes de persistir o estado, para a contagem sobreviver ao turno."""
    from .harness.aprendizado import chegou_a_vez, contar

    contar(state, result)
    if chegou_a_vez(state):
        background_tasks.add_task(_revisar_o_aprendizado, AnalysisState.from_dict(state.to_dict()), tier)


def _exemplos_de_alerta() -> list:
    """Um exemplo por métrica que o setor ativo sabe vigiar."""
    from .domains.do_setor import metricas_vigiaveis
    from .external.cron_scheduler import _maior_e_melhor

    return [
        f"{rotulo} {'abaixo' if _maior_e_melhor(chave) else 'acima'} de 50"
        for chave, rotulo in list(metricas_vigiaveis().items())[:3]
    ]


def _handle_alert_command(session_id: str, user_id: str, message: str, chat_id: Any = None) -> str:
    """Interpreta `/alerta ...`: cria/lista/remove alertas por limiar."""
    raw = message.strip()[len("/alerta"):].strip()
    low = raw.lower()

    if low in ("", "list", "lista", "listar"):
        alertas = [j for j in cron_scheduler.list_jobs(session_id) if j.get("kind") == "alert"]
        if not alertas:
            exemplos = _exemplos_de_alerta()
            if not exemplos:
                return "Nenhum alerta ativo. O setor ativo não tem métrica para vigiar."
            return f"Nenhum alerta ativo. Ex.: `/alerta {exemplos[0]}`."
        linhas = [f"• `{a['id']}` — {a.get('metric','?').upper()} {a.get('op')} {a.get('threshold')} (checou {a['run_count']}x)" for a in alertas]
        return "**Alertas ativos:**\n" + "\n".join(linhas) + "\n\nRemover: `/alerta off`."

    if low.startswith(("stop", "parar", "off", "remove", "remover", "cancela")):
        removidos = sum(1 for j in cron_scheduler.list_jobs(session_id)
                        if j.get("kind") == "alert" and cron_scheduler.remove_job(j["id"]))
        return f"Removi {removidos} alerta(s) desta conversa."

    parsed = parse_alert_command(raw)
    if not parsed:
        exemplos = _exemplos_de_alerta()
        if not exemplos:
            return ("O setor ativo não tem métrica para vigiar por limiar. "
                    "Para acompanhar algo de tempos em tempos, use `/cron`.")
        linhas = "".join(f"• `/alerta {e}`\n" for e in exemplos)
        return f"Não entendi o alerta. Exemplos:\n{linhas}• `/alerta list` · `/alerta off`."
    try:
        job = cron_scheduler.add_alert_job(
            session_id, user_id, parsed["metric"], parsed["op"], parsed["threshold"],
            interval_sec=parsed.get("interval_sec", 120), chat_id=chat_id,
        )
    except ValueError as e:
        return f"Não consegui criar o alerta: {e}"
    label = job.get("metric", "").upper()
    return (f"Alerta criado! Vou checar a cada {job['interval_sec']}s e te aviso se **{label} {job['op']} {job['threshold']}**.\n"
            f"(id `{job['id']}` — `/alerta off` para parar.)")


def _handle_cron_command(session_id: str, user_id: str, message: str, chat_id: Any = None) -> str:
    """Interpreta `/cron ...` do painel: cria/lista/remove agendamentos."""
    raw = message.strip()[len("/cron"):].strip()
    low = raw.lower()

    if low in ("", "list", "lista", "listar", "status"):
        jobs = cron_scheduler.list_jobs(session_id)
        if not jobs:
            return "Nenhum agendamento ativo. Ex.: `/cron todo dia às 9h me dê um resumo das tarefas abertas`."
        def _quando(j):
            if j.get("kind") == "once":
                return f"uma vez em {j.get('run_at')}"
            if j.get("kind") == "cron":
                return f"cron {j.get('cron_expr')}"
            return f"a cada {j.get('interval_sec')}s"
        linhas = [f"• `{j['id']}` — {_quando(j)}: {j['prompt']} (rodou {j['run_count']}x)" for j in jobs]
        return "**Agendamentos ativos:**\n" + "\n".join(linhas) + "\n\nRemover: `/cron stop <id>` ou `/cron off`."

    if low.startswith(("stop", "parar", "remove", "remover", "off", "cancela")):
        partes = low.split()
        if len(partes) >= 2 and partes[1] not in ("all", "tudo", "todos"):
            ok = cron_scheduler.remove_job(partes[1])
            return f"Agendamento `{partes[1]}` removido." if ok else f"Não encontrei o agendamento `{partes[1]}`."
        removidos = sum(1 for j in cron_scheduler.list_jobs(session_id) if cron_scheduler.remove_job(j["id"]))
        return f"Removi {removidos} agendamento(s) desta conversa."

    parsed = parse_cron_command(raw)
    if not parsed:
        return ("Não entendi o agendamento. Exemplos:\n"
                "• `/cron a cada 30 minutos confira se a pasta do projeto mudou`\n"
                "• `/cron todo dia às 9h me dê um resumo das tarefas abertas`\n"
                "• `/cron list` para ver os ativos · `/cron off` para parar todos.")
    try:
        if parsed.get("kind") == "once":
            job = cron_scheduler.add_once_job(
                session_id, user_id, parsed["prompt"],
                delay_sec=parsed.get("delay_sec"), run_at=parsed.get("run_at"), chat_id=chat_id,
            )
        else:
            job = cron_scheduler.add_job(
                session_id, user_id, parsed["prompt"],
                interval_sec=parsed.get("interval_sec"), cron_expr=parsed.get("cron_expr"),
                chat_id=chat_id,
            )
    except ValueError as e:
        return f"Não consegui agendar: {e}"

    if job["kind"] == "once":
        quando = f"uma vez em **{job['run_at']}**"
    elif job["kind"] == "cron":
        quando = f"no horário agendado (cron `{job['cron_expr']}`)"
    else:
        seg = job["interval_sec"]
        intervalo_txt = f"{seg // 3600}h" if seg >= 3600 else (f"{seg // 60} min" if seg >= 60 else f"{seg}s")
        quando = f"a cada **{intervalo_txt}**"
    onde = "te mando aqui" if chat_id is not None else "postar aqui no painel"
    return (f"Agendado! Vou rodar {quando}: \"{job['prompt']}\" e {onde}.\n"
            f"(id `{job['id']}` — use `/cron off` para parar.)")


# O Telegram usa os mesmos comandos deterministicos do painel.
telegram_manager.comandos = {"/alerta": _handle_alert_command, "/cron": _handle_cron_command}
# Aprovação pelos botões do Telegram: o goal parado volta como pelo cartão do painel.
telegram_manager.depois_da_permissao = lambda sessao, escolha: _retomar_goal_da_permissao(sessao, escolha)


def _ultra_failure_result(state: AnalysisState, user_message: str, mode: str, exc: Exception) -> Dict[str, Any]:
    """A frase separa o que a pessoa resolve (o modelo do modo não respondeu)
    do que é defeito do Sentury: culpar o provedor por um erro interno manda
    a pessoa conferir a conta à toa."""
    from robinbandit.routing.chain import FalhaDaCadeia

    label = "Dedicado" if mode == "ultra_max" else "Reforçado"
    detail = str(exc).strip().replace("\n", " ")[:220] or type(exc).__name__
    if isinstance(exc, FalhaDaCadeia):
        reply = (
            f"Os modelos do {label} não responderam agora, e ele não recorre a outros modelos. "
            "Tente de novo em instantes ou confira a conta e o modelo do modo em Provedores."
            f"\n\nDetalhe: {detail}"
        )
    else:
        logger.error("Erro interno no turno do modo %s.", label, exc_info=exc)
        reply = (
            "O turno parou por um erro interno do Sentury, não do provedor. "
            "Tente de novo; se repetir, reinicie o Sentury."
            f"\n\nDetalhe: {detail}"
        )
    if not state.history or state.history[-1].get("role") != "user" or state.history[-1].get("content") != user_message:
        state.history.append({"role": "user", "content": user_message, "priority": "NORMAL"})
    state.history.append({"role": "assistant", "content": reply, "transient_error": True})
    telemetry = {"execution_ms": 0, "provider_error": detail, "mode": mode}
    decision_log = {
        "proposed_tool": None,
        "harness_allowed": False,
        "harness_reason": f"{label}: provedor pago falhou; fallback gratis bloqueado",
        "events": ["ULTRA_PROVIDER_FAILED"],
        "responder_model": None,
    }
    try:
        from .observability import record_turn_trace
        record_turn_trace(
            session_id=state.session_id,
            user_id=state.user_id,
            user_message=user_message,
            reply=reply,
            decision_log=decision_log,
            telemetry=telemetry,
            tool_results=[],
            deliberation=None,
            mode=mode,
            intent="ERROR",
            complexity=None,
        )
    except Exception:
        pass
    return {
        "message": reply,
        "attachment": None,
        "harness": decision_log,
        "state": state.to_dict(),
        "learned": None,
        "telemetry": telemetry,
        "compacted": False,
    }


@app.post("/chat")
async def chat(payload: ChatRequest, background_tasks: BackgroundTasks, _: None = Depends(verify_api_token)):
    is_valid, reason = validate_message(payload.message)
    if not is_valid:
        raise HTTPException(status_code=400, detail=reason)
    # Do carregar ao gravar: o turno automatico do goal e este nao se atropelam.
    async with trava_da_sessao.da(payload.session_id):
        return await _chat_na_trava(payload, background_tasks)


async def _chat_na_trava(payload: ChatRequest, background_tasks: BackgroundTasks):
    raw_state, state = await _load_state(payload.session_id, payload.user_id)
    if payload.regenerate:
        _prepare_regeneration(state, payload.message)

    # Interceptação de alertas por limiar (cron reativo).
    if payload.message.strip().lower().startswith("/alerta"):
        reply = _handle_alert_command(payload.session_id, payload.user_id, payload.message)
        state.history.append({"role": "user", "content": payload.message})
        state.history.append({"role": "assistant", "content": reply})
        state_dict = await _persist_state(state)
        _schedule_autotitle(background_tasks, state, _tier_provider_for(payload.mode))
        return {
            "message": reply, "attachment": None,
            "harness": {"proposed_tool": "alerta", "harness_allowed": True,
                        "harness_reason": "Alerta por limiar (determinístico)", "events": []},
            "state": state_dict, "learned": None,
            "telemetry": {"execution_ms": 1}, "compacted": False,
        }

    # Interceptação do agendador (cron) — cria/lista/remove jobs sem LLM.
    if payload.message.strip().lower().startswith("/cron"):
        reply = _handle_cron_command(payload.session_id, payload.user_id, payload.message)
        state.history.append({"role": "user", "content": payload.message})
        state.history.append({"role": "assistant", "content": reply})
        state_dict = await _persist_state(state)
        _schedule_autotitle(background_tasks, state, _tier_provider_for(payload.mode))
        return {
            "message": reply, "attachment": None,
            "harness": {"proposed_tool": "cron", "harness_allowed": True,
                        "harness_reason": "Agendador (cron) determinístico", "events": []},
            "state": state_dict, "learned": None,
            "telemetry": {"execution_ms": 1}, "compacted": False,
        }

    # Recuperação de contexto se vier do Warm Cache
    if raw_state and raw_state.get("recovered"):
        summary = state.conversation_state.human_summary or "Conversa anterior consolidada."
        state.history = [
            {
                "role": "system",
                "content": f"[Recuperação de Contexto: O usuário retornou após algum tempo. Resumo da conversa anterior: {summary}]",
                "priority": "HIGH"
            }
        ]
        logger.info("Contexto recuperado do Warm Cache com sucesso para a sessão %s", payload.session_id)

    # Reforçado/Dedicado: ativa o alvo do tier somente para este request.
    mensagem = _preparar_turno(state, payload)
    _ultra_token = None
    _ultra_classify_token = None
    _tier = _tier_provider_for(payload.mode)
    if _tier is not None:
        _ultra_token = use_ultra_provider(_tier)
        if payload.mode == "ultra_max":
            _ultra_classify_token = use_ultra_classify_provider(
                _tier_provider_for("ultra")
            )
    _effort_token = None
    try:
        try:
            result = await orchestrator.handle_message(state, mensagem,
                                                       effort=_effort_da_barra(payload))
        except Exception as exc:
            if _tier is None:
                raise
            logger.warning("Falha no modo %s sem fallback gratis: %s", payload.mode, exc)
            result = _ultra_failure_result(state, mensagem, payload.mode, exc)
    finally:
        if _effort_token is not None:
            clear_effort(_effort_token)
        if _ultra_classify_token is not None:
            clear_ultra_classify_provider(_ultra_classify_token)
        if _ultra_token is not None:
            clear_ultra_provider(_ultra_token)

    _agendar_aprendizado(background_tasks, state, result, _tier)
    _attach_result_to_last_assistant(state, result)
    state_dict = await _persist_state(state)
    result["state"] = state_dict
    _schedule_autotitle(background_tasks, state, _tier)

    return result


@app.post("/chat/orientar", status_code=202)
async def chat_orientar(payload: OrientarRequest, _: None = Depends(verify_api_token)):
    """Aplica uma orientação no próximo ponto seguro de um turno ativo.

    Sem turno em curso, responde 409 para que o cliente envie uma mensagem nova.
    """
    is_valid, reason = validate_message(payload.texto)
    if not is_valid:
        raise HTTPException(status_code=400, detail=reason)
    orientacao = caixa_do_turno.receber(payload.session_id, payload.texto, payload.id_cliente)
    if orientacao is None:
        raise HTTPException(status_code=409, detail="Nenhum turno em curso nesta conversa.")
    return {"seq": orientacao.seq, "fase": "recebida"}


@app.get("/sentury/sessions/{session_id}/turno")
async def turno_da_sessao(session_id: str, _: None = Depends(verify_api_token)):
    """O registro do turno mais recente da conversa (harness/registro_do_turno.py).
    `status: reinicio` e o turno que o servidor derrubou ao cair."""
    return registro_do_turno.ler(session_id) or {}


@app.post("/sentury/sessions/{session_id}/turno/continuar")
async def continuar_turno(session_id: str, _: None = Depends(verify_api_token)):
    """Continuar depois do reinicio: o proximo turno da conversa comeca com o
    que ja tinha sido feito, para nada ser feito duas vezes."""
    registro = registro_do_turno.continuar(session_id)
    if registro is None:
        raise HTTPException(status_code=409, detail="Nao ha turno interrompido pelo reinicio nesta conversa.")
    return {"mensagem": registro["pedido"], "funcoes": registro.get("funcoes")}


@app.post("/sentury/sessions/{session_id}/turno/dispensar")
async def dispensar_turno(session_id: str, _: None = Depends(verify_api_token)):
    return {"dispensado": registro_do_turno.dispensar(session_id)}


class PararRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)


@app.post("/chat/parar")
async def chat_parar(payload: PararRequest, _: None = Depends(verify_api_token)):
    """O Parar do chat, cooperativo: leitura e cortada na hora; escrita,
    envio ou comando terminam e o turno para antes do passo seguinte. O stream
    termina com `parado`. `esperando` diz qual ferramenta ainda termina."""
    return turno_em_curso.pedir_parada(payload.session_id)


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest, background_tasks: BackgroundTasks, _: None = Depends(verify_api_token)):
    """Igual ao /chat, mas devolve a resposta em STREAMING (SSE), token a token —
    efeito 'digitando' no conteúdo real. O pipeline roda inteiro no servidor e a
    mensagem final é transmitida em pedaços; o evento 'done' carrega o payload
    completo (attachment/harness/telemetria) pro frontend aplicar o resto."""
    import asyncio as _asyncio
    import json
    import re as _re

    from fastapi.responses import StreamingResponse

    is_valid, reason = validate_message(payload.message)
    if not is_valid:
        raise HTTPException(status_code=400, detail=reason)

    low = payload.message.strip().lower()
    raw_state = state = mensagem = None

    async def gen():
        # A trava vale o turno inteiro, do carregar ao gravar: carregar fora
        # dela deixaria o turno automatico do goal gravar por cima deste.
        nonlocal raw_state, state, mensagem
        async with trava_da_sessao.da(payload.session_id):
            try:
                raw_state, state = await _load_state(payload.session_id, payload.user_id)
                if payload.regenerate:
                    _prepare_regeneration(state, payload.message)
                mensagem = _preparar_turno(state, payload)
            except Exception as exc:
                logger.warning("Falha ao preparar o /chat/stream: %s", exc)
                yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)[:200]})}\n\n"
                return
            async for pedaco in _corpo():
                yield pedaco

    async def _corpo():
        try:
            if low.startswith("/alerta"):
                reply = _handle_alert_command(payload.session_id, payload.user_id, payload.message)
                result = {"message": reply, "attachment": None,
                          "harness": {"proposed_tool": "alerta", "harness_allowed": True, "harness_reason": "Alerta", "events": []},
                          "state": None, "learned": None, "telemetry": {"execution_ms": 1}, "compacted": False}
                state.history.append({"role": "user", "content": payload.message})
                state.history.append({"role": "assistant", "content": reply})
            elif low.startswith("/cron"):
                reply = _handle_cron_command(payload.session_id, payload.user_id, payload.message)
                result = {"message": reply, "attachment": None,
                          "harness": {"proposed_tool": "cron", "harness_allowed": True, "harness_reason": "Cron", "events": []},
                          "state": None, "learned": None, "telemetry": {"execution_ms": 1}, "compacted": False}
                state.history.append({"role": "user", "content": payload.message})
                state.history.append({"role": "assistant", "content": reply})
            else:
                # roda o pipeline como task e transmite as ETAPAS (SSE) enquanto
                # roda — o usuário vê "Entendendo → Consultando → Redigindo".
                fila = _asyncio.Queue()

                def _cb(evento):
                    # Aceita o evento estruturado novo (dict: tool_start/tool_complete/
                    # reasoning/stage) e também a string legada (vira 'stage').
                    try:
                        fila.put_nowait(evento)
                    except Exception:
                        pass

                # Modo Ultra/Super ativo antes do create_task → a task filha herda o
                # contextvar (asyncio copia o contexto na criação).
                _ultra_token = None
                _ultra_classify_token = None
                _tier = _tier_provider_for(payload.mode)
                if _tier is not None:
                    _ultra_token = use_ultra_provider(_tier)
                    if payload.mode == "ultra_max":
                        _ultra_classify_token = use_ultra_classify_provider(
                            _tier_provider_for("ultra")
                        )
                _effort_token = None
                task = None
                # O registro do turno (RunState): harness/registro_do_turno.py.
                registro_do_turno.abrir(state, mensagem)
                _motivo = registro_do_turno.FALHA
                try:
                    try:
                        task = _asyncio.create_task(
                            orchestrator.handle_message(state, mensagem, progress_cb=_cb,
                                                        effort=_effort_da_barra(payload))
                        )
                        # O atalho do computer use para o turno por aqui; ver
                        # harness/turno_em_curso.py.
                        turno_em_curso.registrar(payload.session_id, task)
                        while not task.done() or not fila.empty():
                            try:
                                evento = await _asyncio.wait_for(fila.get(), timeout=0.15)
                                if isinstance(evento, str):
                                    evento = {"type": "stage", "text": evento}
                                yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
                            except _asyncio.TimeoutError:
                                continue
                        _parado = task.cancelled() and turno_em_curso.foi_parado(task)
                        # Sem turno registrado, orientação nova recebe 409 e vira
                        # mensagem normal; a que chegou tarde vai para o próximo turno.
                        turno_em_curso.esquecer(payload.session_id, task)
                        for _o in caixa_do_turno.encerrar(payload.session_id):
                            yield f"data: {json.dumps({'type': caixa_do_turno.EVENTO, 'seq': _o.seq, 'id_cliente': _o.id_cliente, 'fase': 'proximo_turno'})}\n\n"
                        if _parado:
                            _motivo = registro_do_turno.PARADO
                            # Parado de proposito: a tela trata como o botao de
                            # parar, nao como conexao caida.
                            yield f"data: {json.dumps({'type': 'parado'})}\n\n"
                            return
                        result = await task
                        _motivo = registro_do_turno.motivo_do_resultado(result)
                    except _asyncio.CancelledError:
                        _motivo = registro_do_turno.CONEXAO_CAIU
                        if task is not None and not task.done():
                            # Conexao caiu: o mesmo Parar cooperativo do botao.
                            # Escrita em curso termina; o prazo garante o fim.
                            if not turno_em_curso.pedir_parada(payload.session_id)["havia"]:
                                task.cancel()
                            try:
                                await task
                            except BaseException:
                                pass
                        raise
                    except Exception as exc:
                        if _tier is None:
                            raise
                        logger.warning("Falha no modo %s sem fallback gratis (stream): %s", payload.mode, exc)
                        result = _ultra_failure_result(state, mensagem, payload.mode, exc)
                finally:
                    if task is not None:
                        turno_em_curso.esquecer(payload.session_id, task)
                        caixa_do_turno.encerrar(payload.session_id)
                    registro_do_turno.fechar(payload.session_id, _motivo)
                    if _effort_token is not None:
                        clear_effort(_effort_token)
                    if _ultra_classify_token is not None:
                        clear_ultra_classify_provider(_ultra_classify_token)
                    if _ultra_token is not None:
                        clear_ultra_provider(_ultra_token)
                _agendar_aprendizado(background_tasks, state, result, _tier)
            _attach_result_to_last_assistant(state, result)
            state_dict = await _persist_state(state)
            result["state"] = state_dict
            _schedule_autotitle(background_tasks, state, _tier_provider_for(payload.mode))

            # Com anexo HTML, remove o bloco inline para evitar dois previews.
            # Esta guarda cobre saídas que não passaram pela limpeza do turno.
            texto = tirar_html_repetido(
                result.get("message") or "", result.get("attachment")
            )
            result["message"] = texto
            for tok in _re.findall(r"\S+\s*|\n+", texto):
                yield f"data: {json.dumps({'type': 'token', 'text': tok}, ensure_ascii=False)}\n\n"
                await _asyncio.sleep(0.012)  # ritmo de digitação
            yield f"data: {json.dumps({'type': 'done', 'result': result}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.warning("Falha no /chat/stream: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)[:200]})}\n\n"

    from fastapi.responses import StreamingResponse

    # O turno nao vive mais dentro da conexao: publica numa transmissao
    # numerada e a resposta so assiste. Caiu a conexao, a tela volta por
    # /chat/stream/{sessao}/retomar; ninguem voltou, ele para. Ver
    # harness/transmissao.py.
    def _abandonar():
        if canal.produtor is not None and not canal.produtor.done():
            canal.produtor.cancel()

    canal = transmissao.abrir(payload.session_id, ao_abandonar=_abandonar)

    async def _produzir():
        try:
            async for pedaco in gen():
                canal.publicar(pedaco)
        finally:
            canal.encerrar()

    canal.produtor = _asyncio.create_task(_produzir())
    return StreamingResponse(canal.assistir(0), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "X-Sentury-Transmissao": canal.id})


@app.get("/chat/stream/{session_id}/retomar")
async def chat_stream_retomar(session_id: str, desde: int = 0, transmissao_id: str = "",
                              _: None = Depends(verify_api_token)):
    """A tela perdeu a conexao no meio do turno e volta: recebe os eventos
    depois do `desde` (o ultimo `id:` que chegou). 404 se o turno ja acabou ha
    mais de dois minutos ou se outro turno comecou."""
    from fastapi.responses import StreamingResponse

    canal = transmissao.da(session_id, transmissao_id)
    if canal is None:
        raise HTTPException(status_code=404, detail="Nenhum turno para retomar nesta conversa.")
    return StreamingResponse(canal.assistir(desde), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "X-Sentury-Transmissao": canal.id})


async def _rodar_turno_do_goal(goal, mensagem: str) -> Dict[str, Any]:
    """Um turno automatico do goal: o mesmo caminho do /chat, sob a mesma trava,
    no modo que a pessoa escolheu ao aprovar."""
    async with trava_da_sessao.da(goal.session_id):
        _, state = await _load_state(goal.session_id, goal.user_id)
        _ultra_token = _ultra_classify_token = None
        _tier = _tier_provider_for(goal.modo)
        if _tier is not None:
            _ultra_token = use_ultra_provider(_tier)
            if goal.modo == "ultra_max":
                _ultra_classify_token = use_ultra_classify_provider(_tier_provider_for("ultra"))
        # O mesmo registro do turno do /chat/stream: o goal que roda sozinho
        # aparece na lista trabalhando, e o que parou pedindo aprovação ou com
        # pergunta aparece esperando a pessoa.
        registro_do_turno.abrir(state, mensagem)
        _motivo = registro_do_turno.FALHA
        try:
            try:
                result = await orchestrator.handle_message(state, mensagem)
            except Exception as exc:
                if _tier is None:
                    raise
                result = _ultra_failure_result(state, mensagem, goal.modo, exc)
            _motivo = registro_do_turno.motivo_do_resultado(result)
        finally:
            registro_do_turno.fechar(goal.session_id, _motivo)
            if _ultra_classify_token is not None:
                clear_ultra_classify_provider(_ultra_classify_token)
            if _ultra_token is not None:
                clear_ultra_provider(_ultra_token)
        # A mensagem de continuacao entra no historico como a da pessoa; a
        # marca deixa a tela mostrar que foi automatica.
        for message in reversed(state.history):
            if message.get("role") == "user" and message.get("content") == mensagem:
                message["origem"] = "goal"
                break
        ultima = next((m for m in reversed(state.history) if m.get("role") == "assistant"), None)
        result["falhou"] = bool(ultima and is_transient_failure_message(ultima))
        if result["falhou"]:
            # Vai para o motivo da pausa: "3 turnos falharam" sozinho nao diz
            # se foi cota, chave ou provedor fora.
            result["erro"] = str(ultima.get("content") or "")[:200]
        _attach_result_to_last_assistant(state, result)
        await _persist_state(state)
        return result


async def _resumo_da_mesa_no_telegram(assunto) -> None:
    from .residentes import telegram as _residentes_telegram

    aviso = _residentes_telegram.aviso_de_fechamento(assunto)
    if aviso and telegram_manager.status in {"online", "running"}:
        await telegram_manager.avisar_residente(*aviso)


async def _decidir_entrada_na_mesa(agente, assunto) -> bool:
    """Entrar ou não num assunto da Mesa: decisão de sim ou não no modelo barato
    do Router, nunca no cérebro principal do residente."""
    from .context.base import _texto_base

    mensagens = [
        {"role": "system", "content": _texto_base("MESA_ENTRAR")},
        {"role": "user", "content": (
            f"Especialista: {agente.nome}, {agente.papel}. Objetivo: {agente.objetivo}\n"
            f"Assunto: {assunto.titulo}\n{assunto.texto}".strip())},
    ]
    resposta = await planner_llm.complete(mensagens, temperature=0.0, complexity="CLASSIFY",
                                          profile="classify")
    return str(resposta or "").strip().lower().startswith("sim")


async def _rodar_turno_do_residente(agente, tarefa) -> Dict[str, Any]:
    """Um turno do agente residente: a conversa dele, a identidade dele e só as
    ferramentas do manifesto."""
    from .residentes import escopo as _escopo
    from .residentes import hq as _hq
    from .residentes import registro as _registro_residente
    from .residentes import tarefas as _tarefas_residente

    sessao, sem_historico = _hq.sessao_da_vez(agente.nome, tarefa.origem)
    mensagem = _tarefas_residente.mensagem_do_turno(tarefa)
    from .residentes.anexos import contexto_dos_anexos
    mensagem += await contexto_dos_anexos(agente, tarefa)
    async with trava_da_sessao.da(sessao):
        _, state = await _load_state(sessao, "hq")
        if sem_historico:
            state.history = []
        from .residentes import memoria as _memoria_residente
        from .residentes.identidade import vestir as _vestir
        _vestir(state, agente, _memoria_residente.para_o_turno(agente.nome, mensagem), mensagem)
        devolvido = _tarefas_residente.resultado_dos_colegas(tarefa)
        if devolvido:
            # O coordenador junta as respostas no fim: elas ficam inteiras mesmo
            # quando outro colega responde depois e o turno recomeça.
            from .harness.context_budget import MANTER_INTEIRO
            from .llm.prompts import _cabe_no_contexto

            # Acima da régua de resultado grande, o texto inteiro vai para o rascunho
            # e aqui ficam o começo, o fim e onde ler o resto.
            corpo, aviso = _cabe_no_contexto("pedir_ao_agente", devolvido, sessao)
            conteudo = f"{corpo}\n{aviso}" if aviso else corpo
            state.history.append({"role": "system", "content": conteudo, "priority": "HIGH",
                                  MANTER_INTEIRO: True})
        # O passo guardado só retoma quando a pessoa autorizou esta tarefa; o de
        # uma tarefa cancelada não pode rodar na seguinte.
        if not _tarefas_residente.retoma_passo_autorizado(tarefa):
            state.tarefa_pendente = None
        from .residentes.cerebro import provedor_do_turno

        _tier = provedor_do_turno(agente.cerebro, _robin_config, settings, na_mesa=sem_historico)
        _ultra_token = use_ultra_provider(_tier) if _tier is not None else None
        # A pasta dele fica visível dentro da pasta de trabalho do Sentury: o que ele
        # grava aparece junto do resto, e gravar fora dela pede liberação.
        from .tools.arquivos import PASTA_FIXADA, raiz_de_trabalho

        pasta_dele = raiz_de_trabalho() / "Residentes" / (agente.nome[:1].upper() + agente.nome[1:])
        pasta_dele.mkdir(parents=True, exist_ok=True)
        _marca_pasta = PASTA_FIXADA.set(str(pasta_dele))
        try:
            with _escopo.vestido(agente, tarefa):
                # O esforço vai só quando o residente tem um; sem ele vale o padrão do provedor.
                esforco = (agente.cerebro or {}).get("esforco")
                if not esforco and sem_historico:
                    from .ajustes import cardapio

                    esforco = str((cardapio().get("mesa") or {}).get("esforco_padrao") or "") or None
                from .residentes.cerebro import ouvir_respostas

                ouvir_respostas()
                result = await orchestrator.handle_message(state, mensagem, **({"effort": esforco} if esforco else {}))
        finally:
            PASTA_FIXADA.reset(_marca_pasta)
            if _ultra_token is not None:
                clear_ultra_provider(_ultra_token)
        for message in reversed(state.history):
            if message.get("role") == "user" and message.get("content") == mensagem:
                message["origem"] = f"tarefa:{tarefa.id}"
                break
        ultima = next((m for m in reversed(state.history) if m.get("role") == "assistant"), None)
        from .residentes.cerebro import respondeu_so_o_ultimo_recurso

        # Resposta do último recurso é aviso de que nenhum modelo respondeu: a tarefa falha
        # com o aviso como motivo, em vez de o aviso virar a resposta (ou a fala na Mesa).
        result["falhou"] = bool(ultima and is_transient_failure_message(ultima)) or respondeu_so_o_ultimo_recurso(_robin_config)
        if result["falhou"]:
            result["erro"] = str((ultima or {}).get("content") or "")[:200]
        _attach_result_to_last_assistant(state, result)
        await _persist_state(state)
        return result


class MencaoRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    user_id: str = Field(..., min_length=1, max_length=128)
    texto: str = Field(..., min_length=1, max_length=8000)


def _origem_da_conversa(user_id: str, session_id: str) -> str:
    return f"conversa:{user_id}:{session_id}"


class MencoesRequest(MencaoRequest):
    nomes: List[str] = Field(..., min_length=1, max_length=8)


def _em_lista(nomes: List[str]) -> str:
    return nomes[0] if len(nomes) == 1 else f"{', '.join(nomes[:-1])} e {nomes[-1]}"


async def _mencionar(nomes: List[str], payload: MencaoRequest) -> Dict[str, Any]:
    """Cada residente recebe a própria tarefa; a conversa guarda uma troca só, com
    a fala da pessoa uma vez. A conversa inteira de cada um fica no chat dele."""
    from .residentes import cliente as _cliente_hq

    origem = _origem_da_conversa(payload.user_id, payload.session_id)
    entregues, avisos, recusas = [], [], []
    for nome in dict.fromkeys(nome.lower() for nome in nomes):
        Nome = nome[:1].upper() + nome[1:]
        try:
            tarefa = await _cliente_hq.pedir(nome, payload.texto, origem)
        except _cliente_hq.HQIndisponivel as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except ValueError as exc:
            recusas.append(f"{Nome} não recebeu: {exc}.")
            continue
        entregues.append((nome, tarefa))
        if tarefa.get("aviso"):
            avisos.append(f"{tarefa['aviso']}.")
    if not entregues:
        raise HTTPException(status_code=422, detail=" ".join(recusas))
    nomes_ok = [nome for nome, _ in entregues]
    quem = _em_lista([nome[:1].upper() + nome[1:] for nome in nomes_ok])
    volta = ("Quando terminarem, eles respondem aqui." if len(nomes_ok) > 1
             else "Quando terminar, ele responde aqui.")
    confirmacao = " ".join([f"Mandei para {quem}.", *avisos, *recusas, volta])
    async with trava_da_sessao.da(payload.session_id):
        _, state = await _load_state(payload.session_id, payload.user_id)
        state.history.append({"role": "user", "mencao": nomes_ok[0], "mencoes": nomes_ok,
                              "content": " ".join(f"@{nome}" for nome in nomes_ok) + f" {payload.texto}"})
        state.history.append({"role": "assistant", "content": confirmacao, "mencao": nomes_ok[0],
                              "mencoes": nomes_ok, "tarefa_residente": entregues[0][1].get("id"),
                              "tarefas_residentes": [tarefa.get("id") for _, tarefa in entregues]})
        await _persist_state(state)
    return {"tarefas": [tarefa for _, tarefa in entregues], "mensagem": confirmacao}


class LevarAMesaRequest(MencaoRequest):
    nomes: List[str] = Field(default_factory=list, max_length=8)
    assunto_id: str = Field(default="", max_length=64)


def _titulo_da_mesa(texto: str) -> str:
    linha = texto.strip().splitlines()[0].strip() if texto.strip() else "Assunto da conversa"
    return linha if len(linha) <= 80 else linha[:79].rstrip() + "…"


@app.post("/sentury/residentes/_levar_a_mesa")
async def levar_a_mesa(payload: LevarAMesaRequest, _: None = Depends(verify_api_token)):
    """A fala vai para a Mesa: num assunto aberto (`assunto_id`) ou num novo, com
    os residentes marcados. A discussão corre na Mesa; o resumo volta aqui."""
    from .residentes import cliente as _cliente_hq

    chamados = " ".join(f"@{nome.lower()}" for nome in dict.fromkeys(payload.nomes))
    texto = f"{chamados} {payload.texto}".strip()
    try:
        if payload.assunto_id:
            assunto = await _cliente_hq.falar_no_assunto(payload.assunto_id, texto)
        else:
            assunto = await _cliente_hq.abrir_assunto(
                _titulo_da_mesa(payload.texto), texto, "pessoa",
                _origem_da_conversa(payload.user_id, payload.session_id))
    except _cliente_hq.HQIndisponivel as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    mesa = {"id": assunto["id"], "titulo": assunto["titulo"]}
    acao = "Falei na Mesa" if payload.assunto_id else "Abri na Mesa"
    confirmacao = (f"{acao}: {assunto['titulo']}. A conversa segue por lá, e o resumo volta "
                   "aqui quando o assunto fechar.")
    async with trava_da_sessao.da(payload.session_id):
        _, state = await _load_state(payload.session_id, payload.user_id)
        state.history.append({"role": "user", "content": texto, "mesa": mesa})
        state.history.append({"role": "assistant", "content": confirmacao, "mesa": mesa})
        await _persist_state(state)
    return {"assunto": assunto, "mensagem": confirmacao}


async def _resumo_da_mesa_na_conversa(assunto) -> None:
    """O assunto que nasceu numa conversa devolve o resumo para ela ao fechar."""
    canal = str(getattr(assunto, "canal", "") or "")
    if not canal.startswith("conversa:"):
        return
    _, user_id, session_id = canal.split(":", 2)
    resumo = getattr(assunto, "resumo", "") or "Fechou sem resumo."
    try:
        async with trava_da_sessao.da(session_id):
            _, state = await _load_state(session_id, user_id)
            state.history.append({"role": "assistant", "content": resumo,
                                  "mesa": {"id": assunto.id, "titulo": assunto.titulo, "resumo": True}})
            await _persist_state(state)
    except Exception:
        logger.warning("Não consegui devolver o resumo da Mesa %s à conversa %s.", assunto.id, session_id,
                       exc_info=True)


@app.post("/sentury/residentes/_mencao")
async def mencionar_residentes(payload: MencoesRequest, _: None = Depends(verify_api_token)):
    """`@alfa @nina` no começo da mensagem, ou o chip "Falando com" com os dois."""
    return await _mencionar(payload.nomes, payload)


@app.post("/sentury/residentes/{nome}/mencao")
async def mencionar_residente(nome: str, payload: MencaoRequest, _: None = Depends(verify_api_token)):
    """`@nome` na conversa: a tarefa vai para a fila do residente e a troca fica
    no histórico. A resposta dele volta para esta mesma conversa quando terminar."""
    corpo = await _mencionar([nome], payload)
    return {"tarefa": corpo["tarefas"][0], "mensagem": corpo["mensagem"]}


class PropostaRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    user_id: str = Field(..., min_length=1, max_length=128)
    argumentos: Dict[str, Any]


@app.put("/sentury/residentes/_proposta")
async def ajustar_proposta(payload: PropostaRequest, _: None = Depends(verify_api_token)):
    """A pessoa ajusta o residente proposto antes de criar. Muda os argumentos
    que a retomada vai executar depois do "Criar"; o manifesto é validado aqui
    para o erro aparecer no cartão, não no turno."""
    from .residentes import manifesto as _manifesto

    async with trava_da_sessao.da(payload.session_id):
        _, state = await _load_state(payload.session_id, payload.user_id)
        pendente = state.tarefa_pendente or {}
        if pendente.get("ferramenta") != "criar_agente":
            raise HTTPException(status_code=409, detail="não há residente proposto esperando nesta conversa")
        argumentos = {**(pendente.get("argumentos") or {}), **payload.argumentos}
        try:
            _manifesto.validar(argumentos)
        except _manifesto.ManifestoInvalido as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        state.tarefa_pendente = {**pendente, "argumentos": argumentos}
        await _persist_state(state)
    return {"argumentos": argumentos}


async def _aviso_do_residente_no_telegram(tarefa) -> None:
    """O residente avisa no Telegram: no chat de onde veio o pedido ou, se ele
    tem o canal Telegram, nos chats autorizados."""
    from .residentes import registro as _registro_residente
    from .residentes import telegram as _residentes_telegram

    if telegram_manager.status not in {"online", "running"}:
        return
    agente = _registro_residente.carregar(tarefa.agente)
    chats = _residentes_telegram.destinos(tarefa, agente.canais if agente else [],
                                          settings.telegram_allowed_id_list)
    texto, botoes = _residentes_telegram.aviso(tarefa)
    for chat in chats:
        await telegram_manager.avisar_residente(chat, texto, botoes)


async def _resposta_do_residente_na_conversa(tarefa) -> None:
    """Quando a tarefa veio de uma menção, a resposta volta para a conversa."""
    if not str(tarefa.origem or "").startswith("conversa:"):
        return
    _, user_id, session_id = tarefa.origem.split(":", 2)
    # A conversa própria já foi persistida pelo worker, sem cópia por usuário.
    if session_id == f"agente:{tarefa.agente}":
        return
    Nome = tarefa.agente[:1].upper() + tarefa.agente[1:]
    if tarefa.estado == "feita":
        texto = (f"**{Nome}** respondeu:\n\n{tarefa.resposta}" if tarefa.resposta
                 else f"{Nome} terminou sem resposta em texto.")
    elif tarefa.estado == "esperando":
        texto = f"{Nome} está esperando você: {tarefa.motivo}. Responda na Sentury HQ."
    else:
        texto = f"{Nome} não conseguiu: {tarefa.motivo or tarefa.estado}."
    try:
        async with trava_da_sessao.da(session_id):
            _, state = await _load_state(session_id, user_id)
            state.history.append({"role": "assistant", "content": texto, "residente": tarefa.agente,
                                  "tarefa_residente": tarefa.id})
            await _persist_state(state)
    except Exception:
        logger.warning("Não consegui devolver a resposta de %s à conversa %s.", tarefa.agente, session_id,
                       exc_info=True)


class GoalAprovarRequest(BaseModel):
    modo: str = Field(default="router", max_length=16)


class GoalRetomarRequest(BaseModel):
    mais_turnos: int = Field(default=0, ge=0, le=1000)


class GoalConfirmarRequest(BaseModel):
    cumprido: bool
    nota: str = Field(default="", max_length=1000)


class GoalMotivoRequest(BaseModel):
    motivo: str = Field(default="", max_length=300)


def _goal_publico(goal) -> Dict[str, Any]:
    return {**goal.publico(), "rodando": executor_de_goal.rodando(goal.id)}


def _goal_ou_erro(acao):
    from .memory import goals as _goals

    try:
        return _goal_publico(acao())
    except _goals.GoalInvalido as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/sentury/goals")
async def listar_goals(session_id: str, _: None = Depends(verify_api_token)):
    """O goal em aberto da conversa (o que a tela mostra) e o historico dela."""
    from .memory import goals as _goals

    aberto = _goals.em_aberto(session_id)
    return {"goal": _goal_publico(aberto) if aberto else None,
            "goals": [_goal_publico(g) for g in _goals.listar(session_id)]}


@app.get("/sentury/missoes")
async def listar_missoes(_: None = Depends(verify_api_token)):
    """As missões desta máquina e quanto falta em cada uma. Só leitura: quem
    abre e fecha unidade é o agente, pela ferramenta `missao`."""
    from .memory import unidades as _unidades

    return {"missoes": _unidades.listar()}


@app.get("/sentury/missoes/{nome}")
async def ver_missao(nome: str, _: None = Depends(verify_api_token)):
    """As unidades de uma missão, na ordem em que entraram."""
    from .memory import unidades as _unidades

    if nome not in {m["missao"] for m in _unidades.listar()}:
        raise HTTPException(status_code=404, detail="missão não encontrada")
    missao = _unidades.Missao(nome)
    return {"missao": {**missao.resumo(), "faltam": len(missao.proximas())}, "unidades": missao.unidades()}


@app.post("/sentury/goals/{goal_id}/aprovar")
async def aprovar_goal(goal_id: str, payload: GoalAprovarRequest, _: None = Depends(verify_api_token)):
    """O "comecar" da pessoa: so aqui o executor liga."""
    from .memory import goals as _goals

    modo = payload.modo if payload.modo in ("ultra", "ultra_max") else "router"
    dados = _goal_ou_erro(lambda: _goals.aprovar(goal_id, modo))
    executor_de_goal.iniciar(goal_id)
    return {"goal": {**dados, "rodando": executor_de_goal.rodando(goal_id)}}


@app.post("/sentury/goals/{goal_id}/pausar")
async def pausar_goal(goal_id: str, payload: GoalMotivoRequest, _: None = Depends(verify_api_token)):
    """Para depois do turno em curso: cortar no meio deixaria o turno sem gravar."""
    from .memory import goals as _goals

    return {"goal": _goal_ou_erro(lambda: _goals.pausar(goal_id, payload.motivo or "pausado por você"))}


@app.post("/sentury/goals/{goal_id}/retomar")
async def retomar_goal(goal_id: str, payload: GoalRetomarRequest, _: None = Depends(verify_api_token)):
    from .memory import goals as _goals

    dados = _goal_ou_erro(lambda: _goals.retomar(goal_id, mais_turnos=payload.mais_turnos)
                          if payload.mais_turnos else _goals.continuar(goal_id))
    executor_de_goal.iniciar(goal_id)
    return {"goal": {**dados, "rodando": executor_de_goal.rodando(goal_id)}}


@app.post("/sentury/goals/{goal_id}/confirmar")
async def confirmar_goal(goal_id: str, payload: GoalConfirmarRequest, _: None = Depends(verify_api_token)):
    """A palavra final. "Nao cumpriu" volta ao trabalho com a nota da pessoa."""
    from .memory import goals as _goals

    dados = _goal_ou_erro(lambda: _goals.confirmar(goal_id, payload.cumprido, payload.nota))
    if not payload.cumprido:
        executor_de_goal.iniciar(goal_id)
    return {"goal": {**dados, "rodando": executor_de_goal.rodando(goal_id)}}


@app.post("/sentury/goals/{goal_id}/abandonar")
async def abandonar_goal(goal_id: str, payload: GoalMotivoRequest, _: None = Depends(verify_api_token)):
    from .memory import goals as _goals

    return {"goal": _goal_ou_erro(lambda: _goals.abandonar(goal_id, payload.motivo or "encerrado por você"))}


@app.post("/sentury/reset")
async def reset(payload: ResetRequest, _: None = Depends(verify_api_token)):
    await session_store.delete(payload.session_id)
    return {"ok": True}


# === Agendador (cron) — jobs que rodam o agente em intervalo e postam no feed ===

class CronUpdateRequest(BaseModel):
    prompt: str
    kind: str
    cron_expr: Optional[str] = None
    interval_sec: Optional[int] = None
    run_at: Optional[str] = None
    metric: Optional[str] = None
    op: Optional[str] = None
    threshold: Optional[float] = None

@app.get("/sentury/cron")
async def cron_list(session_id: Optional[str] = None, _: None = Depends(verify_api_token)):
    """Lista globalmente, ou filtra quando um consumidor pedir uma sessão.
    `metricas` são as que o setor ativo sabe vigiar (o alerta só edita entre elas)."""
    from .domains.do_setor import metricas_vigiaveis
    import asyncio

    from .residentes import cliente as hq_cliente

    jobs = cron_scheduler.list_jobs(session_id)
    if hq_cliente.url_da_hq():
        jobs = [job for job in jobs if not job.get("residente")]
        try:
            donos = await hq_cliente.listar()
            listas = await asyncio.gather(*(hq_cliente.rotinas(dono["nome"]) for dono in donos))
        except hq_cliente.HQIndisponivel as exc:
            raise HTTPException(503, str(exc)) from None
        jobs.extend(job for lista in listas for job in lista.get("rotinas", [])
                    if session_id is None or job.get("session_id") == session_id)
    return {"jobs": jobs, "metricas": metricas_vigiaveis()}


@app.get("/sentury/cron/feed")
async def cron_feed(session_id: str, since: float = 0.0, _: None = Depends(verify_api_token)):
    """Painel faz polling aqui: devolve os resultados agendados novos (ts > since)."""
    return {"items": cron_scheduler.get_feed(session_id, since)}


@app.delete("/sentury/cron/{job_id}")
async def cron_delete(job_id: str, _: None = Depends(verify_api_token)):
    _exigir_job_do_sentury(job_id)
    return {"ok": cron_scheduler.remove_job(job_id)}


def _exigir_job_do_sentury(job_id: str) -> None:
    if cron_scheduler.jobs.get(job_id, {}).get("residente"):
        raise HTTPException(409, "Esta rotina pertence a um residente. Use a ficha dele na HQ.")


@app.post("/sentury/cron/{job_id}/activate")
async def cron_activate(job_id: str, _: None = Depends(verify_api_token)):
    _exigir_job_do_sentury(job_id)
    try:
        job = cron_scheduler.set_active(job_id, True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "job": job}


@app.post("/sentury/cron/{job_id}/pause")
async def cron_pause(job_id: str, _: None = Depends(verify_api_token)):
    _exigir_job_do_sentury(job_id)
    try:
        job = cron_scheduler.set_active(job_id, False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "job": job}


@app.patch("/sentury/cron/{job_id}")
async def cron_update(job_id: str, payload: CronUpdateRequest,
                      _: None = Depends(verify_api_token)):
    _exigir_job_do_sentury(job_id)
    try:
        job = cron_scheduler.update_job(
            job_id,
            prompt=payload.prompt,
            kind=payload.kind,
            cron_expr=payload.cron_expr,
            interval_sec=payload.interval_sec,
            run_at=payload.run_at,
            metric=payload.metric,
            op=payload.op,
            threshold=payload.threshold,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "job": job}


# === Endpoints REST de Gerenciamento de Skills procedurais ===

class MemoriaDoUsuarioRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    texto: str = Field(..., min_length=1, max_length=500)


@app.get("/sentury/memory/usuario")
async def memorias_do_usuario(user_id: str, _: None = Depends(verify_api_token)):
    """O que o Sentury lembra da pessoa, da mais nova para a mais velha, com o
    tipo e a conversa de onde cada uma veio."""
    from .memory.memoria_em_arquivos import idade

    memorias = await user_memory.all(user_id)
    titulos = {}
    if any(m.get("sessao") for m in memorias):
        titulos = {c.get("session_id"): c.get("title") for c in await session_index.list(user_id)}
    return {"memorias": [
        {"id": m.get("id"), "texto": m.get("texto", ""), "ts": m.get("ts"), "idade": idade(m.get("ts")),
         "tipo": m.get("tipo"), "nome": m.get("nome"), "sessao": m.get("sessao"), "conversa": titulos.get(m.get("sessao")) if m.get("sessao") else None}
        for m in reversed(memorias)
    ]}


@app.post("/sentury/memory/usuario")
async def ensinar_memoria(payload: MemoriaDoUsuarioRequest, _: None = Depends(verify_api_token)):
    """A pessoa ensina algo direto pela tela. `guardada` e falso quando ja
    existe uma memoria sobre o mesmo assunto."""
    return {"guardada": await user_memory.remember(payload.user_id, payload.texto)}


@app.post("/sentury/memory/usuario/esquecer")
async def esquecer_memoria_pelo_texto(payload: MemoriaDoUsuarioRequest, _: None = Depends(verify_api_token)):
    """O "Desfazer" do aviso de aprendizado no chat, que só conhece o texto."""
    return {"removida": await user_memory.remove_texto(payload.user_id, payload.texto)}


@app.delete("/sentury/memory/usuario/{mem_id}")
async def apagar_memoria(mem_id: int, user_id: str, _: None = Depends(verify_api_token)):
    if not await user_memory.remove(user_id, mem_id):
        raise HTTPException(status_code=404, detail="Memoria nao encontrada.")
    return {"removida": True}


@app.get("/sentury/memory")
async def memoria(_: None = Depends(verify_api_token)):
    """Estado da memoria durável: onde vive, tamanho e ultimos eventos.

    So o backend local tem journal; o de memoria nao tem o que inspecionar."""
    inspecionar = getattr(session_store, "inspecionar", None)
    if inspecionar is None:
        return {
            "disponivel": False,
            "backend": getattr(session_store, "backend_name", "desconhecido"),
            "motivo": "A inspeção existe apenas no armazenamento local.",
        }
    dados = inspecionar()
    dados["disponivel"] = True
    return dados


@app.get("/sentury/robinbandit")
async def robinbandit_estado(_: None = Depends(verify_api_token)):
    """O que o Robin aprendeu: ordem atual, saude e qualidade por provedor."""
    saude = robin.snapshot()
    from robinbandit.profiles import active_profile_models

    return {
        "backend": getattr(robin, "backend_name", "robinbandit"),
        "providers": [
            {"key": k, **(v if isinstance(v, dict) else {}),
             "quality": (v or {}).get("quality_mean") if isinstance(v, dict) else None}
            for k, v in sorted(saude.items())
        ],
        "profiles": active_profile_models(),
    }


# O resumo historico acima precisa vir antes do mount: assim o contrato exato
# GET /sentury/robinbandit continua existindo, enquanto os demais endpoints do
# Robin ficam em /sentury/robinbandit/*.
app.mount("/sentury/robinbandit", _robinbandit_api, name="robinbandit-api")


@app.get("/sentury/traces")
async def list_traces(limit: int = 50, _: None = Depends(verify_api_token)):
    """Observabilidade camada 2 (local): os últimos traces de turno (generations
    de LLM + spans de ferramenta). Só memória do processo, sem phone-home."""
    from .observability import get_recent_traces
    return {"traces": get_recent_traces(limit)}


@app.get("/sentury/interventions")
async def list_interventions(_: None = Depends(verify_api_token)):
    """Telemetria de INTERVENÇÃO + LATÊNCIA (prevenção por medição). Mostra quantas
    vezes o harness teve que consertar/rejeitar a saída do modelo (bridge SQL,
    coerção HTML, guard de grounding, erro de tool), por tier (flash/pro/auto), e
    um resumo de latência por etapa (classify/planner/responder) — pra saber ONDE
    o tempo vai e quem erra mais. Só memória do processo, sem phone-home."""
    from .observability import get_interventions, get_recent_traces
    # resumo de latência por etapa a partir dos traces recentes
    soma: Dict[str, Dict[str, float]] = {}
    for tr in get_recent_traces(100):
        for g in (tr.get("generations") or []):
            ms = g.get("ms")
            if not isinstance(ms, (int, float)):
                continue
            cell = soma.setdefault(g.get("name") or "?", {"total_ms": 0.0, "n": 0})
            cell["total_ms"] += float(ms)
            cell["n"] += 1
    latencia = {
        nome: {"media_ms": round(c["total_ms"] / c["n"]), "amostras": c["n"]}
        for nome, c in soma.items() if c["n"]
    }
    return {"interventions": get_interventions(), "latencia_por_etapa": latencia}


class PdfRenderRequest(BaseModel):
    markdown: str
    title: Optional[str] = "Documento"
    filename: Optional[str] = "documento.pdf"


@app.post("/sentury/render/pdf")
async def render_pdf_direct(payload: PdfRenderRequest, _: None = Depends(verify_api_token)):
    """Converte um markdown JÁ PRONTO (ex.: plano de ação) em PDF de forma
    DETERMINÍSTICA (fpdf2), sem LLM e sem gastar token. É o que o botão
    'Exportar PDF' do card usa — o plano já existe, não precisa gerar de novo."""
    from fastapi.responses import Response
    from .renderers.pdf import markdown_para_pdf
    md = (payload.markdown or "").strip()
    if not md:
        raise HTTPException(status_code=400, detail="markdown vazio")
    try:
        pdf_bytes = markdown_para_pdf(md, payload.title or "Documento")
    except Exception as exc:
        logger.warning("Falha ao renderizar PDF direto: %s", exc)
        raise HTTPException(status_code=500, detail="falha ao gerar PDF")
    fname = payload.filename or "documento.pdf"
    if not fname.lower().endswith(".pdf"):
        fname += ".pdf"
    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


class AcaoFromPlanRequest(BaseModel):
    markdown: str
    title: Optional[str] = "Plano de Ação"


@app.get("/sentury/acoes")
async def list_acoes(status: Optional[str] = None, _: None = Depends(verify_api_token)):
    """Lista as ações corretivas (tabela acoes_corretivas) pra página Tasks."""
    try:
        acoes = await data_store.listar_acoes(status=status)
    except Exception as exc:
        logger.warning("Falha ao listar ações: %s", exc)
        acoes = []
    return {"acoes": acoes}


class AcaoUpdateRequest(BaseModel):
    descricao: Optional[str] = None
    status: Optional[str] = None
    responsavel: Optional[str] = None
    prazo: Optional[str] = None
    prioridade: Optional[str] = None


@app.patch("/sentury/acoes/{acao_id}")
async def update_acao(acao_id: str, payload: AcaoUpdateRequest, _: None = Depends(verify_api_token)):
    """Atualiza uma ação (ex.: marcar item do checklist como feito → descricao +
    status). Grava direto em acoes_corretivas, sem token."""
    campos = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not campos:
        raise HTTPException(status_code=400, detail="nada para atualizar")
    try:
        acao = await data_store.atualizar_acao(acao_id, campos)
    except Exception as exc:
        logger.warning("Falha ao atualizar ação %s: %s", acao_id, exc)
        raise HTTPException(status_code=500, detail="falha ao atualizar")
    return {"acao": acao}


@app.post("/sentury/acoes/from-plan")
async def create_acao_from_plan(payload: AcaoFromPlanRequest, _: None = Depends(verify_api_token)):
    """Envia um plano de ação JÁ PRONTO pro Tasks — grava direto em acoes_corretivas,
    sem gastar token. O plano vira UMA ação (titulo + descricao markdown, origem=plano)."""
    md = (payload.markdown or "").strip()
    if not md:
        raise HTTPException(status_code=400, detail="markdown vazio")
    titulo = (payload.title or "Plano de Ação").strip()[:200]
    try:
        acao = await data_store.criar_acao({
            "titulo": titulo,
            "descricao": md[:8000],
            "origem": "plano-de-acao",
            "status": "Aberta",
        })
    except Exception as exc:
        logger.warning("Falha ao criar ação do plano: %s", exc)
        raise HTTPException(status_code=500, detail="falha ao enviar pro Tasks")
    return {"acao": acao}


@app.get("/sentury/skills")
async def list_skills(_: None = Depends(verify_api_token)):
    """Lista o índice compacto de todas as skills compatíveis."""
    skills_index = orchestrator.skill_discovery.get_available_skills()
    result = []
    for s in skills_index:
        telemetry = orchestrator.skill_usage_tracker.get_record(s.name)
        result.append({
            "removivel": (orchestrator.user_skills_dir / s.name).is_dir(),
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "family": s.family,
            "priority": s.priority,
            "tags": s.tags,
            "tools_used": s.tools_used,
            "telemetry": telemetry
        })
    return {"skills": result}


@app.get("/sentury/skills/{name}")
async def get_skill(name: str, _: None = Depends(verify_api_token)):
    """Lê as informações completas (SKILL.md) de uma skill."""
    skill = orchestrator.skill_loader.load_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill não localizada.")
    
    telemetry = orchestrator.skill_usage_tracker.get_record(name)
    return {
        "name": skill.metadata.name,
        "description": skill.metadata.description,
        "category": skill.metadata.category,
        "family": skill.metadata.family,
        "priority": skill.metadata.priority,
        "tags": skill.metadata.tags,
        "version": skill.metadata.version,
        "body": skill.body,
        "available_references": skill.available_references,
        "removivel": (orchestrator.user_skills_dir / skill.metadata.name).is_dir(),
        "telemetry": telemetry
    }


@app.post("/sentury/skills")
async def create_skill(payload: SkillCreateRequest, _: None = Depends(verify_api_token)):
    """Cria uma nova skill escrevendo fisicamente o diretório e o SKILL.md."""
    name_slug = payload.name.strip().lower().replace(" ", "-")
    target_dir = orchestrator.user_skills_dir / name_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    
    md_file = target_dir / "SKILL.md"
    try:
        md_file.write_text(payload.content, encoding="utf-8")
        # Inicia a telemetria
        orchestrator.skill_usage_tracker.bump_use(name_slug, success=True, is_agent_created=False)
        return {"ok": True, "name": name_slug}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao gravar arquivo procedural: {e}")


class SkillImportRequest(BaseModel):
    """Skill baixada de fora: o SKILL.md e, opcionalmente, arquivos de apoio."""
    name: str = Field(..., min_length=1, max_length=80)
    content: str = Field(..., min_length=1, max_length=400_000)
    arquivos: List[Dict[str, str]] = Field(default_factory=list, max_length=30)


@app.post("/sentury/skills/import")
async def import_skill(payload: SkillImportRequest, _: None = Depends(verify_api_token)):
    """Instala uma skill vinda de fora, com os arquivos que a acompanham."""
    slug = payload.name.strip().lower().replace(" ", "-")
    if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail="nome invalido")

    destino = orchestrator.user_skills_dir / slug
    if destino.exists():
        raise HTTPException(status_code=409, detail=f"ja existe uma skill chamada {slug}")

    try:
        destino.mkdir(parents=True)
        (destino / "SKILL.md").write_text(payload.content, encoding="utf-8")
        gravados = []
        for item in payload.arquivos:
            relativo = str(item.get("caminho") or "").strip().lstrip("/\\")
            # Nada de subir na arvore: o pacote so escreve dentro da propria skill.
            if not relativo or ".." in pathlib.PurePosixPath(relativo).parts:
                continue
            arquivo = destino / relativo
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(str(item.get("conteudo") or ""), encoding="utf-8")
            gravados.append(relativo)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"falha ao importar: {exc}") from exc

    orchestrator.skill_usage_tracker.bump_use(slug, success=True, is_agent_created=False)
    return {"ok": True, "name": slug, "arquivos": gravados}


@app.post("/sentury/skills/{name}")
async def update_skill(name: str, payload: SkillUpdateRequest, _: None = Depends(verify_api_token)):
    """Salva modificações no corpo da skill."""
    skill = orchestrator.skill_loader.load_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill não localizada.")

    md_file = skill.path / "SKILL.md"
    try:
        md_file.write_text(payload.content, encoding="utf-8")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao atualizar arquivo procedural: {e}")


@app.post("/sentury/skills/{name}/desfazer")
async def desfazer_skill(name: str, _: None = Depends(verify_api_token)):
    """O "desfazer" do aviso de aprendizado no chat: volta a última escrita do agente na skill."""
    from .skills.escrita import desfazer

    resultado = desfazer(name)
    if resultado.get("erro"):
        raise HTTPException(status_code=404, detail=resultado["erro"])
    return resultado


@app.delete("/sentury/skills/{name}")
async def delete_skill(name: str, _: None = Depends(verify_api_token)):
    """Remove uma skill do usuario, arquivando antes de apagar.

    So mexe no diretorio de skills do usuario: as que vem com o Sentury sao
    parte da instalacao e nao se apagam pela interface.
    """
    import shutil

    slug = str(name or "").strip().lower()
    if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail="nome invalido")

    alvo = orchestrator.user_skills_dir / slug
    if not alvo.is_dir():
        skill = orchestrator.skill_loader.load_skill(slug)
        if skill is not None:
            raise HTTPException(
                status_code=403,
                detail="esta skill faz parte da instalacao; so skills do usuario podem ser removidas",
            )
        raise HTTPException(status_code=404, detail="skill nao localizada")

    arquivo = orchestrator.user_skills_dir / ".arquivadas" / slug
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        if arquivo.exists():
            shutil.rmtree(arquivo)
        # Arquivar antes de apagar: remover skill nao pode ser irreversivel.
        shutil.move(str(alvo), str(arquivo))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"falha ao remover: {exc}") from exc

    try:
        orchestrator.skill_usage_tracker.set_pinned(slug, False)
    except Exception:
        pass
    return {"ok": True, "name": slug, "arquivada_em": str(arquivo)}


@app.post("/sentury/skills/{name}/pin")
async def pin_skill(name: str, payload: PinRequest, _: None = Depends(verify_api_token)):
    """Altera o pino de proteção contra inatividade da skill."""
    orchestrator.skill_usage_tracker.set_pinned(name, payload.pinned)
    return {"ok": True, "pinned": payload.pinned}


@app.post("/sentury/skills/curator/run")
async def run_curator_manual(_: None = Depends(verify_api_token)):
    """Dispara a limpeza de inatividade e consolidação de rotinas imediatamente."""
    res = curator.run_curator(stale_days=30, archive_days=90, dry_run=False)
    return {"ok": True, "curator_report": res}


class TelegramConfigRequest(BaseModel):
    token: Optional[str] = Field(default=None, max_length=256)
    active: bool
    allowed_ids: Optional[str] = None


@app.get("/sentury/telegram/status")
async def get_telegram_status(_: None = Depends(verify_api_token)):
    """Busca o status sem devolver nenhum fragmento do token do bot."""
    token = telegram_manager.current_token or settings.TELEGRAM_TOKEN
    return {
        "status": telegram_manager.status,
        "configured": bool(token),
        "allowed_ids": settings.TELEGRAM_ALLOWED_IDS
    }


@app.post("/sentury/telegram/config")
async def post_telegram_config(payload: TelegramConfigRequest, _: None = Depends(verify_api_token)):
    """Atualiza as configurações do Telegram e liga/desliga o Long Polling."""
    return _aplicar_config_telegram(payload)


def _aplicar_config_telegram(payload: TelegramConfigRequest) -> Dict[str, Any]:
    next_token = (payload.token or "").strip() or telegram_manager.current_token or settings.TELEGRAM_TOKEN or ""
    if payload.active and not next_token:
        raise HTTPException(status_code=400, detail="token do Telegram ausente")

    settings.TELEGRAM_TOKEN = next_token
    settings.TELEGRAM_BOT_ACTIVE = payload.active
    settings.TELEGRAM_ALLOWED_IDS = payload.allowed_ids
    
    # Grava no .env para persistência
    import pathlib
    env_path = pathlib.Path(".env")
    try:
        content = ""
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
        
        lines = content.splitlines()
        new_lines = []
        token_found = False
        active_found = False
        allowed_found = False
        
        for line in lines:
            if line.startswith("TELEGRAM_TOKEN="):
                new_lines.append(f"TELEGRAM_TOKEN={next_token}")
                token_found = True
            elif line.startswith("TELEGRAM_BOT_ACTIVE="):
                new_lines.append(f"TELEGRAM_BOT_ACTIVE={str(payload.active).lower()}")
                active_found = True
            elif line.startswith("TELEGRAM_ALLOWED_IDS="):
                new_lines.append(f"TELEGRAM_ALLOWED_IDS={payload.allowed_ids or ''}")
                allowed_found = True
            else:
                new_lines.append(line)
                
        if not token_found:
            new_lines.append(f"TELEGRAM_TOKEN={next_token}")
        if not active_found:
            new_lines.append(f"TELEGRAM_BOT_ACTIVE={str(payload.active).lower()}")
        if not allowed_found:
            new_lines.append(f"TELEGRAM_ALLOWED_IDS={payload.allowed_ids or ''}")
            
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.error("Falha ao salvar token Telegram no .env: %s", e)

    if payload.active:
        telegram_manager.start(next_token)
    else:
        telegram_manager.stop()

    return {"ok": True, "status": telegram_manager.status}


def _voz_disponivel() -> Dict[str, Any]:
    try:
        import google.genai  # noqa: F401
        tem_lib = True
    except Exception:
        tem_lib = False
    tem_chave = bool(get_gemini_live_api_key())
    return {
        "available": tem_chave and tem_lib,
        "configured": tem_chave and tem_lib,
        "status": "pronto" if (tem_chave and tem_lib) else "indisponivel",
        "motivo": None if (tem_chave and tem_lib) else (
            "Nenhum modelo com áudio bidirecional configurado." if not tem_chave
            else "Biblioteca do provedor de voz não instalada."
        ),
        "model": escolha_de_voz()["modelo"] or settings.GEMINI_LIVE_MODEL,
    }


class McpServerRequest(BaseModel):
    """Servidor MCP. Guarda o NOME da variavel de ambiente, nunca o valor."""
    id: Optional[str] = Field(default=None, max_length=64)
    nome: str = Field(..., min_length=1, max_length=80)
    transporte: str = Field(default="stdio", max_length=10)
    comando: Optional[str] = Field(default=None, max_length=400)
    args: List[str] = Field(default_factory=list, max_length=30)
    url: Optional[str] = Field(default=None, max_length=500)
    env_vars: List[str] = Field(default_factory=list, max_length=20)
    ativo: bool = True


@app.get("/sentury/mcp")
async def listar_mcp(_: None = Depends(verify_api_token)):
    """Servidores registrados, com o nome das variaveis e se elas existem."""
    saida = []
    for servidor in mcp_registry.listar():
        saida.append({
            **servidor,
            "env_presentes": {
                nome: bool(os.environ.get(nome)) for nome in servidor.get("env_vars", [])
            },
        })
    return {"servidores": saida, "config": str(mcp_registry.caminho_da_config())}


@app.post("/sentury/mcp")
async def salvar_mcp(payload: McpServerRequest, _: None = Depends(verify_api_token)):
    try:
        return {"ok": True, "servidor": mcp_registry.salvar(payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/sentury/mcp/{servidor_id}")
async def remover_mcp(servidor_id: str, _: None = Depends(verify_api_token)):
    try:
        removido = mcp_registry.remover(servidor_id)
    except ValueError as exc:
        # Servidor de pacote: existe, aparece na lista e nao se remove daqui.
        # 404 diria "nao encontrado" para algo que esta na tela.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removido:
        raise HTTPException(status_code=404, detail="servidor nao registrado")
    return {"ok": True, "id": servidor_id}


@app.post("/sentury/mcp/{servidor_id}/inspecionar")
async def inspecionar_mcp(servidor_id: str, _: None = Depends(verify_api_token)):
    """Conecta de verdade, le o catalogo de ferramentas e desliga."""
    servidor = mcp_registry.obter(servidor_id)
    if servidor is None:
        raise HTTPException(status_code=404, detail="servidor nao registrado")
    return await mcp_registry.inspecionar(servidor)


# Ultima execucao das evals, para a tela nao comecar vazia a cada visita.
_ULTIMAS_EVALS: Dict[str, Any] = {}


@app.get("/sentury/evals")
async def listar_evals(_: None = Depends(verify_api_token)):
    """Casos golden do setor ativo e o resultado da ultima execucao. As evals de
    um setor so aparecem com ele ligado: o generalista nao ve as do CX."""
    from .domains import get_active_domain
    from .evals.golden import casos_do_setor

    casos = [
        {
            "nome": caso.__name__.replace("_eval_", "").replace("_", " "),
            "funcao": caso.__name__,
            "descricao": (caso.__doc__ or "").strip().splitlines()[0] if caso.__doc__ else "",
        }
        for caso in casos_do_setor(get_active_domain().name)
    ]
    return {"casos": casos, "setor": get_active_domain().name, "ultima_execucao": _ULTIMAS_EVALS or None}


@app.post("/sentury/evals/run")
async def rodar_evals(_: None = Depends(verify_api_token)):
    """Roda as evals do setor ativo. Deterministica: nao chama LLM real."""
    from .domains import get_active_domain
    from .evals.golden import casos_do_setor, run_golden_evals

    _CASES = casos_do_setor(get_active_domain().name)
    inicio = _time.time()
    resultados = await run_golden_evals(_CASES)
    payload = {
        "quando": _time.time(),
        "ms": int((_time.time() - inicio) * 1000),
        "total": len(resultados),
        "passaram": sum(1 for r in resultados if r.ok),
        # A ordem e a mesma de `_CASES`, entao a tela casa resultado e caso pela
        # funcao em vez de tentar adivinhar pelo texto do nome.
        "resultados": [
            {
                "nome": r.nome,
                "funcao": _CASES[i].__name__ if i < len(_CASES) else "",
                "ok": bool(r.ok),
                "detalhe": str(r.detalhe)[:600],
            }
            for i, r in enumerate(resultados)
        ],
    }
    _ULTIMAS_EVALS.clear()
    _ULTIMAS_EVALS.update(payload)
    return payload


class RestaurarRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    # Indice da mensagem no historico visivel; tudo dali para frente sai.
    indice: int = Field(..., ge=0)


@app.get("/sentury/sessions/{session_id}/checkpoints")
async def listar_checkpoints(
    session_id: str,
    user_id: str,
    _: None = Depends(verify_api_token),
):
    """Pontos aos quais da para voltar: cada turno do usuario e um deles.

    Mostra tambem o que ficou pela metade: passo que comecou e nao fechou
    aparece como interrompido, que e a pergunta de quem volta ao historico.
    """
    _, state = await _load_state(session_id, user_id)
    if state is None:
        raise HTTPException(status_code=404, detail="sessao nao encontrada")

    pontos = []
    for indice, mensagem in enumerate(state.history):
        if mensagem.get("role") != "user":
            continue
        # Entre a pergunta e a resposta ha andaime interno (`system`); a
        # resposta e a proxima mensagem do assistente, nao a proxima linha.
        seguinte = next(
            (m for m in state.history[indice + 1:] if m.get("role") in ("assistant", "user")),
            None,
        )
        if seguinte is not None and seguinte.get("role") != "assistant":
            seguinte = None
        processo = (seguinte or {}).get("processo") or []
        inacabados = [p.get("titulo") for p in processo if p.get("status") == "running"]
        pontos.append({
            "indice": indice,
            "texto": str(mensagem.get("content") or "")[:200],
            "respondido": bool(seguinte and seguinte.get("role") == "assistant"),
            "passos": len(processo),
            "interrompidos": [t for t in inacabados if t],
        })
    return {"checkpoints": pontos, "total_mensagens": len(state.history)}


@app.post("/sentury/sessions/{session_id}/restaurar")
async def restaurar_checkpoint(
    session_id: str,
    payload: RestaurarRequest,
    _: None = Depends(verify_api_token),
):
    """Volta a conversa a um ponto: o que veio depois e descartado."""
    _, state = await _load_state(session_id, payload.user_id)
    if state is None:
        raise HTTPException(status_code=404, detail="sessao nao encontrada")
    if payload.indice >= len(state.history):
        raise HTTPException(status_code=400, detail="indice fora do historico")

    removidas = len(state.history) - payload.indice
    state.history = state.history[: payload.indice]
    state_dict = await _persist_state(state)
    return {"ok": True, "removidas": removidas, "state": state_dict}


@app.get("/sentury/escada")
async def medidor_da_escada(dias: int = 30, _: None = Depends(verify_api_token)):
    """Leituras de pagina: quantas foram texto e quantas print, por site, por
    dia e por conversa. `parcela_print` e o numero que a escada tem que baixar."""
    from .memory.estrategia import resumo_da_escada

    return resumo_da_escada(max(1, min(int(dias), 365)))


@app.get("/sentury/memory/sessions")
async def memoria_por_sessao(
    session_id: Optional[str] = None,
    _: None = Depends(verify_api_token),
):
    """Camada 2: journal por sessao, organizado por data.

    Com `session_id`, devolve os eventos daquela sessao; sem ele, os dias que
    tem sessao registrada.
    """
    store = getattr(session_store, "local", None) or session_store
    if not hasattr(store, "sessoes_por_dia"):
        return {"disponivel": False, "motivo": "backend de sessao nao e o local"}
    if session_id:
        eventos = store.eventos_da_sessao(session_id)
        return {
            "disponivel": True,
            "session_id": session_id,
            "total": len(eventos),
            "eventos": [
                {"seq": e.get("seq"), "type": e.get("type"), "time": e.get("time")}
                for e in eventos
            ],
        }
    return {"disponivel": True, "dias": store.sessoes_por_dia()}


class EscopoRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)


@app.delete("/sentury/sessions/{session_id}/escopo")
async def limpar_escopo(
    session_id: str,
    user_id: str,
    _: None = Depends(verify_api_token),
):
    """Zera os filtros da sessao sem gastar um turno de LLM.

    Antes o botao de limpar mandava a frase "limpar filtros" pelo chat: o
    pipeline inteiro rodava (classificador, planner, ferramenta e resposta)
    para esvaziar um dicionario.
    """
    _, state = await _load_state(session_id, user_id)
    if state is None:
        raise HTTPException(status_code=404, detail="sessao nao encontrada")
    anteriores = dict(state.filtros or {})
    state.filtros = {}
    state_dict = await _persist_state(state)
    return {"ok": True, "removidos": anteriores, "state": state_dict}


class PermissaoRequest(BaseModel):
    """Resposta do dono da maquina a um comando que altera alguma coisa.

    O comando pode ser longo: `escrever_arquivo` carrega o conteudo inteiro
    junto. Com o limite em 500 o pedido voltava 422 e nenhum botao da folha de
    autorizacao funcionava.
    """
    comando: str = Field(..., min_length=1, max_length=20000)
    resposta: str = Field(..., max_length=16)
    session_id: Optional[str] = Field(default=None, max_length=128)


class NavegadorRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)


@app.post("/sentury/navegador/mostrar")
async def mostrar_navegador(payload: NavegadorRequest, _: None = Depends(verify_api_token)):
    """Traz a janela do navegador da conversa para a frente."""
    from .tools.browser_registry import trazer_para_frente

    return {"ok": await trazer_para_frente(payload.session_id)}


@app.post("/sentury/navegador/estado")
async def estado_navegador(payload: NavegadorRequest, _: None = Depends(verify_api_token)):
    from .tools.browser_registry import esta_aberta

    return {"aberta": esta_aberta(payload.session_id)}


@app.post("/sentury/navegador/extensao/codigo")
async def codigo_da_extensao(_: None = Depends(verify_api_token)):
    from .tools.browser_chrome_bridge import ponte_chrome

    return ponte_chrome.codigo_de_pareamento()


@app.get("/sentury/navegador/extensao/estado")
async def estado_da_extensao(_: None = Depends(verify_api_token)):
    from .tools.browser_chrome_bridge import ponte_chrome

    return {"conectada": ponte_chrome.conectada}


@app.post("/sentury/navegador/extensao/nova-aba")
async def nova_aba_da_extensao(payload: NavegadorRequest, _: None = Depends(verify_api_token)):
    from .tools.browser_chrome_bridge import ponte_chrome

    if not ponte_chrome.conectada:
        raise HTTPException(status_code=503, detail="extensão do Chrome não conectada")
    try:
        return await ponte_chrome.chamar("reset", payload.session_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.websocket("/sentury/navegador/extensao/ws")
async def websocket_da_extensao(socket: WebSocket):
    from .tools.browser_chrome_bridge import ponte_chrome

    await ponte_chrome.atender(socket)


@app.post("/sentury/navegador/tato")
async def navegador_pelo_tato(pedido: Dict[str, Any] = Body(...), x_tato_segredo: Optional[str] = Header(None)):
    """O servidor MCP do Tato, em outro processo, usa a extensão por aqui."""
    import hmac

    from .tools.browser_chrome_bridge import ponte_chrome, segredo_do_tato

    if not x_tato_segredo or not hmac.compare_digest(x_tato_segredo, segredo_do_tato()):
        raise HTTPException(status_code=401, detail="segredo do Tato inválido")
    return await ponte_chrome.pelo_tato(pedido)


@app.post("/sentury/navegador/encerrar")
async def encerrar_navegador(payload: NavegadorRequest, _: None = Depends(verify_api_token)):
    from .tools.browser_registry import encerrar

    return {"ok": True, "encerradas": encerrar(payload.session_id)}


@app.post("/sentury/computador/estado")
async def estado_computador(payload: NavegadorRequest, _: None = Depends(verify_api_token)):
    from .tools import computador_vez
    from .tools.computador import sessao_ativa

    return {"aberta": sessao_ativa(payload.session_id), "vez": computador_vez.publica(computador_vez.atual())}


@app.post("/sentury/computador/encerrar")
async def encerrar_computador(payload: NavegadorRequest, _: None = Depends(verify_api_token)):
    from .tools.computador import encerrar_sessao

    return {"ok": True, "encerrada": encerrar_sessao(payload.session_id)}


@app.post("/sentury/computador/assumir")
async def assumir_computador(payload: NavegadorRequest, _: None = Depends(verify_api_token)):
    """A vez vai para a pessoa: o turno que usa o computador para e nada mais o toca até ela devolver."""
    from .tools.computador import assumir

    return {"ok": True, "vez": assumir(payload.session_id)}


@app.post("/sentury/computador/devolver")
async def devolver_computador(payload: NavegadorRequest, _: None = Depends(verify_api_token)):
    from .tools.computador import devolver

    return {"ok": True, "vez": devolver()}


@app.get("/sentury/permissoes")
async def listar_permissoes(_: None = Depends(verify_api_token)):
    """O que o agente pode fazer hoje, e onde isso esta registrado."""
    from .tools.permissoes import estado
    from .tools.shell import ambiente

    dados = estado()
    dados["ambiente"] = {**ambiente(), "shell_ligado": bool(settings.SENTURY_SHELL)}
    return dados


@app.post("/sentury/permissoes")
async def responder_permissao(payload: PermissaoRequest, _: None = Depends(verify_api_token)):
    from .tools.permissoes import responder

    try:
        resposta = responder(payload.comando, payload.resposta, payload.session_id or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _retomar_goal_da_permissao(payload.session_id or "", payload.resposta)
    return resposta


def _retomar_goal_da_permissao(session_id: str, escolha: str) -> None:
    """O goal parou porque um passo pedia autorizacao. Liberou: ele continua
    sozinho, sem a pessoa precisar achar o botao. Negou: fica parado, e a
    pessoa decide se ele segue por outro caminho."""
    from .memory import goals as _goals

    goal = _goals.em_aberto(session_id) if session_id else None
    if goal is None or goal.estado != _goals.PAUSADO or goal.pausado_por != "permissao":
        return
    if str(escolha).strip().lower() in ("sempre", "sessao", "uma_vez"):
        _goals.retomar(goal.id)
        executor_de_goal.iniciar(goal.id)


@app.post("/sentury/permissoes/permitir-tudo")
async def permitir_tudo(
    ligado: bool = Body(embed=True),
    _: None = Depends(verify_api_token),
):
    """Modo sem interrupcao. Explicito de proposito: permissao que se liga sem
    querer nao e permissao."""
    from .tools.permissoes import definir_permitir_tudo

    return definir_permitir_tudo(ligado)


@app.delete("/sentury/permissoes/{chave}")
async def esquecer_permissao(chave: str, _: None = Depends(verify_api_token)):
    from .tools.permissoes import esquecer

    return esquecer(chave)


@app.get("/sentury/channels")
async def get_channels(_: None = Depends(verify_api_token)):
    """Catálogo de canais com o estado real de cada um."""
    token = telegram_manager.current_token or settings.TELEGRAM_TOKEN
    estados = {
        "web": {"available": True, "configured": True, "status": "online"},
        "telegram": {
            "available": True,
            "configured": bool(token),
            "status": telegram_manager.status,
            "active": telegram_manager.status in {"online", "running"},
            "values": {"allowed_ids": settings.TELEGRAM_ALLOWED_IDS or ""},
        },
        "voz": _voz_disponivel(),
    }
    return {"canais": channel_catalog(estados)}


@app.post("/sentury/channels/{canal_id}/config")
async def post_channel_config(
    canal_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    _: None = Depends(verify_api_token),
):
    """Aplica a configuração de um canal. Cada canal tem o próprio formato."""
    canal = channel_declaration(canal_id)
    if canal is None:
        raise HTTPException(status_code=404, detail=f"canal desconhecido: {canal_id}")
    if not canal.get("configurable"):
        raise HTTPException(status_code=400, detail=f"canal {canal_id} não tem configuração")

    if canal_id == "telegram":
        resultado = _aplicar_config_telegram(TelegramConfigRequest(
            token=payload.get("token"),
            active=bool(payload.get("active")),
            allowed_ids=payload.get("allowed_ids"),
        ))
        return {"ok": True, "canal": canal_id, "status": resultado.get("status")}

    raise HTTPException(status_code=501, detail=f"canal {canal_id} ainda não aplica configuração")


# === Interface (mesma origem — sem CORS, sem segundo servidor) ===
# Montada por último para não sombrear as rotas de API.
#
# Serve o build do client na mesma origem da API.
from pathlib import Path as _Path
from fastapi.staticfiles import StaticFiles
import robinbandit as _robinbandit_package
from .harness.artefato_do_turno import tirar_html_repetido

class _EstaticoDaInterface(StaticFiles):
    """Arquivo com hash no nome pode ser cacheado para sempre; o `index.html`,
    nunca.

    O Vite gera `index-BIJBDF5o.js` — o nome muda a cada build, entao cache
    eterno neles e seguro e desejavel. Ja o `index.html` tem nome fixo e e ele
    que aponta para os outros: cacheado, o navegador continua pedindo os
    arquivos da versao ANTIGA depois de um deploy, e a tela quebra com 404 em
    coisas que nao existem mais.
    """

    async def get_response(self, path: str, scope):
        resposta = await super().get_response(path, scope)
        # Pelo tipo, não pelo caminho: o Starlette normaliza `/` para `.` antes
        # de chegar aqui, e comparar string erraria justamente no caso que mais
        # importa — a raiz.
        tipo = str(resposta.headers.get("content-type", ""))
        if tipo.startswith("text/html"):
            resposta.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif "assets" in str(path).replace("\\", "/").split("/"):
            resposta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resposta


_client_dir = _Path(__file__).resolve().parent / "client" / "dist"
_provider_logos_dir = _Path(_robinbandit_package.__file__).resolve().parent / "assets" / "providers"
if _provider_logos_dir.is_dir():
    app.mount("/provider-logos", StaticFiles(directory=str(_provider_logos_dir)), name="provider-logos")
if _client_dir.is_dir():
    app.mount("/", _EstaticoDaInterface(directory=str(_client_dir), html=True), name="client")
    logger.info("Interface servida em / a partir de %s", _client_dir)
else:
    logger.warning(
        "Interface não encontrada em %s — rode `npm run build` em sentury/client. "
        "A API continua respondendo normalmente.", _client_dir,
    )
