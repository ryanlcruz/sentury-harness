import logging
import math
import re
import unicodedata
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "e",
    "ou", "que", "com", "sem", "para", "pra", "por", "no", "na", "nos", "nas",
    "em", "ao", "aos", "se", "meu", "minha", "seu", "sua", "como", "qual",
    "quais", "quanto", "quanta", "é", "ser", "tem", "ter", "vai", "the",
}


def _tokenize(text: str) -> List[str]:
    text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")
    tokens = re.findall(r"[a-z0-9]+", text)
    return [t for t in tokens if len(t) > 1 and t not in _STOPWORDS]


class _LexicalBackend:
    """Recuperação léxica TF-IDF + cosseno, em memória e sem dependências.
    Fallback de demo: bom o bastante para uma base de conhecimento pequena."""

    nome = "lexical (demo)"
    _THRESHOLD = 0.04

    def __init__(self, chunks: List[Dict[str, str]]):
        self._chunks = chunks
        self._docs = [_tokenize(c["texto"] + " " + c.get("titulo", "")) for c in chunks]

        df: Dict[str, int] = {}
        for doc in self._docs:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1
        n = max(len(self._docs), 1)
        self._idf = {term: math.log((n + 1) / (freq + 1)) + 1 for term, freq in df.items()}
        self._doc_vecs = [self._vectorize(doc) for doc in self._docs]

    def _vectorize(self, tokens: List[str]) -> Dict[str, float]:
        tf: Dict[str, float] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0.0) + 1.0
        return {t: freq * self._idf.get(t, 0.0) for t, freq in tf.items()}

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    def search(self, query: str, k: int) -> List[Dict[str, str]]:
        qvec = self._vectorize(_tokenize(query))
        scored = [(self._cosine(qvec, dvec), i) for i, dvec in enumerate(self._doc_vecs)]
        scored.sort(reverse=True)
        results = []
        for score, i in scored[:k]:
            if score < self._THRESHOLD:
                break
            results.append({**self._chunks[i], "score": round(score, 4)})
        return results


class _EmbeddingBackend:
    """Recuperação semântica com embeddings ONNX locais (fastembed). Opcional:
    só usada quando habilitada e a lib está instalada; caso contrário cai no
    backend léxico."""

    nome = "embeddings (fastembed)"
    _THRESHOLD = 0.55

    def __init__(self, chunks: List[Dict[str, str]]):
        from fastembed import TextEmbedding  # import tardio: dependência opcional

        self._chunks = chunks
        self._model = TextEmbedding()
        self._doc_vecs = list(self._model.embed([c["texto"] + " " + c.get("titulo", "") for c in chunks]))

    @staticmethod
    def _cosine(a, b) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def search(self, query: str, k: int) -> List[Dict[str, str]]:
        qvec = list(self._model.embed([query]))[0]
        scored = [(self._cosine(qvec, dvec), i) for i, dvec in enumerate(self._doc_vecs)]
        scored.sort(reverse=True)
        results = []
        for score, i in scored[:k]:
            if score < self._THRESHOLD:
                break
            results.append({**self._chunks[i], "score": round(float(score), 4)})
        return results


