import hashlib
import re
import logging
import json
from typing import Any, Dict, List, Optional, Tuple
from .state import AnalysisState, ConversationState
from ..llm.action_parser import _strip_reasoning, extract_plain_text

logger = logging.getLogger(__name__)


class CompactacaoIndisponivel(RuntimeError):
    """Sem resumo válido, o histórico original precisa continuar disponível."""

CONTEXTUALIZER_PROMPT = """Você é o Sentury Contextualizer.
Sua responsabilidade é analisar o histórico de mensagens antigo e produzir dois itens consolidados:
1. Um resumo em texto humano (curto, focado no que foi pedido, feito e decidido).
2. Um estado estruturado da conversa em formato JSON contendo o progresso e decisões.

Você deve responder APENAS com um objeto JSON contendo as chaves "human_summary" e "conversation_state".
O "conversation_state" deve possuir a seguinte estrutura:
{
  "historical_goal": "Objetivo antigo da conversa que já foi consolidado/resolvido (ou null)",
  "historical_completed_tasks": ["Lista de tarefas/análises concluídas no passado"],
  "historical_topic": "Assunto antigo em discussão (ou null)",
  "historical_important_decisions": ["Decisões históricas tomadas"],
  "historical_pending_tasks": ["Tarefas pendentes antigas que NÃO devem ser reiniciadas automaticamente"],
  "known_entities": {"entidades_mencionadas": "valor"},
  "user_preferences": {"preferencias_do_usuario": "valor"}
}

### DIRETRIZES (o resumo não pode envelhecer mal):
- Não copie valores medidos (números, porcentagens, contagens, datas de dado) para o "human_summary" nem para o "conversation_state". Valor envelhece; o turno seguinte deve buscá-lo de novo na fonte.
- Não fixe o recorte no "human_summary": descreva o papel do que estava em foco, não o nome dele. O nome, quando importar, vai em "known_entities".
- Registre o que foi pedido, o que foi feito e o que foi decidido. Não registre conclusões sobre o dado.
- Seja curto e direto.
"""

class Contextualizer:
    def __init__(self, llm_chain):
        self.llm = llm_chain

    async def summarize_and_extract(
        self, messages: List[Dict[str, str]], current_state: Optional[ConversationState] = None
    ) -> Tuple[str, ConversationState]:
        """Chama a LLM para sumarizar a conversa anterior e extrair o estado estruturado."""
        prompt = CONTEXTUALIZER_PROMPT
        if current_state:
            # Converte para a nomenclatura histórica esperada pela LLM
            ref_dict = {
                "historical_goal": current_state.current_goal,
                "historical_completed_tasks": current_state.completed_tasks,
                "historical_topic": current_state.current_topic,
                "historical_important_decisions": current_state.important_decisions,
                "historical_pending_tasks": current_state.pending_tasks,
                "known_entities": current_state.known_entities,
                "user_preferences": current_state.user_preferences
            }
            prompt += f"\nEstado atual da conversa anterior para referência:\n{json.dumps(ref_dict, ensure_ascii=False, indent=2)}"

        history_str = ""
        for m in messages:
            role = m.get("role", "").upper()
            content = m.get("content", "")
            history_str += f"{role}: {content}\n"

        messages_to_send = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Histórico a consolidar:\n{history_str}"}
        ]

        try:
            try:
                # #8 + #2: resumir turno antigo é tarefa lateral — vai no modelo
                # rápido/barato (complexity=SIMPLE faz o roteador preferir os fast
                # providers), reservando o modelo bom pra resposta ao usuário.
                raw = await self.llm.complete(messages_to_send, temperature=0.1, complexity="SIMPLE")
            except TypeError:
                raw = await self.llm.complete(messages_to_send)
            cleaned = _strip_reasoning(raw).strip()
            try:
                if "{" in cleaned and "}" in cleaned:
                     json_str = cleaned[cleaned.find("{"):cleaned.rfind("}")+1]
                     data = json.loads(json_str)
                else:
                    raise ValueError("Resposta não contém JSON")
                
                human_summary = data.get("human_summary", cleaned)
                state_data = data.get("conversation_state", {})
                
                new_state = ConversationState(
                    current_goal=state_data.get("historical_goal") or state_data.get("current_goal"),
                    completed_tasks=list(state_data.get("historical_completed_tasks") or state_data.get("completed_tasks", [])),
                    current_topic=state_data.get("historical_topic") or state_data.get("current_topic"),
                    important_decisions=list(state_data.get("historical_important_decisions") or state_data.get("important_decisions", [])),
                    pending_tasks=list(state_data.get("historical_pending_tasks") or state_data.get("pending_tasks", [])),
                    known_entities=dict(state_data.get("known_entities", {})),
                    user_preferences=dict(state_data.get("user_preferences", {}))
                )
                return human_summary, new_state
            except Exception:
                logger.info("Retorno do Contextualizer não é JSON estruturado. Tratando como resumo em texto puro.")
                return cleaned, current_state or ConversationState()
        except Exception as exc:
            raise CompactacaoIndisponivel("Não foi possível consolidar o histórico.") from exc

