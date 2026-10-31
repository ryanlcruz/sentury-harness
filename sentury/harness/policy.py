from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .state import AnalysisState
from ..tools.registry import names_for_gate

# === Categorias de ferramenta: DERIVADAS do ToolRegistry ===================
# Passo 1 da plugabilidade: a fonte única da verdade agora é tools/registry.py
# (TOOL_REGISTRY). Os conjuntos abaixo são derivados por GATE: conteúdo idêntico
# ao que eram como listas hardcoded, mas adicionar uma tool passa a ser um
# registro único, não editar vários sets. O drift test (tests/test_registry.py)
# continua garantindo a sincronia com o prompt.

# Análise: computam do dataset na hora, só leem, nunca exigem pré-condição.
# Inclui o escape-hatch (executar_python), a leitura da camada
# de execução (priorizar_casos/gerar_resposta).
ANALYSIS_TOOLS = names_for_gate("analysis")

# AÇÃO: abrem/atualizam/listam ações corretivas (acoes_corretivas). Escrevem
# estado benigno e auditável, iniciado pelo gestor: sempre permitidas. Quando
# entrarem dados reais com PII, é o ponto natural para gate de LGPD.
ACTION_TOOLS = names_for_gate("action")

# Renderização/exportação: nunca geram dado novo, só apresentam/exportam um
# resultado já computado nesta sessão (o gate _evaluate_export garante isso).
EXPORT_TOOLS = names_for_gate("export")

# Leitura de conhecimento (RAG/FAQ): só lê corpus conceitual em memória.
READ_TOOLS = names_for_gate("read")

# Memória do usuário: salva/lê preferências de longo prazo (não toca o dataset).
MEMORY_TOOLS = names_for_gate("memory")

# Skills reutilizáveis: salvam/reexecutam uma sequência de análises.
SKILL_TOOLS = names_for_gate("skill")
BROWSER_TOOLS = names_for_gate("browser")

def _do_setor(gate: str) -> set:
    """Ferramentas que o pacote de setor publicou, pelo gate da categoria
    declarada. Sem isso elas existiriam e o Harness recusaria todas."""
    try:
        from ..domains.extensao import para_o_registro
        from ..tools.registry import CATEGORIA_TO_GATE

        return {
            nome for nome, meta in para_o_registro().items()
            if CATEGORIA_TO_GATE.get(meta.get("categoria", ""), "analysis") == gate
        }
    except Exception:
        return set()


ANALYSIS_TOOLS = ANALYSIS_TOOLS | _do_setor("analysis")
ACTION_TOOLS = ACTION_TOOLS | _do_setor("action")
EXPORT_TOOLS = EXPORT_TOOLS | _do_setor("export")
READ_TOOLS = READ_TOOLS | _do_setor("read")
MEMORY_TOOLS = MEMORY_TOOLS | _do_setor("memory")

KNOWN_TOOLS = ANALYSIS_TOOLS | ACTION_TOOLS | EXPORT_TOOLS | READ_TOOLS | MEMORY_TOOLS | SKILL_TOOLS | BROWSER_TOOLS
PROCEDURAL_SKILLS = set()


@dataclass
class HarnessDecision:
    allowed: bool
    reason: str
    missing: List[str]


