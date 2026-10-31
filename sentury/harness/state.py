import time
import base64
from pathlib import Path
import unicodedata
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4


_TRANSIENT_FAILURE_HINTS = (
    "no momento nao consegui acessar os provedores de ia",
    "provedores de ia para montar esta resposta",
    "verifique as chaves de llm",
    "modo super maxima tentou apenas os modelos ultra",
    "modo ultra tentou apenas os modelos ultra",
    "nao usei fallback gratis",
    "desculpe, tive um problema ao processar a resposta",
)

_ATTACHMENT_PAYLOAD_KEYS = {
    "content_base64",
    "verified_preview_base64",
    "content",
    "chart_data",
}


def sanitize_attachment_for_history(attachment: Any) -> Optional[Dict[str, Any]]:
    """Keep artifact metadata in chat history without binary/text payloads.

    Full payloads are returned in the live response. Persisted conversation
    history should never carry base64 or large artifact bodies because old
    sessions and background tasks may stringify it and poison later turns.
    """
    if not isinstance(attachment, dict):
        return None
    clean = {
        key: value
        for key, value in attachment.items()
        if key not in _ATTACHMENT_PAYLOAD_KEYS and not str(key).startswith("_")
    }
    if not clean:
        return None
    clean["payload_persisted"] = bool(clean.get("artifact_id"))
    return clean


def _norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return text.encode("ascii", "ignore").decode("ascii").lower()


def is_transient_failure_message(message: Dict[str, Any]) -> bool:
    if not isinstance(message, dict):
        return False
    if message.get("transient_error") or message.get("ephemeral_error"):
        return True
    meta = message.get("metadata")
    if isinstance(meta, dict) and (meta.get("transient_error") or meta.get("ephemeral_error")):
        return True
    if message.get("role") != "assistant":
        return False
    content = _norm_text(message.get("content"))
    return any(hint in content for hint in _TRANSIENT_FAILURE_HINTS)