_TOOL_RE = re.compile(r'RESULTADO DA FERRAMENTA "([a-z_]+)"', re.I)
# Resultado que é o material do trabalho, e não uma leitura de passagem (a
# resposta de um colega que ainda vai ser juntada): a poda não o resume.
MANTER_INTEIRO = "manter_inteiro"
_ID_RE = re.compile(r"ID DO RESULTADO NA SESSÃO: '([^']+)'")
_NUMPY_RE = re.compile(r"np\.\w+\(([^)]*)\)")
_RASCUNHO_RE = re.compile(r"O texto inteiro está em `([^`]+)`")
# Captura pares escalares de qualquer ferramenta, sem depender de um setor.
_PAR = re.compile(
    r"""['"]([A-Za-z]\w*)['"]\s*:\s*(np\.\w+\([^)]*\)|-?\d[\d.eE+-]*|True|False|true|false|'[^'\n]{1,40}'|"[^"\n]{1,40}")"""
)


def _assinatura_resultado(content: str) -> str:
    """Identidade do resultado, pra reconhecer a MESMA leitura repetida."""
    m = _TOOL_RE.search(content or "")
    corpo = re.sub(r"\s+", " ", (content or ""))[:600]
    return f"{m.group(1) if m else '?'}|{hashlib.sha1(corpo.encode('utf-8', 'replace')).hexdigest()[:12]}"


def summarize_tool_result(content: str, max_campos: int = 6) -> str:
    """Resultado antigo vira uma linha que AINDA informa.

    O corte por caractere podia levar embora exatamente os numeros; aqui eles
    sao o que fica.
    """
    m = _TOOL_RE.search(content or "")
    tool = m.group(1) if m else "ferramenta"
    achados = []
    vistos = set()
    for campo, valor in _PAR.findall(content or ""):
        if campo in vistos:
            continue
        vistos.add(campo)
        # `np.float64(-31.2)` é ruído do pandas: o número é o que interessa, e
        # o embrulho ainda custa token toda vez que o resumo é reenviado.
        valor = _NUMPY_RE.sub(r"\1", valor).strip("'\"")
        if valor in ("None", "nan", ""):
            continue
        achados.append(f"{campo}={valor}")
        if len(achados) >= max_campos:
            break
    resumo = " · ".join(achados) if achados else "resultado obtido"
    # O ID sobrevive ao resumo: e por ele que o agente pede o detalhe de volta,
    # e e ele que sustenta a proveniencia na resposta ("fonte: resultado_004").
    ident = _ID_RE.search(content or "")
    cabeca = f"ID DO RESULTADO NA SESSÃO: '{ident.group(1)}'\n" if ident else ""
    # Resultado grande já foi guardado inteiro no rascunho; sem o caminho, o
    # único jeito de rever o detalhe seria rodar a ferramenta de novo.
    rascunho = _RASCUNHO_RE.search(content or "")
    onde = (f"O texto inteiro continua em `{rascunho.group(1)}` (leia trechos com `ler_arquivo`).\n"
            if rascunho else "")
    return (
        f'{cabeca}RESULTADO DA FERRAMENTA "{tool}" (resumido para poupar contexto): {resumo}\n'
        f"{onde}[detalhe completo omitido; os valores acima são os do resultado real]"
    )