class _GeminiEmbeddingBackend:
    """Recuperação semântica com embeddings da API Gemini (gemini-embedding-001).
    A cota de embeddings é SEPARADA da de chat (1K RPD própria), então melhora o
    RAG sem roubar cota do agente. Os vetores dos docs são calculados 1x no init
    (batchEmbedContents = 1 chamada). Se o embed da query falhar em runtime, cai
    no léxico interno: nunca deixa o RAG sem resposta."""

    nome = "embeddings (gemini)"
    _THRESHOLD = 0.55
    _BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        chunks: List[Dict[str, str]],
        api_key: str,
        model: str = "gemini-embedding-001",
        runtime_fallback=None,
    ):
        import httpx

        self._chunks = chunks
        self._api_key = (api_key or "").strip()
        self._model = model
        # Runtime fallback preferencial: fastembed opcional quando habilitado;
        # se não existir/estiver desligado, cai no léxico interno.
        self._runtime_fallback = runtime_fallback or _LexicalBackend(chunks)
        self._lexical = _LexicalBackend(chunks)
        texts = [c["texto"] + " " + c.get("titulo", "") for c in chunks]
        # 1 chamada pra todos os docs. Se falhar, propaga → KnowledgeBase cai no
        # próximo backend (não fica sem RAG).
        resp = httpx.post(
            f"{self._BASE}/{self._model}:batchEmbedContents",
            headers={"x-goog-api-key": self._api_key},
            json={"requests": [
                {"model": f"models/{self._model}", "content": {"parts": [{"text": t}]}}
                for t in texts
            ]},
            timeout=30.0,
        )
        resp.raise_for_status()
        self._doc_vecs = [e["values"] for e in resp.json()["embeddings"]]

    def _embed_query(self, query: str) -> List[float]:
        import httpx

        resp = httpx.post(
            f"{self._BASE}/{self._model}:embedContent",
            headers={"x-goog-api-key": self._api_key},
            json={"model": f"models/{self._model}", "content": {"parts": [{"text": query}]}},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()["embedding"]["values"]

    @staticmethod
    def _cosine(a, b) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def search(self, query: str, k: int) -> List[Dict[str, str]]:
        try:
            qvec = self._embed_query(query)
        except Exception as exc:
            logger.warning(
                "Gemini embeddings falhou na query (%s) — usando fallback %s",
                exc,
                getattr(self._runtime_fallback, "nome", "desconhecido"),
            )
            return self._runtime_fallback.search(query, k)
        scored = [(self._cosine(qvec, dvec), i) for i, dvec in enumerate(self._doc_vecs)]
        scored.sort(reverse=True)
        results = []
        for score, i in scored[:k]:
            if score < self._THRESHOLD:
                break
            results.append({**self._chunks[i], "score": round(float(score), 4)})
        return results


class _EmbeddingsDaInstalacao:
    """O modelo de embeddings escolhido na tela, lido a cada busca: trocar na tela vale
    na hora. Desligado ou com o provedor fora, a busca é a léxica."""

    def __init__(self, chunks: List[Dict[str, str]]):
        self._chunks = chunks
        self._lexico = _LexicalBackend(chunks)

    @property
    def nome(self) -> str:
        from ..memory import embeddings

        atual = embeddings.escolha()
        return f"embeddings ({atual['provedor']})" if embeddings.ligado() else self._lexico.nome

    def search(self, query: str, k: int) -> List[Dict[str, str]]:
        from ..memory import embeddings

        acervo = {str(i): f"{c.get('titulo', '')} {c['texto']}" for i, c in enumerate(self._chunks)}
        achados = embeddings.semelhantes(query, acervo, limite=k)
        if achados is None:
            return self._lexico.search(query, k)
        return [{**self._chunks[int(i)], "score": nota} for i, nota in achados]


class KnowledgeBase:
    """RAG leve: indexa a base de conhecimento e recupera os trechos mais
    relevantes para uma pergunta. Usa embeddings quando habilitados, senão
    recuperação léxica. A ferramenta buscar_conhecimento expõe isso à LLM como
    leitura: conteúdo conceitual que não cabe numa consulta de tabela."""

    def __init__(
        self,
        chunks: List[Dict[str, str]],
        use_embeddings: bool = False,
        gemini_api_key: Optional[str] = None,
        gemini_model: str = "gemini-embedding-001",
    ):
        backend = None
        fastembed_backend = None
        if use_embeddings:
            try:
                fastembed_backend = _EmbeddingBackend(chunks)
                logger.info("KnowledgeBase: fastembed disponível como backend/fallback local")
            except Exception as exc:
                logger.warning("KnowledgeBase: fastembed indisponível (%s)", exc)

        # Embeddings Gemini: melhor qualidade que léxico e não precisa instalar
        # nada (cota de embeddings é separada da de chat). Se o batch inicial
        # falhar (429/rede/chave), cai no próximo backend.
        if backend is None and gemini_api_key:
            try:
                backend = _GeminiEmbeddingBackend(
                    chunks,
                    gemini_api_key,
                    gemini_model,
                    runtime_fallback=fastembed_backend,
                )
                logger.info("KnowledgeBase: usando embeddings (gemini)")
            except Exception as exc:
                logger.warning("KnowledgeBase: embeddings Gemini indisponível (%s) — tentando próximo", exc)

        if backend is None and fastembed_backend is not None:
            try:
                backend = fastembed_backend
                logger.info("KnowledgeBase: usando embeddings (fastembed)")
            except Exception as exc:
                logger.warning("KnowledgeBase: fastembed indisponível (%s) — usando backend léxico", exc)

        if backend is None:
            backend = _EmbeddingsDaInstalacao(chunks)

        self._backend = backend

    @property
    def modo(self) -> str:
        return self._backend.nome

    def buscar(self, query: str, k: int = 3) -> List[Dict[str, str]]:
        if not query or not query.strip():
            return []
        return self._backend.search(query, k)


def get_knowledge_base(settings) -> Optional[KnowledgeBase]:
    from .faq import FAQ_SENTURY

    # O corpus do motor mais o que o SETOR declara. Sem isto, perguntar "o que
    # voce consegue analisar?" num pacote de e-commerce devolvia a descricao de
    # outro produto.
    corpus = list(FAQ_SENTURY)
    try:
        from ..domains.registry import get_active_domain

        corpus += list(getattr(get_active_domain(), "conhecimento", ()) or ())
    except Exception:
        logger.debug("Conhecimento do setor nao foi lido", exc_info=True)

    # O modelo de embeddings é um só para a instalação (memory/embeddings.py): a escolha
    # da tela, ou a do `.env` enquanto não há escolha. A base segue o mesmo.
    return KnowledgeBase(corpus)