@dataclass
class ConversationState:
    """Estado estruturado da conversa, usado para manter contexto consolidado de longo prazo."""
    current_goal: Optional[str] = None
    completed_tasks: List[str] = field(default_factory=list)
    current_topic: Optional[str] = None
    important_decisions: List[str] = field(default_factory=list)
    pending_tasks: List[str] = field(default_factory=list)
    known_entities: Dict[str, Any] = field(default_factory=dict)
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    human_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationState":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class AnalysisState:
    """Estado da sessão de análise. Persistido no store de sessão (local)
    entre turnos da conversa.

    `results` guarda só a "receita" de cada resultado computado nesta sessão
    (ferramenta + argumentos + resumo + linhas), nunca o DataFrame inteiro:
    pesado demais para serializar a cada turno. Renderizar/exportar um resultado
    recomputa o DataFrame na hora a partir da receita."""

    session_id: str
    user_id: str
    history: List[Dict[str, Any]] = field(default_factory=list)
    filtros: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    artifacts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Imagens deste turno, consumidas ao montar a mensagem do usuario.
    imagens_do_turno: Optional[List[Dict[str, Any]]] = None
    # Passos executados no turno; viram o Processo Analitico persistido.
    processo_do_turno: Optional[List[Dict[str, Any]]] = None
    # O cartao do navegador do turno; o main guarda na mensagem do assistente.
    navegador_do_turno: Optional[Dict[str, Any]] = None
    # O cartão do computer use também vira recibo compacto na mensagem.
    computador_do_turno: Optional[Dict[str, Any]] = None
    # O último print do turno (tela ou página), anexado à chamada seguinte; não é salvo.
    print_da_tela: Optional[Dict[str, Any]] = None
    # Funcoes nativas ligadas pelo usuario (badge `@`), validas neste turno.
    funcoes_ativas: List[str] = field(default_factory=list)
    result_counter: int = 0
    last_result_id: Optional[str] = None
    updated_at: float = field(default_factory=time.time)
    conversation_state: ConversationState = field(default_factory=ConversationState)
    # A tarefa que parou para pedir autorizacao. Sem isto, conceder a
    # permissao deixava o proximo turno sem saber o que retomar.
    tarefa_pendente: Optional[Dict[str, Any]] = None
    # Preenchido só no turno em que houve compactação: o que saiu do contexto,
    # em número, pra UI conseguir dizer mais do que "otimizei a memória".
    ultima_compactacao: Optional[Dict[str, Any]] = None
    # Quantas falas havia quando a compactação falhou: a próxima tentativa
    # espera a conversa crescer, em vez de repetir a cada turno.
    compactacao_falhou_com: Optional[int] = None
    # Voltas com ferramenta desde a última revisão do aprendizado.
    voltas_desde_revisao: int = 0

    def register_result(self, tool: str, arguments: Dict[str, Any], summary: Dict[str, Any], row_count: int) -> str:
        self.result_counter += 1
        result_id = f"resultado_{self.result_counter:03d}"
        self.results[result_id] = {
            "tool": tool,
            "arguments": arguments,
            "summary": summary,
            "row_count": row_count,
            "created_at": time.time(),
        }
        self.last_result_id = result_id
        return result_id

    def resolve_source(self, source: Optional[Any]) -> Optional[str]:
        if source is None:
            candidate = self.last_result_id
            return candidate if candidate and candidate in self.results else None

        if isinstance(source, (list, tuple)):
            for item in source:
                resolved = self.resolve_source(item)
                if resolved:
                    return resolved
            return None

        if isinstance(source, dict):
            for key in ("source", "source_id", "result_id", "id", "tool"):
                resolved = self.resolve_source(source.get(key))
                if resolved:
                    return resolved
            return None

        if not isinstance(source, str):
            return None

        candidate = source.strip()
        if candidate and candidate in self.results:
            return candidate
        if candidate:
            clean_source = candidate.replace("_result", "").strip()
            # Procurar se corresponde ao nome de alguma ferramenta executada nesta sessao (do mais recente ao mais antigo)
            for rid in sorted(self.results.keys(), reverse=True):
                if self.results[rid].get("tool") == clean_source:
                    return rid
        return None


    # Limites de persistência: o histórico cresce a cada turno e é serializado
    # inteiro no store de sessão toda vez. Sem teto, uma única mensagem
    # gigante (ex.: despejo de tabela) ou uma conversa longa estoura o limite de
    # tamanho do registro. Capamos antes de persistir: o contexto da LLM já usa
    # só as últimas 12 mensagens, então cortar o histórico antigo não muda a
    # resposta.
    MAX_HISTORY_MESSAGES = 40
    MAX_MESSAGE_CHARS = 8000

    def prune_transient_failures(self) -> int:
        """Remove transient LLM failure turns so retries do not poison context."""
        remove: set[int] = set()
        for index, message in enumerate(self.history):
            if not is_transient_failure_message(message):
                continue
            remove.add(index)
            cursor = index - 1
            while cursor >= 0 and self.history[cursor].get("role") == "system":
                cursor -= 1
            if cursor >= 0 and self.history[cursor].get("role") == "user":
                remove.add(cursor)
        if not remove:
            return 0
        self.history = [message for index, message in enumerate(self.history) if index not in remove]
        return len(remove)

    def sanitize_history_payloads(self) -> None:
        """Remove heavy artifact payloads from persisted/reloaded history."""
        for message in self.history:
            # Base64 de imagem vale para o turno, nao para o estado persistido:
            # fica a marca do que foi enviado, sem carregar megabytes adiante.
            imagens = message.pop("imagens", None)
            if imagens:
                message["imagens_enviadas"] = [
                    str((item or {}).get("nome") or "imagem") for item in imagens
                ]
            attachment = sanitize_attachment_for_history(message.get("attachment"))
            if attachment:
                message["attachment"] = attachment
            elif "attachment" in message:
                message.pop("attachment", None)

    def migrate_legacy_history_artifacts(self) -> int:
        """Move legacy attachment payloads out of history without losing files.

        Older sessions stored the complete base64/HTML payload directly on the
        assistant message. Stripping it blindly fixes context pollution but
        makes the old download disappear. On the first load, preserve the
        payload in ``artifacts`` and leave only a small reference in history.
        """
        migrated = 0
        for message in self.history:
            attachment = message.get("attachment")
            if not isinstance(attachment, dict) or attachment.get("artifact_id"):
                continue
            if not any(key in attachment for key in _ATTACHMENT_PAYLOAD_KEYS):
                continue
            metadata = self.store_artifact(attachment)
            if metadata:
                message["attachment"] = metadata
                migrated += 1
        return migrated

    def store_artifact(self, attachment: Any) -> Optional[Dict[str, Any]]:
        """Persist an artifact outside LLM-visible chat history.

        Conversation messages retain a small reference. The live API response can
        still deliver the full payload, and a restored session fetches it through
        the artifact endpoint instead of injecting base64 into context.
        """
        if not isinstance(attachment, dict):
            return None
        artifact_id = str(uuid4())
        guardado = deepcopy(attachment)
        if guardado.get("caminho"):
            # O arquivo mora no disco: a sessão não carrega uma cópia em base64.
            guardado.pop("content_base64", None)
            guardado.pop("content", None)
        self.artifacts[artifact_id] = {
            "attachment": guardado,
            "created_at": time.time(),
        }
        metadata = sanitize_attachment_for_history(attachment)
        if not metadata:
            return None
        metadata["artifact_id"] = artifact_id
        metadata["payload_persisted"] = True
        return metadata

    def get_artifact(self, artifact_id: Any) -> Optional[Dict[str, Any]]:
        record = self.artifacts.get(str(artifact_id or ""))
        attachment = record.get("attachment") if isinstance(record, dict) else None
        if not isinstance(attachment, dict):
            return None
        anexo = deepcopy(attachment)
        caminho = anexo.get("caminho")
        if caminho and not anexo.get("content_base64") and not anexo.get("content"):
            try:
                anexo["content_base64"] = base64.b64encode(Path(caminho).read_bytes()).decode("ascii")
            except OSError:
                # Movido ou apagado pela pessoa: o cartão diz onde ele estava.
                anexo["ausente"] = True
        return anexo

    def sanitize_result_payloads(self) -> None:
        """Remove non-recomputable sandbox code from legacy session anchors."""
        stale_ids = [
            result_id
            for result_id, record in self.results.items()
            if isinstance(record, dict) and str(record.get("tool") or "") == "executar_python"
        ]
        for result_id in stale_ids:
            self.results.pop(result_id, None)
        if self.last_result_id not in self.results:
            if self.results:
                self.last_result_id = max(
                    self.results,
                    key=lambda result_id: float((self.results[result_id] or {}).get("created_at") or 0),
                )
            else:
                self.last_result_id = None

    def remove_latest_user_turn(self, user_message: str) -> bool:
        """Drop the latest visible turn when the user asks to regenerate it."""
        target = str(user_message or "")
        for index in range(len(self.history) - 1, -1, -1):
            message = self.history[index]
            if message.get("role") == "user" and str(message.get("content") or "") == target:
                # Sem id do turno, só a última mensagem pode ser substituída
                # sem apagar contexto posterior.
                if any(item.get("role") == "user" for item in self.history[index + 1:]):
                    return False
                del self.history[index:]
                return True
        return False

    def trim_history(self) -> None:
        self.prune_transient_failures()
        self.sanitize_history_payloads()
        self.sanitize_result_payloads()
        for m in self.history:
            conteudo = m.get("content")
            if isinstance(conteudo, str) and len(conteudo) > self.MAX_MESSAGE_CHARS:
                m["content"] = conteudo[: self.MAX_MESSAGE_CHARS] + "… [truncado]"
        if len(self.history) > self.MAX_HISTORY_MESSAGES:
            self.history = self.history[-self.MAX_HISTORY_MESSAGES :]

    def to_dict(self) -> Dict[str, Any]:
        self.updated_at = time.time()
        self.sanitize_history_payloads()
        self.sanitize_result_payloads()
        d = asdict(self)
        d.pop("artifacts", None)
        d.pop("print_da_tela", None)
        d["conversation_state"] = self.conversation_state.to_dict()
        return d

    def to_persisted_dict(self) -> Dict[str, Any]:
        """Serialize durable state, including artifact payloads outside history."""
        self.updated_at = time.time()
        self.sanitize_history_payloads()
        self.sanitize_result_payloads()
        d = asdict(self)
        d["conversation_state"] = self.conversation_state.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisState":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if "conversation_state" in data and isinstance(data["conversation_state"], dict):
            known["conversation_state"] = ConversationState.from_dict(data["conversation_state"])
        else:
            known["conversation_state"] = ConversationState()
        state = cls(**known)
        # Versoes antigas da retomada gravaram uma mensagem artificial da pessoa
        # depois da nota de reinicio. A nota preserva o pedido real: restaura-o
        # tambem no historico antigo, sem alterar mensagens legitimas sem nota.
        for indice, mensagem in enumerate(state.history):
            if mensagem.get("role") != "user" or mensagem.get("content") != "Continue de onde parou.":
                continue
            for anterior in reversed(state.history[:indice]):
                if anterior.get("role") == "user":
                    break
                texto = str(anterior.get("content") or "")
                inicio = "O pedido era: "
                fim = "\n\nO que já tinha rodado:"
                if anterior.get("role") == "system" and texto.startswith("[INSTRUÇÃO DO SISTEMA: O servidor reiniciou") \
                        and inicio in texto and fim in texto:
                    pedido = texto.split(inicio, 1)[1].split(fim, 1)[0].strip()
                    if pedido:
                        mensagem["content"] = pedido
                    break
        state.migrate_legacy_history_artifacts()
        state.sanitize_history_payloads()
        state.sanitize_result_payloads()
        return state

    @classmethod
    def new(cls, session_id: str, user_id: str) -> "AnalysisState":
        return cls(session_id=session_id, user_id=user_id)