class ContextBudgetManager:
    def __init__(self, contextualizer: Contextualizer, limit_chars: int = 60000, keep_last_n: int = 12, limit_messages: int = 30, tool_budget_chars: int = 4000):
        self.contextualizer = contextualizer
        self.limit_chars = limit_chars
        self.keep_last_n = keep_last_n
        self.limit_messages = limit_messages
        self.tool_budget_chars = tool_budget_chars

    @staticmethod
    def _inicio_do_turno(history: List[Dict[str, str]]) -> Optional[int]:
        """Índice da última pergunta do usuário. O que vem depois é o turno
        corrente — o dado com que ele está trabalhando agora.

        Devolve None quando não há pergunta nenhuma no histórico (a antiga já
        saiu numa compactação, por exemplo). Tratar isso como "corte no zero"
        protegeria o histórico inteiro e a poda voltaria a economizar nada.
        """
        for i in range(len(history) - 1, -1, -1):
            if history[i].get("role") == "user":
                return i
        return None

    def prune_tool_outputs(self, history: List[Dict[str, str]],
                           proteger_ultimos: int = 2) -> List[Dict[str, str]]:
        """Primeira etapa da compactação: barata, determinística, antes de gastar LLM.

        Resultado de ferramenta ANTIGO vira uma linha que ainda informa
        (`[analyze_nps] regiao=Sudeste · nps=-49.3 · volume=2009`) em vez de
        um corte cego no meio do texto. Num produto de análise isso importa: o
        valor está nos NÚMEROS, e cortar por caractere pode remover justo eles.

        O que fica inteiro é o **turno corrente**: os resultados que vieram
        depois da última pergunta. Resultado de turno anterior já foi lido e
        já virou texto na resposta do assistente — a conclusão está lá, e o
        bruto vira uma segunda cópia paga por token, a cada turno, para sempre.

        Antes a proteção era por contagem (os 6 últimos) somada a um teto de
        tamanho: numa conversa comum isso protegia TODOS os resultados e o teto
        nunca era atingido, então a poda economizava exatamente zero. O
        `proteger_ultimos` continua como piso, para a conversa que ainda não
        tem um turno fechado.

        Resultado repetido (mesma ferramenta, mesmo conteúdo) some — mantendo o
        mais novo. O ID sobrevive ao resumo, então o detalhe pode ser pedido de
        volta.
        """
        indices_tool = [i for i, m in enumerate(history)
                        if m.get("role") == "system" and "RESULTADO DA FERRAMENTA" in (m.get("content") or "")]
        corte = self._inicio_do_turno(history)
        protegidos = {i for i in indices_tool if i >= corte} if corte is not None else set()
        if proteger_ultimos:
            protegidos |= set(indices_tool[-proteger_ultimos:])
        protegidos |= {i for i in indices_tool if history[i].get(MANTER_INTEIRO)}

        # As assinaturas protegidas entram ANTES do laço: quem sobrevive inteiro
        # é sempre o mais recente, então a cópia antiga idêntica pode sair. Se
        # eu só fosse acumulando na ordem, a antiga seria vista primeiro e viraria
        # resumo — sobrando duas versões da mesma leitura.
        vistos: set = {_assinatura_resultado(history[i].get("content", "")) for i in protegidos}
        saida: List[Dict[str, str]] = []
        for i, m in enumerate(history):
            content = m.get("content", "")
            if i not in indices_tool or i in protegidos:
                saida.append(m)
                continue

            assinatura = _assinatura_resultado(content)
            if assinatura in vistos:
                # Mesma leitura de novo: a versão que ficou inteira basta.
                continue
            vistos.add(assinatura)
            saida.append({**m, "content": summarize_tool_result(content)})
        return saida

    # Quanto o preservado pode ocupar depois de compactar. O resto do orçamento
    # fica para o turno que vem — que é o motivo de ter compactado.
    FRACAO_PRESERVADA = 0.25

    def _cortar_por_tamanho(self, recentes: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Preserva as mensagens mais novas até caber no teto de caracteres.

        Percorre de trás para frente: a última mensagem é a que a resposta
        precisa, e é a única que nunca cai.
        """
        teto = int(self.limit_chars * self.FRACAO_PRESERVADA)
        mantidas: List[Dict[str, str]] = []
        usado = 0
        for mensagem in reversed(recentes):
            tamanho = len(str(mensagem.get("content") or ""))
            if mantidas and usado + tamanho > teto:
                break
            mantidas.insert(0, mensagem)
            usado += tamanho
        return mantidas

    def calculate_usage(self, history: List[Dict[str, str]]) -> int:
        """Calcula o consumo atual em caracteres do histórico."""
        return sum(len(m.get("content", "")) for m in history)

    def get_status(self, usage: int) -> str:
        pct = (usage / self.limit_chars) * 100
        if pct < 60:
            return "OK"
        elif pct < 75:
            return "MONITOR"
        elif pct < 85:
            return "WARN"
        elif pct < 95:
            return "COMPACT"
        else:
            return "AGGRESSIVE_COMPACT"

    async def _resumir_com_diario(self, state: AnalysisState, a_compactar: List[Dict[str, Any]]):
        """O resumo, reaproveitado quando ja existe e gravado assim que sai.

        Sem diario, o unico jeito de nao perder era torcer para o usuario nao
        apertar stop. Falha do diario NAO derruba a compactacao: perder o
        reaproveitamento e barato, perder o turno nao.
        """
        from .compactacao_persistente import (
            CompactacaoEmAndamento, DiarioDeCompactacao, hash_do_contexto,
        )

        sessao = str(getattr(state, "session_id", "") or "")
        diario = None
        identidade = ""
        if sessao:
            try:
                diario = DiarioDeCompactacao()
                identidade = hash_do_contexto(a_compactar)
                guardada = diario.recuperar(sessao, identidade)
                if guardada is not None:
                    logger.info("Compactacao reaproveitada do diario (sem chamar o modelo).")
                    return guardada.estado_conversa.get("human_summary", ""), state.conversation_state
            except Exception:
                logger.debug("Diario de compactacao indisponivel", exc_info=True)
                diario = None

        if diario is None:
            return await self.contextualizer.summarize_and_extract(
                a_compactar, state.conversation_state
            )

        try:
            with diario.lease(sessao) as posse:
                resumo, estado = await self.contextualizer.summarize_and_extract(
                    a_compactar, state.conversation_state
                )
                # Sincrono de proposito: entre o retorno do modelo e esta linha
                # nao ha `await`, entao o cancelamento nao cabe no meio.
                diario.salvar(posse, identidade, a_compactar,
                              {"human_summary": resumo})
                return resumo, estado
        except CompactacaoEmAndamento:
            # Outro turno esta compactando esta sessao. Esperar seria travar a
            # conversa; a compactação deste turno não pode bloquear o outro.
            logger.info("Outra compactacao da mesma sessao ja esta em andamento.")
            return await self.contextualizer.summarize_and_extract(
                a_compactar, state.conversation_state
            )

    @staticmethod
    def falas(historico: List[Dict[str, Any]]) -> int:
        return sum(1 for m in historico if m.get("role") in ("user", "assistant"))

    async def manage(self, state: AnalysisState, progress_cb=None, forcar: bool = False) -> bool:
        """Monitora o tamanho do histórico no estado e compacta progressivamente se necessário.
        Retorna True se houve compactação.

        `forcar` pula a régua de uso: é para quando TODOS os provedores já
        recusaram o pedido por tamanho (ver harness/pedido_grande.py). A régua
        conta caracteres e o provedor conta tokens; os dois discordam, e quem
        manda é quem recusou."""
        # 1. Prune determinístico de ferramentas primeiro
        state.history = self.prune_tool_outputs(state.history)

        usage = self.calculate_usage(state.history)
        status = self.get_status(usage)

        # O teto por quantidade conta as falas, da pessoa e do agente. Cada
        # resultado de ferramenta também é mensagem, e contá-los fazia uma
        # conversa com ferramentas compactar a cada três turnos com o contexto
        # longe do teto de caracteres, que é o que importa.
        falas = self.falas(state.history)
        if falas > self.limit_messages:
            status = "COMPACT"

        logger.info("Uso de contexto: %d/%d chars (%.1f%%), %d/%d falas - Status: %s",
                    usage, self.limit_chars, (usage / self.limit_chars) * 100,
                    falas, self.limit_messages, status)

        if not forcar and status in ("OK", "MONITOR", "WARN"):
            # Apenas monitoramos ou registramos log
            return False

        # Depois de uma falha, tentar de novo na mensagem seguinte repetia a
        # mesma chamada que acabou de falhar, com o aviso na tela, a cada turno.
        # Espera a conversa crescer meia janela; `forcar` passa por cima.
        falhou_com = getattr(state, "compactacao_falhou_com", None)
        if not forcar and falhou_com is not None and falas < falhou_com + max(1, self.keep_last_n // 2):
            return False

        # Compactação é necessária (COMPACT ou AGGRESSIVE_COMPACT)
        if len(state.history) <= self.keep_last_n:
            logger.warning("Histórico curto mas com volume alto. Nenhuma compactação realizada para manter as últimas mensagens.")
            return False

        # Compactar leva alguns segundos e, em silencio, o turno parecia
        # travado. O aviso vem depois das guardas: so anuncia o que vai fazer.
        if progress_cb:
            try:
                progress_cb({"type": "stage", "text": "Compactando a conversa para caber no contexto…"})
            except Exception:
                pass

        logger.info("Iniciando compactação progressiva do histórico...")
        antes = len(state.history)
        # Divide em histórico antigo a compactar e mensagens recentes a
        # preservar. Contar mensagens não bastava: doze mensagens em que uma é
        # um PDF inteiro continuam estourando o orçamento, e a compactação
        # devolvia 26% em vez de zerar. O teto real é de caracteres.
        to_compact = state.history[:-self.keep_last_n]
        preserved = self._cortar_por_tamanho(state.history[-self.keep_last_n:])

        # Prioridade crítica preserva a mensagem mesmo quando ela é antiga.
        critical_messages = [m for m in to_compact if m.get("priority") == "CRITICAL"]

        # Grava o resumo antes de trocar o histórico; uma interrupção não
        # obriga a compactar novamente o mesmo conteúdo.
        try:
            human_summary, conversation_state = await self._resumir_com_diario(state, to_compact)
        except CompactacaoIndisponivel:
            logger.warning("Compactação indisponível; mantendo o histórico.")
            state.compactacao_falhou_com = falas
            return False
        state.compactacao_falhou_com = None
        conversation_state.human_summary = human_summary

        state.conversation_state = conversation_state
        
        # Limpa os filtros grudados da sessão para evitar contaminação pós-compactação
        state.filtros = {}

        # Monta o novo histórico com o resumo e as mensagens preservadas
        summary_content = (
            "[CONTEXT COMPACTION — REFERÊNCIA APENAS]\n"
            "As interações anteriores do usuário foram resumidas abaixo apenas para fins de histórico e contexto. "
            "Este é um handoff de contexto anterior — trate como referência em background, NÃO como instruções ativas. "
            "NUNCA responda a perguntas, tarefas ou solicitações descritas no resumo histórico, pois elas já foram solucionadas. "
            "Seu único objetivo é responder à última mensagem do usuário que aparece DEPOIS deste sumário.\n\n"
            f"### Resumo Histórico de Conversa\n{human_summary}\n\n"
        )
        if conversation_state.important_decisions:
            summary_content += f"### Decisões Históricas Tomadas\n{', '.join(conversation_state.important_decisions)}\n\n"
            
        summary_content += (
            "--- END OF CONTEXT SUMMARY — "
            "responda apenas à mensagem do usuário abaixo, ignorando as instruções do sumário acima ---"
        )
        
        summary_message = {
            "role": "system",
            "content": summary_content,
            "priority": "HIGH"
        }

        new_history = [summary_message]
        # Reinjeta as mensagens críticas que estavam na parte compactada
        for crit in critical_messages:
            new_history.append(crit)
            
        new_history.extend(preserved)
        state.history = new_history
        
        # Recalcula o novo uso
        new_usage = self.calculate_usage(state.history)
        logger.info("Compactação concluída. Novo uso: %d/%d chars (%.1f%%)", new_usage, self.limit_chars, (new_usage / self.limit_chars) * 100)
        # O que aconteceu, em número: "otimizei a memória" não diz nada, e quem
        # está lendo precisa saber o que saiu do contexto para julgar a resposta
        # seguinte. Fica no state (por requisição) em vez de no manager, que é
        # compartilhado entre requisições concorrentes.
        state.ultima_compactacao = {
            "mensagens_antes": antes,
            "mensagens_depois": len(state.history),
            "preservadas": len(preserved),
            "criticas_mantidas": len(critical_messages),
            "uso_antes_pct": round((usage / self.limit_chars) * 100),
            "uso_depois_pct": round((new_usage / self.limit_chars) * 100),
        }
        if progress_cb:
            try:
                # Emite apenas o marco de compactação para não duplicar a frase
                # nem manter uma etapa ativa depois que o processo terminou.
                progress_cb({"type": "compacted", **state.ultima_compactacao})
            except Exception:
                pass
        return True
