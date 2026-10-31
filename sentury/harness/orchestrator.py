import logging
import re
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import settings
from ..llm.action_parser import extract_plain_text
from ..llm.prompts import (
    system_persona_do_dominio,
    build_tool_result_instruction,
)
from ..memory.skill_store import build_skills_context
from ..artifacts import plan_artifact_request, validate_delivery
from ..tools.catalog import execute_tool
from .guardrails import OBSERVERS, OUTPUT_GUARDRAILS, veredito
from ..tools.registry import com_propriedade
from .policy import ANALYSIS_TOOLS
from .state import AnalysisState
from .entrega_de_artefato import EntregaDeArtefato

# Novos componentes da arquitetura
from .context_budget import ContextBudgetManager, Contextualizer
from .council import SenturyCouncil

from ..memory.experience_library import ExperienceLibrary
from ..context import PromptContextEngine
from ..agents import ExplicitSubagentCoordinator

from ..skills.skill_loader import SkillLoader
from ..skills.skill_discovery import SkillDiscoveryEngine
from . import passo_unico
from .conversa import preparar_legado
from .titulo_de_ferramenta import alvo as alvo_da_ferramenta, rotulo_de_progresso, titulo_do_passo


from ..skills.skill_usage import SkillUsageTracker




from .contexto_do_mundo import ambiente_do_turno as _ambiente_do_turno
from .contexto_do_mundo import decisoes as _decisoes, memoria_da_pessoa as _memoria_da_pessoa, equipe as _equipe, mcp as _contexto_mcp, outras_conversas as _outras_conversas
from ..domains.steering import do_turno as _steering_do_turno
from ..tools.selos import ACTION_INTENTS as _ACTION_INTENTS
from ..tools.selos import TOOL_KINDS as _TOOL_KINDS
from ..tools.selos import intent_da_ferramenta as _intent_da_ferramenta
from ..tools.selos import kind_da_ferramenta as _kind_da_ferramenta
from ..context.base import _texto_base
from . import turno as _turno
from .artefato_do_turno import estrategia_visual, ultima_analise
from ..tools.subagentes import registrar as _registrar_subagentes

logger = logging.getLogger(__name__)











def _campos_simples(dados: Dict[str, Any]):
    """(campo, valor) de texto curto ou numero, na ordem do resultado.

    Checagem escalar explicita: o dataset devolve np.float64 e afins, e
    comparar array com `in (None, "")` estoura.
    """
    for k, v in dados.items():
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, str):
            if v.strip() and len(v) <= 40:
                yield k, v
        elif isinstance(v, (int, float)) or type(v).__name__.startswith(("float", "int")):
            yield k, v


# Prompt do Planner para gerar planos de ação estruturados
PLANNER_SYSTEM_PROMPT = _texto_base("PLANNER_SYSTEM_PROMPT")

RESPONSE_SYSTEM_PROMPT = _texto_base("RESPONSE_SYSTEM_PROMPT")



def _prompt_do_planejador(com_ferramentas: bool = True) -> str:
    """Ver llm/secoes.py: o prompt e montado de secoes, e a orientacao de cada
    ferramenta viaja com ela."""
    from ..llm.secoes import prompt_do_planejador

    # Sem as ferramentas no prompt e o passo unico: as regras, sem o contrato de JSON.
    base = PLANNER_SYSTEM_PROMPT if com_ferramentas else passo_unico.base_do_passo(PLANNER_SYSTEM_PROMPT)
    return prompt_do_planejador(base, com_ferramentas)


from .perguntas import limites as _limites_de_pergunta
MAX_ETAPAS_DE_PERGUNTA, MAX_OPCOES_POR_ETAPA = _limites_de_pergunta()

# Limita perguntas consecutivas para que o agente avance ou explique o bloqueio.
MAX_PERGUNTAS_SEGUIDAS = 2