class SenturyHarness:
    """Camada de política do Sentury Harness: a LLM PROPÕE uma ferramenta, o
    Harness DECIDE se ela pode ser executada. Ferramentas de análise são
    sempre permitidas (só leem o dataset). Renderizar/exportar exige que o
    `source` (ou o último resultado da sessão) aponte para um resultado de
    fato computado por uma ferramenta de análise nesta sessão: nunca um
    número que a LLM tenha inventado."""

    def evaluate(
        self,
        state: AnalysisState,
        tool: str,
        user_message: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> HarnessDecision:
        if tool not in KNOWN_TOOLS and tool not in PROCEDURAL_SKILLS:
            return HarnessDecision(False, f"ferramenta desconhecida: {tool}", ["ferramenta_valida"])

        # Turno de agente residente: só as ferramentas do manifesto dele.
        from ..residentes.escopo import agente_do_turno, pode_usar

        from ..tools.registry import TOOL_REGISTRY, so_residente

        if agente_do_turno() is None and so_residente(TOOL_REGISTRY.get(tool) or {}):
            return HarnessDecision(False, f"'{tool}' só existe no turno de um agente residente",
                                   ["use outra ferramenta da mesa"])
        if not pode_usar(tool):
            agente = agente_do_turno()
            return HarnessDecision(
                False, f"'{tool}' não está entre as ferramentas de {agente.nome if agente else 'o agente'}",
                ["use uma das ferramentas do agente ou diga na resposta o que faltou"],
            )

        # Na pausa de revisão do aprendizado só respondem memória e skill.
        from .aprendizado import ferramentas_da_revisao

        na_revisao = ferramentas_da_revisao()
        if na_revisao is not None and tool not in na_revisao:
            return HarnessDecision(
                False, f"na revisão do aprendizado só respondem: {', '.join(sorted(na_revisao))}",
                ["guarde com uma delas ou termine com 'nada a guardar'"],
            )

        # Gerar imagem é caro e quase nunca é o que "faz um visual" quer dizer.
        # A intenção é uma ATIVAÇÃO visível (badge `@image`), não uma palavra
        # que o texto precisa conter: o usuário liga a função e ela vale até
        # ser desligada. O texto ainda serve de atalho para quem digita.
        if tool == "gerar_imagem":
            from ..tools.imagem import pediu_imagem

            ligada = "image" in (getattr(state, "funcoes_ativas", None) or [])
            if not ligada and not pediu_imagem(user_message):
                return HarnessDecision(
                    False,
                    "geração de imagem exige a função @image ligada; sem ela, pedido de visual é gráfico de dados",
                    ["intencao_declarada"],
                )
            return HarnessDecision(
                True,
                "função @image ligada" if ligada else "imagem pedida explicitamente no texto",
                [],
            )

        # O computer use mexe no mouse e no teclado da pessoa: só com o badge
        # `@computador`. O gesto ainda pede o cartão, no
        # despacho; aqui é só a porta.
        if tool == "computador":
            if "computador" not in (getattr(state, "funcoes_ativas", None) or []):
                return HarnessDecision(
                    False, "o computer use exige a função @computador ligada", ["ligue @computador"])
            return HarnessDecision(True, "função @computador ligada; gestos pedem o cartão", [])

        if tool in ANALYSIS_TOOLS:
            return HarnessDecision(True, "ferramenta de análise, sempre permitida", [])

        if tool in ACTION_TOOLS:
            return HarnessDecision(True, "ferramenta de ação corretiva, sempre permitida", [])

        if tool in READ_TOOLS:
            return HarnessDecision(True, "ferramenta de leitura (conhecimento), sempre permitida", [])

        if tool in MEMORY_TOOLS:
            return HarnessDecision(True, "ferramenta de memória do usuário, sempre permitida", [])

        if tool in SKILL_TOOLS:
            return HarnessDecision(True, "ferramenta de skill, sempre permitida", [])

        if tool in PROCEDURAL_SKILLS:
            return HarnessDecision(True, "skill procedural cadastrada, sempre permitida para carregamento", [])

        if tool in BROWSER_TOOLS:
            return self._evaluate_browser(state, arguments or {})

        # `entregar_arquivo` nao exporta analise: anexa um arquivo que ja existe
        # no disco. O gate de exportacao: que exige um resultado computado
        # para nao gerar planilha de numero inventado: nao se aplica, e
        # bloqueava a entrega do arquivo que o agente acabou de escrever.
        if tool == "entregar_arquivo":
            caminho = str((arguments or {}).get("caminho") or (arguments or {}).get("path") or "").strip()
            if not caminho:
                return HarnessDecision(
                    False, "entregar_arquivo precisa do caminho do arquivo",
                    ["informe `caminho`"],
                )
            return HarnessDecision(True, "entrega de arquivo que ja existe no disco", [])

        return self._evaluate_export(state, arguments or {})

    def _evaluate_browser(self, state: AnalysisState, arguments: Dict[str, Any]) -> HarnessDecision:
        """So o que e estrutural: acao valida e destino publico.

        A autorizacao de acao mutante fica no despacho, que devolve
        `precisa_permissao` como o shell. Recusar aqui virava bloqueio em laco
        e o cartao nunca abria.
        """
        from ..tools.browser_contracts import Action
        from ..tools.web import UrlRecusada, validar_url_do_navegador

        from ..exec.saida import tem_segredo

        try:
            action = Action.de_argumentos(arguments)
            # O roteiro passa pelas mesmas checagens, passo a passo.
            acoes = [action] + action.passos()
        except ValueError as exc:
            return HarnessDecision(False, str(exc), ["acao_de_browser_valida"])
        if action.do_usuario:
            return HarnessDecision(
                False, "isso a pessoa faz: contornar aviso de seguranca, paywall ou troca de senha",
                ["peca para a pessoa fazer este passo"],
            )

        for passo in (a for a in acoes if a.tipo == "navegar"):
            url = str(passo.argumentos.get("url") or "")
            try:
                validar_url_do_navegador(url)
            except UrlRecusada as exc:
                return HarnessDecision(False, f"navegar recusado: {exc}", ["url em http ou https"])
            # Uma URL sugerida por conteúdo externo pode exfiltrar credenciais
            # na própria requisição.
            if tem_segredo(url):
                return HarnessDecision(False, "navegar recusado: a URL carrega o que parece credencial",
                                       ["url sem chave, token ou senha"])

        if action.idempotente:
            return HarnessDecision(True, f"browser.{action.tipo} apenas observa a página", [])
        if not action.pede_autorizacao:
            return HarnessDecision(True, f"browser.{action.tipo} muda a página, não o mundo", [])
        return HarnessDecision(True, f"browser.{action.tipo} segue para a autorização", [])

    def _evaluate_export(self, state: AnalysisState, arguments: Dict[str, Any]) -> HarnessDecision:
        source = arguments.get("source")
        resolved = state.resolve_source(source)

        if resolved is None:
            if source:
                return HarnessDecision(
                    False,
                    "fonte de exportação não encontrada nesta sessão",
                    [f"resultado '{source}' não existe — rode uma análise antes de exportar"],
                )
            return HarnessDecision(
                False,
                "exportação exige um resultado já computado na sessão",
                ["rode uma ferramenta de análise antes de exportar/renderizar"],
            )

        return HarnessDecision(True, f"fonte de exportação validada ({resolved})", [])


sentury_harness = SenturyHarness()
