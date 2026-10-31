import hashlib
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional

from ..harness.state import is_transient_failure_message


_INDEX_PREFIX = "__sentury_session_index__"
_ARCHIVE_PREFIX = "__sentury_session_archive__"
_TITLE_CLEAN_RE = re.compile(r"[\x00-\x1f\x7f`*_#>\[\]{}<>|]+")
_SPACE_RE = re.compile(r"\s+")


def _hashed(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:32]


def index_key(user_id: str) -> str:
    return f"{_INDEX_PREFIX}:{_hashed(user_id or 'anon')}"


def archive_key(session_id: str) -> str:
    return f"{_ARCHIVE_PREFIX}:{_hashed(session_id or 'session')}"


def sanitize_title(value: str, max_len: int = 80) -> str:
    text = _TITLE_CLEAN_RE.sub(" ", str(value or ""))
    text = text.replace("\n", " ").replace("\r", " ")
    text = _SPACE_RE.sub(" ", text).strip(" .:-")
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0].strip(" .:-") or text[:max_len].strip(" .:-")
    return text or "Nova conversa"


def clean_ai_title(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^titulo\s*:\s*", "", text, flags=re.I)
    text = text.strip("\"'` \n\r\t")
    text = sanitize_title(text, max_len=72)
    lowered = text.lower()
    if any(marker in lowered for marker in ("nao consegui", "não consegui", "provedores de ia", "limite de uso")):
        return ""
    words = text.split()
    if len(words) > 9:
        text = " ".join(words[:9]).strip(" .:-")
    return text


def visible_messages(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        item for item in history or []
        if item.get("role") in ("user", "assistant") and str(item.get("content") or "").strip()
        and not is_transient_failure_message(item)
    ]


def first_user_message(history: List[Dict[str, Any]]) -> str:
    for item in history or []:
        if item.get("role") == "user":
            return str(item.get("content") or "").strip()
    return ""


def first_assistant_message(history: List[Dict[str, Any]]) -> str:
    for item in history or []:
        if item.get("role") == "assistant" and not is_transient_failure_message(item):
            return str(item.get("content") or "").strip()
    return ""


def user_message_count(history: List[Dict[str, Any]]) -> int:
    return sum(1 for item in history or [] if item.get("role") == "user")


def attachment_count(history: List[Dict[str, Any]]) -> int:
    return sum(1 for item in history or [] if item.get("attachment") and not is_transient_failure_message(item))


def preview_from_history(history: List[Dict[str, Any]], max_len: int = 140) -> str:
    for item in reversed(history or []):
        if item.get("role") not in ("user", "assistant"):
            continue
        if is_transient_failure_message(item):
            continue
        text = _SPACE_RE.sub(" ", str(item.get("content") or "")).strip()
        if text:
            return text[:max_len].strip()
    return ""


_STOP = {
    "o", "a", "os", "as", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "um", "uma", "e", "ou", "que", "com", "por", "para", "pra", "ao", "aos", "se", "me",
    "qual", "quais", "como", "quanto", "quantos", "onde", "quando", "porque", "por que",
    "eu", "voce", "ele", "ela", "isso", "esse", "essa", "mais", "menos", "foi", "esta",
}


def _termos(texto: str) -> set:
    """Palavras significativas, sem acento e sem ruído."""
    t = unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode("ascii")
    return {w for w in re.findall(r"[a-z0-9]{3,}", t) if w not in _STOP}


def search_digest(history: List[Dict[str, Any]], max_chars: int = 1200) -> str:
    """Resumo pesquisável da conversa, montado na hora de INDEXAR.

    O trabalho pesado fica aqui pra busca ser uma leitura só: sem isso, procurar
    exigiria carregar as 80 sessões do usuário e varrer cada uma.

    Prioriza a fala do USUÁRIO: é ela que carrega o assunto ("por que o NPS do
    Sudeste caiu"); a resposta do agente é longa e repete o enunciado.
    """
    partes: List[str] = []
    for m in visible_messages(history):
        conteudo = str(m.get("content") or "").strip()
        if not conteudo:
            continue
        if m.get("role") == "user":
            partes.append(conteudo[:200])
        elif len(partes) and len(" ".join(partes)) < max_chars:
            partes.append(conteudo[:120])
    return " · ".join(partes)[:max_chars]


def derive_session_title(history: List[Dict[str, Any]]) -> str:
    text = first_user_message(history) or preview_from_history(history)
    text = re.sub(r"^/[a-zA-Z0-9_-]+\s*", "", text)
    text = re.sub(r"\b(p|r)\s*:\s*", " ", text, flags=re.I)
    text = sanitize_title(text, max_len=80)
    words = text.split()
    if len(words) > 7:
        text = " ".join(words[:7])
    return sanitize_title(text, max_len=72)


class SessionIndex:
    """Small per-user session index backed by the existing session store."""

    def __init__(self, store: Any, ttl: int = 2592000, max_items: int = 80):
        self.store = store
        self.ttl = ttl
        self.max_items = max_items

    async def list(self, user_id: str) -> List[Dict[str, Any]]:
        raw = await self.store.get(index_key(user_id))
        items = raw.get("sessions", []) if isinstance(raw, dict) else []
        clean = [item for item in items if isinstance(item, dict) and item.get("session_id")]
        clean.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
        return clean[: self.max_items]

    async def get_meta(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        for item in await self.list(user_id):
            if item.get("session_id") == session_id:
                return item
        return None

    async def remember(self, state: Any, title: Optional[str] = None, title_source: Optional[str] = None) -> Dict[str, Any]:
        user_id = getattr(state, "user_id", "") or ""
        session_id = getattr(state, "session_id", "") or ""
        now = time.time()
        items = await self.list(user_id)
        existing = next((item for item in items if item.get("session_id") == session_id), None) or {}
        manual = existing.get("title_source") == "manual"

        if manual and not title:
            final_title = existing.get("title") or derive_session_title(getattr(state, "history", []))
            final_source = "manual"
        else:
            final_title = title or existing.get("title") or derive_session_title(getattr(state, "history", []))
            final_source = title_source or existing.get("title_source") or "auto"

        history = getattr(state, "history", []) or []
        item = {
            "session_id": session_id,
            "user_id": user_id,
            "title": sanitize_title(final_title),
            "title_source": final_source,
            "preview": preview_from_history(history),
            "busca": search_digest(history),
            "created_at": existing.get("created_at") or now,
            "updated_at": getattr(state, "updated_at", None) or now,
            "message_count": len(visible_messages(history)),
            "user_message_count": user_message_count(history),
            "artifact_count": attachment_count(history),
        }
        # De onde a conversa veio sobrevive ao salvamento: o item e remontado
        # a cada turno, e isto e o que conta a historia dela.
        if existing.get("origem_id"):
            item["origem_id"] = existing["origem_id"]

        next_items = [item] + [old for old in items if old.get("session_id") != session_id]
        next_items.sort(key=lambda old: float(old.get("updated_at") or 0), reverse=True)
        next_items = next_items[: self.max_items]
        await self.store.set(
            index_key(user_id),
            {"user_id": user_id, "sessions": next_items},
            hot_ttl=self.ttl,
            warm_ttl=self.ttl,
        )
        await self.store.set(
            archive_key(session_id),
            state.to_persisted_dict() if hasattr(state, "to_persisted_dict") else state.to_dict(),
            hot_ttl=self.ttl,
            warm_ttl=self.ttl,
        )
        return item

    async def search(self, user_id: str, consulta: str, limite: int = 5,
                     excluir: Optional[str] = None) -> List[Dict[str, Any]]:
        """Procura nas conversas ANTERIORES deste usuário.

        Escopo por `user_id` é regra, não detalhe: conversa de um usuário nunca
        pode vazar pra busca de outro. `excluir` tira a sessão corrente, senão o
        agente "encontra" o que acabou de dizer.

        A sobreposição de termos basta para o limite pequeno de sessões por
        usuário; um índice vetorial acrescentaria custo sem necessidade.
        """
        alvo = _termos(consulta)
        if not alvo:
            return []
        achados = []
        for item in await self.list(user_id):
            if excluir and item.get("session_id") == excluir:
                continue
            texto = " ".join(str(item.get(c) or "") for c in ("title", "preview", "busca"))
            termos = _termos(texto)
            comuns = alvo & termos
            if not comuns:
                continue
            achados.append((len(comuns) / len(alvo), item, sorted(comuns)))
        achados.sort(key=lambda x: (-x[0], -float(x[1].get("updated_at") or 0)))
        return [{
            "session_id": it.get("session_id"),
            "titulo": it.get("title"),
            "quando": it.get("updated_at"),
            "relevancia": round(score, 2),
            "casou_em": comuns[:6],
            "trecho": (it.get("busca") or it.get("preview") or "")[:300],
        } for score, it, comuns in achados[:limite]]

    async def load(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        raw = await self.store.get(archive_key(session_id))
        if not isinstance(raw, dict):
            raw = await self.store.get(session_id)
        if not isinstance(raw, dict):
            return None
        owner = raw.get("user_id")
        if owner and user_id and owner != user_id:
            # Quem manda na posse e o indice: se a conversa esta listada para
            # este usuario, o dono gravado no arquivo esta velho.
            if not await self.get_meta(user_id, session_id):
                return None
            raw = {**raw, "user_id": user_id}
            await self.store.set(archive_key(session_id), raw,
                                 hot_ttl=self.ttl, warm_ttl=self.ttl)
        return raw

    async def remove(self, user_id: str, session_id: str) -> bool:
        """Tira a sessao do indice do usuario. Devolve se ela estava la."""
        raw = await self.store.get(index_key(user_id))
        itens = raw.get("sessions", []) if isinstance(raw, dict) else []
        restantes = [i for i in itens if isinstance(i, dict) and i.get("session_id") != session_id]
        if len(restantes) == len(itens):
            return False
        await self.store.set(index_key(user_id), {"sessions": restantes},
                             hot_ttl=self.ttl, warm_ttl=self.ttl)
        return True

    async def rename(self, user_id: str, session_id: str, title: str, source: str = "manual") -> Optional[Dict[str, Any]]:
        raw = await self.load(user_id, session_id)
        if not raw:
            return None
        from ..harness.state import AnalysisState

        state = AnalysisState.from_dict(raw)
        return await self.remember(state, title=sanitize_title(title), title_source=source)