class SenturyOrchestrator(EntregaDeArtefato):
    """Liga o turno: o modelo escolhe as ferramentas no laço, o harness aplica
    a política e executa, e o redator escreve quando o laço não respondeu."""

    def __init__(self, planner, responder, store, knowledge=None, memory=None, skills=None,
                 context_budget_manager=None, experience_library=None, council=None,
                 session_index=None,
                 skills_dir: Optional[Path] = None, user_skills_dir: Optional[Path] = None,
                 prompt_context_engine=None, subagent_coordinator=None,
                 provider_router_backend=None):
        self.planner = planner
        self.responder = responder
        self.store = store
        self.knowledge = knowledge
        self.memory = memory
        self.skills = skills
        self.robin = provider_router_backend or getattr(responder, "router", None)

        self.context_budget_manager = context_budget_manager or ContextBudgetManager(Contextualizer(self.responder))
        self.experience_library = experience_library or ExperienceLibrary()
        # Índice das conversas anteriores deste usuário (memória episódica).
        self.session_index = session_index
        self.council = council or SenturyCouncil(self.planner)

        context_root = Path(settings.SENTURY_PROMPT_CONTEXT_DIR) if settings.SENTURY_PROMPT_CONTEXT_DIR else None
        self.prompt_context_engine = prompt_context_engine or PromptContextEngine(
            context_root,
            enabled=settings.SENTURY_PROMPT_CONTEXT_ENABLED,
            max_chars=settings.SENTURY_PROMPT_CONTEXT_MAX_CHARS,
        )
        self.subagent_coordinator = subagent_coordinator or ExplicitSubagentCoordinator(
            self.planner,
            context_engine=self.prompt_context_engine,
            enabled=settings.SENTURY_SUBAGENTS_BETA,
            default_count=settings.SENTURY_SUBAGENTS_DEFAULT,
            max_count=settings.SENTURY_SUBAGENTS_MAX,
            timeout_seconds=settings.SENTURY_SUBAGENT_TIMEOUT_SEC,
            max_context_chars=settings.SENTURY_SUBAGENT_CONTEXT_CHARS,
            max_summary_chars=settings.SENTURY_SUBAGENT_SUMMARY_CHARS,
        )
        _registrar_subagentes(self.subagent_coordinator)

        base_path = Path(__file__).resolve().parent.parent
        self.skills_dir = Path(skills_dir) if skills_dir else base_path / "skills"
        
        from ..skills.escrita import pasta_do_usuario
        self.user_skills_dir = Path(user_skills_dir) if user_skills_dir else pasta_do_usuario()
        self.user_skills_dir.mkdir(parents=True, exist_ok=True)
        
        self.skill_loader = SkillLoader(self.skills_dir, self.user_skills_dir, com_setor=True)
        self.skill_discovery = SkillDiscoveryEngine(self.skill_loader)
        
        usage_file = self.user_skills_dir / ".usage.json"
        self.skill_usage_tracker = SkillUsageTracker(usage_file)

        from .policy import PROCEDURAL_SKILLS
        self.procedural_skills = set()
        try:
            for s in self.skill_loader.scan_skills():
                self.procedural_skills.add(s.name)
                PROCEDURAL_SKILLS.add(s.name)
        except Exception as e:
            logger.warning("Falha ao povoar índice de skills iniciais: %s", e)

    @property
    def turno(self) -> _turno.Turno:
        """O estado do turno em curso nesta tarefa; ver harness/turno.py."""
        return _turno.atual()

    @staticmethod
    def _msg_usuario(state: AnalysisState, texto: str, priority: Optional[str] = None) -> Dict[str, Any]:
        """Mensagem do usuario com as imagens do turno, quando houver.

        O conteudo continua texto; a imagem vai num campo proprio e so a chain
        monta o formato multimodal na saida para o provedor.
        """
        msg: Dict[str, Any] = {"role": "user", "content": texto}
        if priority:
            msg["priority"] = priority
        imagens = getattr(state, "imagens_do_turno", None)
        if imagens:
            msg["imagens"] = list(imagens)
            state.imagens_do_turno = None
        return msg

    async def handle_message(self, state: AnalysisState, user_message: str, progress_cb=None,
                             effort: Optional[str] = None) -> Dict[str, Any]:
        """`effort` é a escolha manual da barra; None deixa o provedor no padrão dele.

        A resolução mora aqui, não no endpoint: o Telegram, o cron e a eval
        chamam este método direto e recebem o mesmo comportamento.
        """
        from ..llm.effort import clear_effort, normalize as _norm_effort, use_effort
        from .perguntas import validar_retomada

        _turno.novo()
        user_message = validar_retomada(state, user_message)

        # O Auto não escolhe esforço pela mensagem: palavra não diz o tamanho
        # da tarefa em toda língua nem com erro de digitação.
        nivel = _norm_effort(effort)
        _etoken = use_effort(nivel) if nivel else None
        # O turno gravado para o replay. Aqui, e nao no `_inner`: aquele tem
        # seis saidas. Ver harness/gravacao_do_turno.py.
        from .gravacao_do_turno import abrir as _abrir_gravacao, fechar as _fechar_gravacao

        _antes = _abrir_gravacao(state)
        # O modo escolhido no painel vale o turno inteiro; mudar no meio vale no proximo.
        from robinbandit.account_config import congelar_selecao_do_turno, soltar_selecao_do_turno

        _modo_token = congelar_selecao_do_turno()
        from .emissor import EMISSOR

        _emissor_token = EMISSOR.set(None)
        from .descoberta import abrir as abrir_descoberta, fechar as fechar_descoberta
        _descoberta_token = abrir_descoberta()
        try:
            resultado = await self._handle_message_inner(state, user_message, progress_cb)
            _fechar_gravacao(state, user_message, resultado, _antes, nivel)
            return resultado
        finally:
            fechar_descoberta(_descoberta_token)
            from ..tools.computador import encerrar_do_turno  # moldura sai, aprovacao do turno vence
            encerrar_do_turno(state)
            from ..tools.browser_chrome_provider import soltar_do_turno  # a borda da aba apaga com o turno
            soltar_do_turno(state)
            EMISSOR.reset(_emissor_token)
            soltar_selecao_do_turno(_modo_token)
            if _etoken is not None:
                clear_effort(_etoken)

    async def _insight_proativo(self, tool_results: Any) -> Optional[str]:
        """Uma observacao nao-obvia que o usuario nao pediu.

        Deterministico e grounded: os numeros saem dos resultados, e o modelo so
        redige em cima deles. So aparece em padrao notavel: insight em todo
        turno deixa de ser insight.
        """
        from .insight_proativo import derivar, polir

        insight = derivar(*ultima_analise(tool_results))
        return await polir(insight, self.responder) if insight else insight

    async def _handle_message_inner(self, state: AnalysisState, user_message: str, progress_cb=None) -> Dict[str, Any]:
        start_time = time.time()
        telemetry = {}
        self.turno.reparos_json = 0
        try:
            from robinbandit.chain import iniciar_contagem, iniciar_conversa
            iniciar_contagem(); iniciar_conversa(state.session_id)  # grude do Router
        except Exception:
            pass

        from .canal_do_turno import CanalDoTurno

        canal = CanalDoTurno(self, state, progress_cb)
        canal.ligar()

        from .abertura_do_turno import abrir as _abrir_turno

        aberto = await _abrir_turno(
            self, state, user_message, telemetry=telemetry, start_time=start_time,
            canal=canal,
        )
        if isinstance(aberto, dict):
            return aberto

        from .laco_do_turno import novo as _novo_laco, rodar as _rodar_laco

        laco = _novo_laco(self, state, user_message, aberto)
        self.turno.resposta_conferida = None
        self.turno.fala_da_volta = None
        parou = await _rodar_laco(self, laco, state=state, user_message=user_message, aberto=aberto,
                                  telemetry=telemetry, canal=canal)
        if parou is not None:
            return parou

        from .fechamento_do_turno import fechar as _fechar_turno

        return await _fechar_turno(
            self, state=state, user_message=user_message, start_time=start_time, telemetry=telemetry,
            decision_log=aberto.decision_log, deliberation=laco.deliberation, plan=laco.plano,
            complexity=aberto.complexity, tool_results=laco.tool_results, exit_reason=laco.exit_reason,
            unresolved_tool_failure=laco.unresolved_tool_failure, export_response=laco.export_response,
            attachment=laco.attachment, anexos_do_turno=laco.anexos_do_turno,
            pre_turn_had_data=laco.pre_turn_had_data, compacted=aberto.compacted,
            contexto_adicional=aberto.contexto_adicional, rag_context=aberto.rag_context,
            turn_activated_skills=laco.turn_activated_skills, repeticoes_puladas=laco.repeticoes_puladas,
            orcamento=laco.orcamento, progress=canal.progress, emit=canal.emit,
            emit_reasoning=canal.emit_reasoning,
        )

    def _extract_clarification(self, plan: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        from .perguntas import extrair

        return extrair(plan, getattr(self, "_refresh_period_option_descriptions", None))

    @staticmethod
    def _refresh_period_option_descriptions(options: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Evita opções de período fossilizadas pelo modelo (por exemplo, 2025)
        quando a conversa e o dataset já estão em 2026."""
        months = (
            "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
        )
        today = date.today()
        previous = today.replace(day=1) - timedelta(days=1)
        quarter_start = (today.replace(day=1) - timedelta(days=61)).replace(day=1)
        semester_start = (today.replace(day=1) - timedelta(days=152)).replace(day=1)
        refreshed: List[Dict[str, str]] = []
        for option in options:
            item = dict(option)
            label = unicodedata.normalize("NFKD", str(item.get("label") or "")).encode("ascii", "ignore").decode("ascii").lower()
            if "ultimo mes" in label:
                item["description"] = f"{months[previous.month - 1]} {previous.year}"
            elif "ultimo trimestre" in label:
                item["description"] = f"{months[quarter_start.month - 1]} a {months[today.month - 1]} {today.year}"
            elif "ultimo semestre" in label:
                item["description"] = f"{months[semester_start.month - 1]} a {months[today.month - 1]} {today.year}"
            elif "ano atual" in label:
                item["description"] = f"Janeiro a {months[today.month - 1]} {today.year}"
            refreshed.append(item)
        return refreshed

    def _pontuar_resposta(
        self,
        user_message: str,
        reply_text: str,
        complexity: Optional[str],
        decision_log: Dict[str, Any],
    ) -> None:
        """Devolve ao RobinBandit se o provedor inventou numero neste turno.

        O veredito vinha da autocritica: uma chamada de modelo pedindo
        "APROVADO ou a lista de erros". Ela era a UNICA fonte do sinal dentro
        do chat (a outra e o `/feedback` da API do RobinBandit), entao
        aposenta-la sem trocar a fonte cegaria o roteador.

        `veredito` devolve None quando nao ha o que julgar, e ai nada e
        registrado: resposta sem valor algum nao e prova de fidelidade.
        """
        bom = veredito(reply_text, bool(self.turno.grounding_avisou))
        if bom is None or self.robin is None:
            return
        provedor = self.planner if self.turno.passo_unico else self.responder
        resp_key = str(
            getattr(provedor, "last_provider", "")
            or str(getattr(provedor, "last_model", "") or "").split(":")[0]
        )
        if resp_key in ("cache", "fallback", ""):
            return
        self.robin.reward_quality(resp_key, complexity, bom, model=getattr(provedor, "last_model", None))

    async def _contexto_do_turno(
        self,
        state: AnalysisState,
        decision_log: Dict[str, Any],
    ) -> Optional[str]:
        """Reúne o que o agente precisa saber além da pergunta.

        Cinco fontes, cada uma com um motivo próprio para estar aqui:

        - **memória do usuário**.
        - **skills salvas**, o que ele já aprendeu a fazer nesta conversa.
        - **dica de design**, e SÓ quando há dado real na sessão. Sem esse
          cuidado a dica empurra o modelo a montar um artefato no vazio, e um
          dashboard com números de mentira parece mais confiável que um erro.
        - **o ambiente**, porque sem saber o sistema o agente manda `ls` onde
          só existe `dir`.
        - **os servidores MCP conectados**: sem a lista, `usar_mcp` fica no
          prompt sem nada para chamar.

        Devolve `None` quando não há nada a acrescentar: string vazia viraria
        uma seção de cabeçalho sem conteúdo no prompt.
        """
        memoria_ctx = await _memoria_da_pessoa(self.memory, state)

        skills_ctx = None
        if self.skills:
            skills_ctx = build_skills_context(await self.skills.all(state.user_id))

        return "\n\n".join(
            c for c in (
                memoria_ctx, skills_ctx,
                _ambiente_do_turno(state.session_id), _contexto_mcp(), _outras_conversas(state.session_id), _decisoes(state), _equipe(state),
                _steering_do_turno(state),
            ) if c
        ) or None

    async def _escrever_resposta(
        self,
        user_message: str,
        state: AnalysisState,
        council_analysis: Optional[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
        telemetry: Dict[str, Any],
        decision_log: Dict[str, Any],
        _progress,
    ) -> str:
        """A resposta do turno. Um modelo, um laço: o texto da última volta, que
        viu os resultados, já é a resposta; sem ele, uma chamada de fechamento na
        mesma conversa, sem ferramenta. Nenhum segundo modelo reescreve o que o
        primeiro já escreveu."""
        turno = self.turno
        telemetry["responder_ms"] = 0
        decision_log["responder_reasoning_summary"] = None
        if turno.resposta_conferida:
            decision_log["responder_mode"] = "resposta_conferida"
            return turno.resposta_conferida
        if council_analysis:
            decision_log["responder_mode"] = "native_council"
            decision_log["responder_model"] = None
            consenso = str(council_analysis.get("consensus_recommendation") or "").strip()
            return f"Conselho concluido. {consenso}\n\nOs cinco pareceres e os trade-offs estao no card abaixo.".strip()
        decision_log["responder_model"] = decision_log.get("planner_model")
        if turno.resposta_direta:
            decision_log["responder_mode"] = "planner_direct_response"
            return turno.resposta_direta
        from .encerramento import responder_no_limite

        _progress("Redigindo a resposta…")
        inicio = time.time()
        texto = await responder_no_limite(self, state, user_message,
                                          [str((r or {}).get("tool") or "") for r in tool_results])
        telemetry["responder_ms"] = int((time.time() - inicio) * 1000)
        decision_log["responder_model"] = getattr(self.planner, "last_model", None)
        decision_log["responder_mode"] = "fechamento_sem_ferramenta"
        return texto

    def _detect_follow_up_and_extract_context(self, user_message: str, state: AnalysisState) -> Tuple[bool, List[Dict[str, Any]]]:
        """Devolve observações candidatas; a relação com o pedido cabe ao modelo."""
        from .antecedentes import extrair

        chave = (id(state), user_message)
        if getattr(self, "_chave_antecedentes", None) == chave:
            resultados = self._antecedentes_do_turno
        else:
            resultados = extrair(state, user_message)
        return bool(resultados), resultados

    def _format_tool_results_for_context(self, tool_results: List[Dict[str, Any]]) -> str:
        """
        Formats tool results for injection into Planner context.
        Extracts key data and formats for readability without overwhelming the context.
        
        Args:
            tool_results: List of "system" messages containing tool execution results
            
        Returns:
            Formatted string with tool results ready for context injection
        """
        if not tool_results:
            return ""
        
        formatted_parts = []
        for idx, result in enumerate(tool_results, 1):
            content = result.get("content", "")
            # Ignora o prefixo anterior ao marcador do resultado.
            if "RESULTADO DA FERRAMENTA" in content:
                # Split on the marker and take everything after it
                marker = "RESULTADO DA FERRAMENTA"
                marker_index = content.find(marker)
                if marker_index != -1:
                    # Mantém o marcador para identificar a origem do conteúdo.
                    content = content[marker_index:]
                
                # Limit length to avoid overwhelming context (max ~500 chars per result)
                if len(content) > 500:
                    content = content[:500] + "... (dados adicionais truncados)"
                formatted_parts.append(f"Resultado {idx}:\n{content}")
        
        return "\n\n".join(formatted_parts)

    def _decorate_harness(
        self,
        decision_log: Dict[str, Any],
        user_message: str,
        attachment: Optional[Dict[str, Any]],
        message: str,
    ) -> Dict[str, Any]:
        artifact_plan = plan_artifact_request(attachment)
        harness = dict(decision_log)
        harness["artifact_plan"] = artifact_plan
        harness["artifact_validation"] = validate_delivery(attachment)
        harness["visual_strategy"] = estrategia_visual(artifact_plan, attachment)
        raw_reasoning_keys = (
            "planner_reasoning_summary",
            "responder_reasoning_summary",
            "council_reasoning_summary",
            "reasoning_summary",
        )
        harness["reasoning_applied"] = any(bool(harness.get(key)) for key in raw_reasoning_keys)
        for key in raw_reasoning_keys:
            harness.pop(key, None)
        return harness

    @staticmethod
    def _progress_label_for_tool(tool: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        return rotulo_de_progresso(tool, arguments)

    # `kind` e `intent` moram em `sentury/tools/selos.py`: sao propriedade da
    # ferramenta, nao do laco de turno. Ficam expostos aqui porque tem chamador
    # e porque o contrato do client declara o mesmo vocabulario que
    # `TOOL_KINDS`, entao mudar um exige mudar o outro e o teste pega quem
    # esquecer.
    TOOL_KINDS = _TOOL_KINDS
    ACTION_INTENTS = _ACTION_INTENTS

    @staticmethod
    def _tool_intent(tool: str) -> str:
        return _intent_da_ferramenta(tool)

    @staticmethod
    def _tool_kind(tool: str) -> str:
        return _kind_da_ferramenta(tool)






    @staticmethod
    def _tool_command(tool: str, arguments: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """O que de fato vai rodar, quando roda algo. A interface mostra isso
        antes do resultado: execucao nao pode ser invisivel."""
        args = arguments or {}
        for chave in ("codigo", "sql", "query", "comando", "command"):
            valor = args.get(chave)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()
        # Nem toda ferramenta roda um comando, mas toda ferramenta age sobre
        # algo. O cartao de execucao e a caixa que ja existe para mostrar isso;
        # fechado, ele e uma linha so, entao nao vira parede.
        return alvo_da_ferramenta(tool, arguments)

    @staticmethod
    def _tool_title(tool: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        return titulo_do_passo(tool, arguments)

    @staticmethod
    def _clean_reasoning_for_stream(raw: Optional[str]) -> str:
        """Aparo o resumo de <think> do modelo pra virar narração ao vivo: tira as
        tags, colapsa espaço em branco e descarta ruído curto demais."""
        if not raw:
            return ""
        text = str(raw)
        text = re.sub(r"</?think>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"```[a-zA-Z]*", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 12:
            return ""
        # Classificador e planner podem partilhar o mesmo motor, e `last_reasoning
        # _summary` fica no objeto ate alguem sobrescrever: o raciocinio do
        # classify vazava como se fosse do turno. Este vocabulario e so dele
        # (o esquema intent/complexity/events), nunca narracao util.
        if SenturyOrchestrator._parece_do_classificador(text):
            return ""
        return text

    _MARCAS_DO_CLASSIFICADOR = (
        "need_planner", "need_council", "need_review", "direct_response",
        "check_experience", '"intent"', "intent:", "complexity:", "priority:",
    )

    @staticmethod
    def _parece_do_classificador(texto: str) -> bool:
        baixo = texto.lower()
        return sum(1 for marca in SenturyOrchestrator._MARCAS_DO_CLASSIFICADOR if marca in baixo) >= 2

    def _injetar_passo_retomado(self, plan, retomar):
        """Ver harness/retomada.py: por que executar em vez de pedir."""
        from .retomada import injetar_passo

        return injetar_passo(plan, retomar)


    # O YAML declara quais resultados servem de lastro para artefatos.
    _GROUNDING_TOOLS = com_propriedade("traz_dado")

    @staticmethod
    def _describe_current_state(state: AnalysisState) -> str:
        """Uma linha por coisa que já existe: análises rodadas e o último
        artefato entregue.

        É o antecedente que faltava pro refinamento. "Muda a cor pra azul" só
        faz sentido se o modelo souber que existe um gráfico, e qual.
        """
        linhas: List[str] = []
        for rid, receita in list(state.results.items())[-4:]:
            tool = receita.get("tool")
            resumo = receita.get("summary") or {}
            marcas = []
            if isinstance(resumo, dict):
                # Usa campos simples do resultado, independentemente do setor.
                for k, v in _campos_simples(resumo):
                    marcas.append(f"{k}={v}")
                    if len(marcas) >= 3:
                        break
            linhas.append(f"- `{rid}` — {tool}({', '.join(marcas) if marcas else 'sem filtro'})")

        ultimo_artefato = None
        for msg in reversed(state.history):
            att = msg.get("attachment")
            if isinstance(att, dict) and att.get("type"):
                ultimo_artefato = att
                break
        if ultimo_artefato:
            titulo = ultimo_artefato.get("title") or ultimo_artefato.get("filename") or "artefato"
            linhas.append(
                f"- ÚLTIMO ARTEFATO ENTREGUE: {titulo} ({ultimo_artefato.get('type')}). "
                "Se o usuário pedir para MUDAR, AJUSTAR ou TIRAR algo dele, refaça ESTE "
                "artefato com a alteração — reaproveitando o resultado que já existe acima. "
                "NÃO comece uma análise nova nem entregue outra coisa."
            )
        return "\n".join(linhas)

    @staticmethod
    def _derive_objective(user_message: str) -> str:
        """Objetivo curto do turno para o DeliberationState (o 'por que' do que o agente
        vai fazer). Respostas de esclarecimento (p:/r:) não são o objetivo real."""
        msg = (user_message or "").strip()
        if msg.lower().startswith(("p:", "r:")) or "[esclarecimento" in msg.lower():
            msg = "prosseguir com o contexto esclarecido"
        short = msg if len(msg) <= 90 else msg[:88] + "…"
        return f"Atender: {short}" if short else "Atender"

    @staticmethod
    def _observe_result(tool: str, result: Any) -> str:
        """Observação de UMA linha do que a ferramenta trouxe (o 'observation' do loop)."""
        t = str(tool or "")
        if isinstance(result, dict) and result.get("erro"):
            return f"{t} falhou: {str(result.get('erro'))[:120]}"
        if isinstance(result, dict):
            achados = [f"{k}={v}" for k, v in _campos_simples(result)][:2]
            return f"{t} → " + (", ".join(achados) if achados else "resultado obtido")
        if isinstance(result, (list, tuple)):
            return f"{t} → {len(result)} item(ns)"
        if isinstance(result, str):
            s = result.strip()
            return f"{t} → " + ((s[:70] + "…") if len(s) > 70 else (s or "vazio"))
        return f"{t} → ok"

    _prepare_messages = staticmethod(preparar_legado)

    async def _generate_plan(self, user_message: str, state: AnalysisState, contexto_adicional: Optional[str],
                             rag_context: str, complexity: Optional[str] = None, is_replanning: bool = False,
                             planner_mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """A chamada da volta: ver harness/chamada_da_volta.py."""
        from .chamada_da_volta import chamar

        return await chamar(self, user_message, state, contexto_adicional, rag_context,
                            complexity, is_replanning, planner_mode)

    def _requested_skill_name(self, user_message: str, funcoes: Optional[List[str]] = None
                              ) -> Tuple[Optional[str], Optional[str]]:
        from .roteamento_de_skill import escolher

        return escolher(user_message, self.procedural_skills, self.skill_loader.scan_skills, funcoes)

    async def _handle_skill(self, state: AnalysisState, tool: str, arguments: Dict[str, Any]):
        nome = (arguments.get("nome") or arguments.get("nome_skill") or "").strip().lower()

        if tool == "salvar_skill":
            if self.skills is None:
                return ("terminal", "Skills indisponíveis nesta instância.")
            passos = [{"tool": r["tool"], "arguments": r["arguments"]} for r in state.results.values()]
            if not passos:
                return ("terminal", "Ainda não há uma análise nesta conversa para salvar como skill. Rode uma análise primeiro.")
            if not nome:
                return ("terminal", "Como quer chamar essa skill?")
            await self.skills.save(state.user_id, nome, passos)
            return ("terminal", f"Pronto — salvei como a skill “{nome}” ({len(passos)} passo(s)). Depois é só pedir “rode a skill {nome}”.")

        if tool == "listar_skills":
            from .comando_de_barra import _format_skills_pretty, skills_disponiveis

            todas = await skills_disponiveis(self, state)
            if not todas:
                return ("terminal", "Você ainda não possui skills ou skills salvas no sistema.")
            return ("terminal", _format_skills_pretty(todas))

        if tool == "esquecer_skill":
            if self.skills is None:
                return ("terminal", "Skills indisponíveis nesta instância.")
            removidos = await self.skills.delete(state.user_id, nome) if nome else 0
            return ("terminal", f"Removi a skill “{nome}”." if removidos else f"Não encontrei a skill “{nome}”.")

        # Rota primária: Tenta carregar do loader (Nível 1 - procedural)
        skill_content = self.skill_loader.load_skill(nome, session_id=state.session_id)
        if skill_content:
            # Registra telemetria de uso
            self.skill_usage_tracker.bump_use(nome, success=True)
            
            # Injeta o bloco markdown completo de instruções no histórico da sessão
            instruction_block = skill_content.to_context_block()
            state.history.append({
                "role": "system",
                "content": f"[INSTRUÇÃO PROCEDURAL DE SKILL CARREGADA]\n\n{instruction_block}",
                "priority": "HIGH"
            })
            logger.info("Skill procedural '%s' injetada com sucesso no histórico da sessão.", nome)
            return ("continue", None)

        # Fallback: receita salva pelo usuario (skill_store)
        if self.skills is None:
            return ("terminal", f"Não encontrei a skill “{nome}”.")

        passos = await self.skills.get(state.user_id, nome)
        if not passos:
            return ("terminal", f"Não encontrei a skill “{nome}”. Veja as suas com “listar skills”.")
        
        ultimo = None
        for passo in passos:
            try:
                resultado = await execute_tool(
                    self.store, state, passo["tool"], passo["arguments"], self.knowledge, self.memory
                )
            except Exception as exc:
                logger.warning("Replay da skill '%s', passo %s falhou: %s", nome, passo.get("tool"), exc)
                continue
            ultimo = (passo["tool"], resultado)
        
        instruction = build_tool_result_instruction(ultimo[0], ultimo[1])
        if ultimo[0] in ANALYSIS_TOOLS and state.last_result_id:
            instruction = f"ID DO RESULTADO NA SESSÃO: '{state.last_result_id}'\n" + instruction
        state.history.append({"role": "system", "content": instruction})
        return ("continue", None)

    async def _enforce_grounding(self, state: AnalysisState, text: str) -> str:
        # O observador vira telemetria, não só linha de log. Sem contar
        # quantos números são de evidência, quantos são conta sobre ela e
        # quantos ninguém explica, não dá pra saber a taxa de falso positivo.
        self.turno.grounding: Dict[str, Any] = {}
        avisos: List[str] = []
        for observe in OBSERVERS:
            r = observe(state, text)
            if r.detail:
                self.turno.grounding[r.name] = r.detail
            if r.reason:
                # Só vira aviso no log o que chega à pessoa; o resto já está na telemetria.
                (logger.warning if r.aviso else logger.debug)("Guardrail %s: %s", r.name, r.reason)
            if r.aviso:
                avisos.append(r.aviso)
        # O aviso vai JUNTO da resposta, nao no lugar dela. Reescrever custava
        # uma chamada de modelo e ainda podia apagar valor com lastro; avisar
        # custa zero e deixa a conferencia com quem vai usar o numero.
        # O pontuador lê isto logo depois: é o mesmo fato (o número tem
        # origem?) que a autocrítica gastava uma chamada de modelo para saber.
        self.turno.grounding_avisou = bool(avisos)
        if avisos:
            text = text.rstrip() + "\n\n---\n" + "\n".join(avisos)

        for guardrail in OUTPUT_GUARDRAILS:
            resultado = guardrail(state, text)
            if not resultado.tripwire_triggered:
                continue
            logger.warning("Guardrail %s disparou: %s", resultado.name, resultado.reason)

            messages = [
                {"role": "system", "content": system_persona_do_dominio() + "\n\n" + RESPONSE_SYSTEM_PROMPT + "\n\n" + resultado.correction_instruction},
                {"role": "user", "content": text}
            ]
            raw = await self.responder.complete(messages)
            corrigido = extract_plain_text(raw)
            triggered_again = guardrail(state, corrigido).tripwire_triggered
            if corrigido and not triggered_again:
                text = corrigido
            elif resultado.sanitize:
                text = resultado.sanitize(corrigido or text)

        return text
