import logging
import json
import hashlib
from copy import deepcopy
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_EXPERIENCE_KEY = "sentury:experiences"
_EXPERIENCE_TTL = 10 * 365 * 24 * 60 * 60

# Nao ha experiencia pre-gravada no MOTOR. Eram tres fluxos de CX
# (`analyze_nps` -> `analyze_tickets` -> `correlate` -> `root_cause`,
# "investigacao de queda de NPS cruzando com backlog de chamados"), com
# confianca 0.95 e frequencia 12: numeros inventados para parecer experiencia
# vivida. Duas consequencias: o generalista recebia sugestao de fluxo com
# ferramentas que nao existem para ele, que e o mesmo mecanismo que queimava
# volta do laco no catalogo; e a biblioteca comecava mentindo sobre o que ja
# tinha dado certo nesta instalacao.
#
# Pacote que queira semear experiencia declara no `pack.yaml`; o que se aprende
# aqui vem de turno que aconteceu.
DEFAULT_EXPERIENCES: List[Dict[str, Any]] = []

class ExperienceLibrary:
    def __init__(self, session_store=None):
        self.session_store = session_store
        self._local_experiences: List[Dict[str, Any]] = deepcopy(DEFAULT_EXPERIENCES)
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.session_store:
            return
        try:
            stored = await self.session_store.get(_EXPERIENCE_KEY)
        except Exception as exc:
            logger.warning("Falha ao carregar experiências persistidas: %s", exc)
            return
        experiences = stored.get("experiences") if isinstance(stored, dict) else None
        if isinstance(experiences, list):
            clean = [item for item in experiences if isinstance(item, dict)]
            if clean:
                self._local_experiences = clean

    async def _persist(self) -> None:
        if not self.session_store:
            return
        try:
            await self.session_store.set(
                _EXPERIENCE_KEY,
                {"schema_version": 1, "experiences": self._local_experiences},
                hot_ttl=_EXPERIENCE_TTL,
                warm_ttl=_EXPERIENCE_TTL,
            )
        except Exception as exc:
            logger.warning("Falha ao persistir biblioteca de experiências: %s", exc)

    def _hash_experience(self, exp: Dict[str, Any]) -> str:
        serialized = json.dumps(exp, sort_keys=True)
        return hashlib.md5(serialized.encode("utf-8")).hexdigest()

    async def save(
        self,
        intent: str,
        flow: List[str],
        success: bool = True,
        confidence: float = 1.0,
        user_message: Optional[str] = None
    ) -> None:
        """Salva uma nova estratégia bem-sucedida na biblioteca de experiências."""
        await self._ensure_loaded()
        new_exp = {
            "intent": intent,
            "flow": flow,
            "tools": flow,
            "rags": [],
            "success": success,
            "frequency": 1,
            "confidence": confidence,
            "user_message": user_message
        }
        
        # Procura se já existe um fluxo igual para incrementar frequência
        for exp in self._local_experiences:
            if exp["intent"] == intent and exp["flow"] == flow:
                exp["frequency"] += 1
                exp["success"] = (exp["success"] and success) or success
                exp["confidence"] = (exp["confidence"] + confidence) / 2
                if user_message and not exp.get("user_message"):
                    exp["user_message"] = user_message
                logger.info("Experiência existente atualizada: %s (frequência: %d)", intent, exp["frequency"])
                await self._persist()
                return

        self._local_experiences.append(new_exp)
        logger.info("Nova experiência salva na biblioteca: %s -> %s", intent, flow)

        await self._persist()

    # Abaixo disso a semelhança é uma palavra solta em comum.
    _CORTE_DA_BUSCA = 0.15

    async def buscar(self, consulta: str, k: int = 2) -> List[Dict[str, Any]]:
        """Pedidos parecidos já resolvidos aqui: o pedido e as ferramentas, em ordem.

        Mesma busca por radical do manual, sem depender da intenção nem de
        lista de palavras de uma língua. Entra no `buscar_conhecimento` como a
        terceira fonte, ao lado do manual e da base de conceitos.
        """
        await self._ensure_loaded()
        casos = [e for e in self._local_experiences
                 if e.get("success") and e.get("user_message") and e.get("flow")]
        if not casos or not str(consulta or "").strip():
            return []
        from ..knowledge.manual import _radicais
        from ..knowledge.retriever import _LexicalBackend

        busca = _LexicalBackend([{"id": str(i), "titulo": "", "texto": _radicais(e["user_message"])}
                                 for i, e in enumerate(casos)])
        saida = []
        for achado in busca.search(_radicais(consulta), k):
            if achado["score"] < self._CORTE_DA_BUSCA:
                continue
            caso = casos[int(achado["id"])]
            vezes = int(caso.get("frequency") or 1)
            saida.append({
                "id": f"experiencia:{achado['id']}",
                "titulo": "Pedido parecido já resolvido aqui",
                "texto": (f"Pedido: {str(caso['user_message'])[:300]}\n"
                          f"Ferramentas, em ordem: {' -> '.join(caso['flow'])}\n"
                          f"Deu certo {vezes} {'vez' if vezes == 1 else 'vezes'}."),
                "fonte": "experiencia",
                "relacionados": [f"ferramenta:{f}" for f in dict.fromkeys(caso["flow"])],
                "score": achado["score"],
            })
        return saida

    async def find_similar(self, intent: str, user_message: str) -> Optional[Dict[str, Any]]:
        """Busca uma experiência semelhante com base no intent e palavras-chave da mensagem."""
        await self._ensure_loaded()
        candidates = [e for e in self._local_experiences if e["intent"] == intent and e["success"]]
        if not candidates:
            return None

        # Filtro de stopwords básicas para extrair palavras significativas
        stopwords = {
            "o", "a", "os", "as", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
            "com", "que", "se", "um", "uma", "para", "ou", "por", "como", "isso", "esta", "este",
            "esse", "essa", "ter", "tem", "ser", "é", "são", "foi", "qual", "quais", "quem", "ele", "ela"
        }
        
        def _get_significant_words(text: str) -> set[str]:
            words = text.lower().replace("?", "").replace(".", "").replace(",", "").split()
            return {w for w in words if w not in stopwords and len(w) > 1}

        query_words = _get_significant_words(user_message)
        if not query_words:
            return None

        scored_candidates = []
        for exp in candidates:
            exp_text = exp.get("user_message") or exp.get("description") or ""
            exp_words = _get_significant_words(exp_text)
            
            # Calcula interseção de palavras significativas
            common = query_words.intersection(exp_words)
            score = len(common)
            
            if score >= 2: # Exige pelo menos 2 palavras significativas em comum para evitar falsos positivos
                scored_candidates.append((exp, score))

        if not scored_candidates:
            logger.info("Nenhuma experiência com correspondência de palavras-chave suficiente encontrada para a intenção %s.", intent)
            return None

        # Ordena pelo score de palavras comuns, depois confiança e frequência
        scored_candidates.sort(key=lambda x: (x[1], x[0]["confidence"], x[0]["frequency"]), reverse=True)
        best_match = scored_candidates[0][0]
        logger.info(
            "Experiência semelhante encontrada com score %d de palavras para a intenção %s: %s",
            scored_candidates[0][1], intent, best_match["flow"]
        )
        return best_match
