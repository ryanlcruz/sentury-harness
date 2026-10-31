import os
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from .exec.logs import instalar_redacao

instalar_redacao()


class Settings(BaseSettings):
    def model_post_init(self, context):
        from .exec.segredos import registrar_configuracao

        registrar_configuracao({nome: getattr(self, nome) for nome in type(self).model_fields})

    def __repr_args__(self):
        # Exceções e logs podem representar o objeto; credenciais não entram ali.
        return [("APP_NAME", self.APP_NAME), ("ENVIRONMENT", self.ENVIRONMENT)]

    def __setattr__(self, nome, valor):
        super().__setattr__(nome, valor)
        from .exec.segredos import chave_sensivel, registrar_configuracao

        if chave_sensivel(nome):
            registrar_configuracao({nome: valor})

    APP_NAME: str = "Sentury"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = Field(default="development")

    # O gateway de provedores é o projeto plugável RobinBandit.
    SENTURY_ROBINBANDIT_CONFIG: str = Field(
        default="sentury/plugins/robinbandit/config/sentury.yaml"
    )
    SENTURY_AUXILIARY_ROUTE: str = Field(default="auxiliar")

    OPENROUTER_API_KEY: Optional[str] = Field(default=None)
    # Listas vazias significam "usar o catálogo YAML do RobinBandit". O env
    # continua podendo sobrescrever qualquer lista por deploy.
    OPENROUTER_MODELS: str = Field(default="")

    # --- Reforçado (id legado: ultra) — seleção híbrida por request ---
    # Tenta primeiro o alvo fixado e, em falha/cota, entrega a decisão ao Router.
    API_KEY_ULTRA: Optional[str] = Field(default=None)
    # Aceita 1 modelo ou CSV (o Ultra tenta na ordem antes de cascatear pra cadeia).
    ULTRA_MODEL: str = Field(default="")
    # Endpoint OpenAI-compatible que serve o ULTRA_MODEL. Default: OpenRouter (o id
    # "openai/gpt-oss-120b" segue o padrão de nomes deles). Troque para Groq/etc.
    ULTRA_BASE_URL: str = Field(default="")

    # --- Dedicado (id legado: ultra_max) — seleção estrita por request ---
    # Usa somente o alvo escolhido. Em falha/cota, a chamada termina sem Router.
    # A CHAVE e o BASE_URL caem no do Ultra quando vazios (mesma conta OpenRouter, só
    # o modelo muda) — basta setar ULTRA_MAX_MODEL no .env.
    ULTRA_MAX_MODEL: str = Field(default="")
    API_KEY_ULTRA_MAX: Optional[str] = Field(default=None)
    ULTRA_MAX_BASE_URL: Optional[str] = Field(default=None)

    GROQ_API_KEY: Optional[str] = Field(default=None)
    # Responder ("groq responde"): modelo rápido para redigir a resposta final.
    GROQ_MODELS: str = Field(default="")
    # Planner ("pensa/decide ações"): por padrão usa o qwen3-32b (raciocínio) —
    # cruzar fontes e montar causa-raiz pede mais raciocínio que
    # só redigir a resposta final.
    GROQ_PLANNER_MODELS: str = Field(default="")

    # ChatGPT Codex não usa API key do Sentury: o adaptador Robin delega OAuth
    # e renovação ao `codex app-server`, autenticado previamente por `codex login`.
    CODEX_BINARY: str = Field(default="codex")
    CHATGPT_CODEX_MODELS: str = Field(default="")

    GEMINI_API_KEY: Optional[str] = Field(default=None)
    GEMINI_MODELS: str = Field(default="")
    # Modelo da ligação por voz (Gemini Live). Half-cascade = bom uso de tools.
    GEMINI_LIVE_MODEL: str = Field(default="gemini-3.1-flash-live-preview")

    # --- Provedores extras OpenAI-compatible (multi-provider) ---
    # Todos falam o mesmo formato (OpenAI Chat Completions); o que muda é a URL
    # base (declarada no YAML Robin), a chave e a lista
    # de modelos. Entram na cadeia como fallback ANTES do FallbackProvider demo,
    # ampliando o "runway" gratuito quando Groq/Gemini/OpenRouter batem cota.
    GITHUB_MODELS_API_KEY: Optional[str] = Field(default=None)
    GITHUB_MODELS_MODELS: str = Field(default="")

    CEREBRAS_API_KEY: Optional[str] = Field(default=None)
    CEREBRAS_MODELS: str = Field(default="")

    # Ollama (local, OpenAI-compat). Default vazio = desligado. Ex:
    # OLLAMA_BASE_URL=http://localhost:11434/v1 ; OLLAMA_MODELS=llama3.1,qwen2.5.
    # É OpenAICompatProvider → ganha o native tools (tools=) de graça.
    OLLAMA_BASE_URL: str = Field(default="")
    OLLAMA_MODELS: str = Field(default="")
    OLLAMA_API_KEY: str = Field(default="ollama")

    HUGGINGFACE_API_KEY: Optional[str] = Field(default=None)
    HUGGINGFACE_MODELS: str = Field(default="")

    SAMBANOVA_API_KEY: Optional[str] = Field(default=None)
    SAMBANOVA_MODELS: str = Field(default="")

    MISTRAL_API_KEY: Optional[str] = Field(default=None)
    MISTRAL_MODELS: str = Field(default="")

    COHERE_API_KEY: Optional[str] = Field(default=None)
    COHERE_MODELS: str = Field(default="")

    # DeepInfra e Fireworks — OpenAI-compatible, pay-per-use com crédito grátis
    # (Tier 3). Bom leque de modelos (DeepSeek/Qwen/GLM/gpt-oss). IDs verificados
    # nas APIs deles.
    DEEPINFRA_API_KEY: Optional[str] = Field(default=None)
    DEEPINFRA_MODELS: str = Field(default="")
    FIREWORKS_API_KEY: Optional[str] = Field(default=None)
    FIREWORKS_MODELS: str = Field(default="")

    # Anthropic é montado pelo catálogo YAML do RobinBandit como os demais.
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None)
    CLAUDE_MODELS: str = Field(default="")

    # Replicate: guardado p/ uso futuro; usa a API de predictions própria (não
    # OpenAI-compatible), então NÃO entra na cadeia de chat ainda. Declarado só
    # para o pydantic-settings aceitar a variável no .env.
    REPLICATE_API_KEY: Optional[str] = Field(default=None)
    # Volume e narrativa do dataset mock do setor de CX, que mora em memória.
    # Seed fixa = dataset reprodutível entre restarts.
    SENTURY_MOCK_SEED: int = Field(default=42)
    SENTURY_MOCK_FEEDBACKS: int = Field(default=5000)
    SENTURY_MOCK_TICKETS: int = Field(default=15000)
    SENTURY_MOCK_TECHNICIANS: int = Field(default=150)
    SENTURY_MOCK_CONTACTS: int = Field(default=3000)

    SESSION_TTL_SEC: int = Field(default=1800)
    # Arquivo revisitavel de sessoes. O estado operacional quente continua curto,
    # mas a copia de historico/artefatos leves fica disponivel por mais tempo.
    SENTURY_SESSION_ARCHIVE_TTL: int = Field(default=2592000)
    SENTURY_SESSION_MAX_INDEX: int = Field(default=80)
    SENTURY_SESSION_AI_TITLES: bool = Field(default=True)

    SENTURY_API_TOKEN: Optional[str] = Field(default=None)
    CORS_ORIGINS: str = Field(default="*")

    TELEGRAM_TOKEN: Optional[str] = Field(default=None)
    TELEGRAM_BOT_ACTIVE: bool = Field(default=False)
    TELEGRAM_ALLOWED_IDS: Optional[str] = Field(default=None)

    @property
    def telegram_allowed_id_list(self) -> List[int]:
        if not self.TELEGRAM_ALLOWED_IDS:
            return []
        ids = []
        for val in self.TELEGRAM_ALLOWED_IDS.split(","):
            val = val.strip()
            if val:
                try:
                    ids.append(int(val))
                except ValueError:
                    pass
        return ids

    # Gráfico do CX desenhado pelo QuickChart.io, serviço de fora: os dados do
    # gráfico saem da máquina. Desligado, o gráfico é desenhado aqui.
    SENTURY_QUICKCHART: bool = Field(default=False)

    # Documentação automática da API (`/docs`, `/redoc`, `/openapi.json`): um
    # mapa de todas as rotas, sem login. Fechada por padrão; `sentury.py --api`
    # e `--dev` ligam para quem está desenvolvendo.
    SENTURY_DOCS: bool = Field(default=False)

    # RAG do glossário CX/Ops: por padrão usa recuperação léxica em memória
    # (zero infra). Ligue para usar embeddings ONNX locais (fastembed).
    SENTURY_EMBEDDINGS: bool = Field(default=False)

    # RAG com embeddings da API Gemini (cota SEPARADA da de chat, 1K RPD). Opt-in;
    # melhora a busca semântica do glossário sem instalar nada. Fallback: léxico.
    SENTURY_GEMINI_EMBEDDINGS: bool = Field(default=False)
    GEMINI_EMBEDDING_MODEL: str = Field(default="gemini-embedding-001")

    # Aprendizado: de tempos em tempos o Sentury revisa a conversa e guarda o
    # que vale (harness/aprendizado.py). A revisão gasta uma chamada de modelo;
    # desligado, nada roda.
    SENTURY_AUTOLEARN: bool = Field(default=True)
    # Voltas entre uma revisão e outra: cada ferramenta que rodou, ou o turno só de
    # conversa, conta uma. Zero desliga a revisão.
    SENTURY_APRENDER_A_CADA: int = Field(default=10)

    # Setor (dominio) ativo — qual DomainPack o Sentury usa.
    #
    # Sem pacote escolhido, o Sentury usa o motor generalista; setores são
    # extensões opcionais, não dependências do núcleo.
    SENTURY_DOMAIN: str = Field(default="generalista")

    # O replay precisa do estado completo do turno para comparar resultados.
    SENTURY_GRAVAR_TRACOS: bool = Field(default=True)
    # Teto do corpus de desenvolvimento: sem ele o diretorio so cresce, e
    # `replay.listar()` le tudo. `avaliacao` e `holdout` nao sao podados — sao
    # curados, e apagar ali muda a bateria que mede o mutation.
    SENTURY_TRACOS_MAXIMO: int = Field(default=500)
    # O traco guarda a conversa inteira, anexo incluso: prazo, e nao "para sempre".
    SENTURY_TRACOS_DIAS: int = Field(default=30)
    # Anexo recebido no chat: lido no turno em que chegou; depois disso, prazo.
    SENTURY_RECEBIDOS_DIAS: int = Field(default=30)
    # A sessão pertence à conversa e sobrevive aos turnos. Por padrão só fecha
    # por pedido explícito, ao apagar a conversa ou no shutdown; um valor > 0
    # habilita a coleta por inatividade em instalações com pouca memória.
    SENTURY_BROWSER_OCIOSO_MIN: float = Field(default=0)
    # Janela do navegador na frente da pessoa: sim, nao ou auto (abre quando ha
    # tela). Visivel, a pagina ganha a borda, a seta e o balao da Sentury.
    SENTURY_BROWSER_VISIVEL: str = Field(default="auto")
    # Quanto a seta leva ate o alvo antes da acao. 0 tira a espera.
    SENTURY_BROWSER_SETA_MS: int = Field(default=450)
    # O print do computer use: `imagem` (vai ao modelo como imagem, e o Router
    # só usa quem enxerga), `descricao` (um modelo com visão descreve uma vez e
    # o turno segue em texto) ou `auto` (descrição quando o provedor da frente
    # não enxerga e outro enxerga). Ver harness/visao_auxiliar.py.
    SENTURY_COMPUTADOR_VISAO: str = Field(default="auto")
    # Em que Chrome o agente navega pela tela: `pessoa` (o da pessoa, com as
    # contas dela) ou `agente` (um perfil separado, "Chrome do <nome>").
    SENTURY_NAVEGADOR_PERFIL: str = Field(default="pessoa")
    SENTURY_NAVEGADOR_AGENTE_NOME: str = Field(default="Agente")
    # Chamadas nativas usam esquemas validados; provedores sem suporte seguem
    # pelo planejador textual, que precisa reparar JSON inválido.
    SENTURY_NATIVE_TOOLS: bool = Field(default=True)

    # Dados locais não exigem serviço externo nem enviam conversas para fora.
    SENTURY_HOME: str = Field(default="")               # vazio => ~/.sentury
    SENTURY_SESSION_BACKEND: str = Field(default="local")  # local | memory
    SENTURY_DATA_BACKEND: str = Field(default="")      # memory | <o seu>
    # O catálogo nomeia contas e faixas; guarda o nome da variável de ambiente,
    # nunca o valor da credencial.
    # Ex.: {"contas":[{"id":"or-paga","provider":"openrouter",
    #        "key_env":"API_KEY_ULTRA","models":["deepseek/deepseek-v4-pro"],"paga":true}],
    #       "tiers":{"ultra_max":"or-paga"}}
    SENTURY_ACCOUNTS: str = Field(default="")

    # O laço usa o resultado de cada passo para escolher o seguinte.
    SENTURY_AGENT_LOOP: bool = Field(default=True)
    # O índice antecipa esquemas relevantes e permite buscar os demais por nome;
    # descoberta não concede permissão nem executa ferramentas.
    SENTURY_PROGRESSIVE_CAPABILITIES: bool = Field(default=True)
    # A carga sob demanda só liga quando o catálogo inteiro passa deste tanto de
    # tokens (perto de 10% de uma janela de 200 mil); abaixo, vai tudo na chamada.
    SENTURY_FERRAMENTAS_TETO_TOKENS: int = Field(default=20000)
    SENTURY_MAX_LOOPS: int = Field(default=6)

    # Busca web: so o nome da variavel mora aqui; sem chave, nao ha busca.
    TAVILY_API_KEY: Optional[str] = Field(default=None)
    BRAVE_API_KEY: Optional[str] = Field(default=None)
    SERPER_API_KEY: Optional[str] = Field(default=None)
    # Execucao de comandos. Ligada: quem filtra e a politica — leitura roda,
    # escrita pede autorizacao —, e um agente sem comando nenhum nao trabalha.
    SENTURY_SHELL: bool = Field(default=True)
    # Roda o sandbox de Python num processo filho, com timeout que encerra de
    # verdade e teto de memoria. Quando o filho nao sobe, a execucao cai para
    # o modo em processo e registra a degradacao na observabilidade.
    SENTURY_PY_CHILD: bool = Field(default=True)

    # Identidade e procedimentos editáveis não substituem as regras do núcleo.
    SENTURY_PROMPT_CONTEXT_ENABLED: bool = Field(default=True)
    SENTURY_PROMPT_CONTEXT_DIR: str = Field(default="")
    SENTURY_PROMPT_CONTEXT_MAX_CHARS: int = Field(default=12000)

    # Subagentes só entram por pedido explícito; recebem resumos com evidência,
    # sem ferramentas nem nova delegação.
    SENTURY_SUBAGENTS_BETA: bool = Field(default=True)
    SENTURY_SUBAGENTS_DEFAULT: int = Field(default=2)
    SENTURY_SUBAGENTS_MAX: int = Field(default=3)
    SENTURY_SUBAGENT_TIMEOUT_SEC: float = Field(default=35.0)
    SENTURY_SUBAGENT_CONTEXT_CHARS: int = Field(default=12000)
    SENTURY_SUBAGENT_SUMMARY_CHARS: int = Field(default=2400)

    # Pasta onde export_xlsx/export_csv/export_pdf gravam os arquivos gerados
    # (além de devolvê-los em base64 na resposta do /chat).
    SENTURY_EXPORT_DIR: str = Field(default="/tmp/sentury-exports")

    # --- Perfis de tarefa: preferência suave de provider:model por tipo
    # de tarefa. CSV `provider:model` (ex.: "groq:openai/gpt-oss-120b,gemini:...").
    # Vazio → usa DEFAULT_PROFILE_MODELS em llm/profiles.py. Opcional e
    # retrocompatível: sem perfil, o roteamento é idêntico ao de hoje.
    SENTURY_CLASSIFY_MODELS: str = Field(default="")
    SENTURY_ANALYSIS_MODELS: str = Field(default="")
    SENTURY_ARTIFACT_MODELS: str = Field(default="")
    SENTURY_CODING_MODELS: str = Field(default="")
    SENTURY_FALLBACK_MODELS: str = Field(default="")

    @property
    def ollama_model_list(self) -> List[str]:
        return [m.strip() for m in self.OLLAMA_MODELS.split(",") if m.strip()]

    @property
    def openrouter_model_list(self) -> List[str]:
        return [m.strip() for m in self.OPENROUTER_MODELS.split(",") if m.strip()]

    @property
    def ultra_model_list(self) -> List[str]:
        return [m.strip() for m in self.ULTRA_MODEL.split(",") if m.strip()]

    @property
    def ultra_enabled(self) -> bool:
        return bool(self.API_KEY_ULTRA and self.ultra_model_list)

    # --- Ultra Max (Super Máxima): reusa chave/base do Ultra quando não setados ---
    @property
    def ultra_max_model_list(self) -> List[str]:
        return [m.strip() for m in self.ULTRA_MAX_MODEL.split(",") if m.strip()]

    @property
    def ultra_max_key(self) -> Optional[str]:
        return self.API_KEY_ULTRA_MAX or self.API_KEY_ULTRA

    @property
    def ultra_max_base_url(self) -> str:
        return self.ULTRA_MAX_BASE_URL or self.ULTRA_BASE_URL

    @property
    def ultra_max_enabled(self) -> bool:
        return bool(self.ultra_max_key and self.ultra_max_model_list)

    @property
    def groq_model_list(self) -> List[str]:
        return [m.strip() for m in self.GROQ_MODELS.split(",") if m.strip()]

    @property
    def groq_planner_model_list(self) -> List[str]:
        return [m.strip() for m in self.GROQ_PLANNER_MODELS.split(",") if m.strip()]

    @property
    def gemini_model_list(self) -> List[str]:
        return [m.strip() for m in self.GEMINI_MODELS.split(",") if m.strip()]

    @staticmethod
    def _csv(value: str) -> List[str]:
        return [m.strip() for m in (value or "").split(",") if m.strip()]

    @property
    def github_models_list(self) -> List[str]:
        return self._csv(self.GITHUB_MODELS_MODELS)

    @property
    def cerebras_model_list(self) -> List[str]:
        return self._csv(self.CEREBRAS_MODELS)

    @property
    def huggingface_model_list(self) -> List[str]:
        return self._csv(self.HUGGINGFACE_MODELS)

    @property
    def sambanova_model_list(self) -> List[str]:
        return self._csv(self.SAMBANOVA_MODELS)

    @property
    def mistral_model_list(self) -> List[str]:
        return self._csv(self.MISTRAL_MODELS)

    @property
    def cohere_model_list(self) -> List[str]:
        return self._csv(self.COHERE_MODELS)

    @property
    def deepinfra_model_list(self) -> List[str]:
        return self._csv(self.DEEPINFRA_MODELS)

    @property
    def fireworks_model_list(self) -> List[str]:
        return self._csv(self.FIREWORKS_MODELS)

    @property
    def claude_model_list(self) -> List[str]:
        return self._csv(self.CLAUDE_MODELS)

    @property
    def sentury_analysis_model_targets(self):
        from robinbandit.profiles import parse_profile_targets
        return parse_profile_targets(self.SENTURY_ANALYSIS_MODELS)

    @property
    def sentury_artifact_model_targets(self):
        from robinbandit.profiles import parse_profile_targets
        return parse_profile_targets(self.SENTURY_ARTIFACT_MODELS)

    @property
    def sentury_coding_model_targets(self):
        from robinbandit.profiles import parse_profile_targets
        return parse_profile_targets(self.SENTURY_CODING_MODELS)

    @property
    def sentury_fallback_model_targets(self):
        from robinbandit.profiles import parse_profile_targets
        return parse_profile_targets(self.SENTURY_FALLBACK_MODELS)

    @property
    def cors_origin_list(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


def _carregar_cofre_no_ambiente() -> None:
    """As chaves gravadas pelo painel entram como variáveis de ambiente antes
    do Settings ler o ambiente, para a cadeia de provedores montada no import
    já usá-las.

    O cofre é o lugar das chaves: ele vence o `.env`, que fica como valor
    inicial. Só uma variável já definida no ambiente do processo (servidor,
    container) vence o cofre.
    """
    try:
        from robinbandit import secrets
        from .exec.segredos import registrar_configuracao

        credenciais = []
        for nome, valor in (secrets._carregar() or {}).items():
            efetivo = os.environ.setdefault(str(nome), ",".join(secrets._lista(valor)))
            credenciais.extend(secrets._lista(valor))
            credenciais.extend(secrets._lista(efetivo))
        registrar_configuracao({"SECRET": credenciais})
    except Exception:   # cofre é conveniência: nunca pode impedir o boot
        pass


_carregar_cofre_no_ambiente()
settings = Settings()
