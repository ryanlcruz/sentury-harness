import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

from .local_session_store import LocalSessionStore

logger = logging.getLogger(__name__)


class InMemorySessionStore:
    """Em memoria: nao persiste entre restarts. Serve teste e uso efemero."""

    def __init__(self):
        self.backend_name = "memory"
        # Armazena (expires_at, value)
        self._hot_data: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._warm_data: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        # Tenta obter do Hot Cache
        hot_entry = self._hot_data.get(session_id)
        if hot_entry:
            expires_at, value = hot_entry
            if time.time() <= expires_at:
                logger.info("Hot Cache hit (InMemory) para a sessão %s", session_id)
                return value
            else:
                self._hot_data.pop(session_id, None)

        # Se não achar no Hot, tenta no Warm Cache (Context Recovery)
        warm_entry = self._warm_data.get(session_id)
        if warm_entry:
            expires_at, value = warm_entry
            if time.time() <= expires_at:
                logger.info("Warm Cache hit / Context Recovery (InMemory) para a sessão %s", session_id)
                # Retorna apenas o estado de conversa encapsulado em um dict de estado vazio
                return {
                    "session_id": session_id,
                    "user_id": value.get("user_id", ""),
                    "conversation_state": value.get("conversation_state", {}),
                    "recovered": True
                }
            else:
                self._warm_data.pop(session_id, None)
        return None

    async def set(self, session_id: str, value: Dict[str, Any], hot_ttl: int = 1800, warm_ttl: int = 604800) -> None:
        now = time.time()
        # Salva no Hot Cache (tamanho completo)
        self._hot_data[session_id] = (now + hot_ttl, value)
        
        # Salva no Warm Cache (apenas dados essenciais de contexto)
        warm_value = {
            "user_id": value.get("user_id"),
            "conversation_state": value.get("conversation_state", {})
        }
        self._warm_data[session_id] = (now + warm_ttl, warm_value)

    async def delete(self, session_id: str) -> None:
        self._hot_data.pop(session_id, None)
        self._warm_data.pop(session_id, None)


# A sessão fica local por padrão; o backend pode ser trocado explicitamente.
SESSION_BACKENDS = {
    "local": lambda s: LocalSessionStore(getattr(s, "SENTURY_HOME", "")),
    "memory": lambda s: InMemorySessionStore(),
}


def get_session_store(settings):
    escolhido = (getattr(settings, "SENTURY_SESSION_BACKEND", "") or "").strip().lower()
    escolhido = escolhido or "local"
    fabrica = SESSION_BACKENDS.get(escolhido)
    if fabrica is None:
        raise ValueError(
            f"SENTURY_SESSION_BACKEND='{escolhido}' desconhecido. "
            f"Opções: {', '.join(sorted(SESSION_BACKENDS))}."
        )
    logger.info("Sentury Memory: backend de sessão '%s'.", escolhido)
    return fabrica(settings)

