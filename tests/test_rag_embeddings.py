"""RAG com embeddings Gemini: ranking por cosseno e fallback em runtime.
Sem rede: injeta os vetores e monkeypatcha o embed da query."""
from sentury.knowledge.retriever import _EmbeddingBackend, _GeminiEmbeddingBackend, _LexicalBackend, KnowledgeBase

CHUNKS = [
    {"id": "1", "titulo": "NPS", "texto": "Net Loyalty Score mede lealdade do cliente"},
    {"id": "2", "titulo": "SLA", "texto": "prazo de atendimento acordado com o cliente"},
]


def _backend_sem_rede(doc_vecs):
    be = object.__new__(_GeminiEmbeddingBackend)
    be._chunks = CHUNKS
    be._doc_vecs = doc_vecs
    be._lexical = _LexicalBackend(CHUNKS)
    be._runtime_fallback = be._lexical
    be._api_key = "x"
    be._model = "gemini-embedding-001"
    return be


def test_ranking_por_cosseno():
    be = _backend_sem_rede([[1.0, 0.0], [0.0, 1.0]])
    be._embed_query = lambda q: [1.0, 0.0]  # query alinhada com o doc 1
    r = be.search("qualquer", 2)
    assert r and r[0]["id"] == "1"


def test_fallback_lexico_quando_query_falha():
    be = _backend_sem_rede([[1.0, 0.0], [0.0, 1.0]])
    def _boom(q):
        raise RuntimeError("429 quota")
    be._embed_query = _boom
    r = be.search("NPS", 2)
    # caiu no léxico, que acha por termo
    assert r == be._lexical.search("NPS", 2)
    assert any("NPS" in x["titulo"] for x in r)


def test_fallback_fastembed_quando_disponivel():
    class _Fallback:
        nome = "embeddings (fastembed)"

        def search(self, query, k):
            return [{"id": "2", "titulo": "SLA", "texto": "via fastembed", "score": 0.91}]

    be = _backend_sem_rede([[1.0, 0.0], [0.0, 1.0]])
    be._runtime_fallback = _Fallback()

    def _boom(q):
        raise RuntimeError("429 quota")

    be._embed_query = _boom
    r = be.search("NPS", 2)
    assert r == [{"id": "2", "titulo": "SLA", "texto": "via fastembed", "score": 0.91}]


def test_knowledgebase_sem_key_usa_lexico():
    # sem gemini_api_key nem supabase → backend léxico (não faz rede)
    kb = KnowledgeBase(CHUNKS)
    assert kb.modo == "lexical (demo)"


def test_knowledgebase_gemini_usa_fastembed_como_fallback(monkeypatch):
    class _FakeFastembed:
        nome = "embeddings (fastembed)"

        def search(self, query, k):
            return [{"id": "1", "titulo": "NPS", "texto": "fallback local", "score": 0.88}]

    def _fake_fastembed(chunks):
        return _FakeFastembed()

    def _fake_gemini(chunks, api_key, model, runtime_fallback=None):
        backend = _backend_sem_rede([[1.0, 0.0], [0.0, 1.0]])
        backend._runtime_fallback = runtime_fallback
        return backend

    monkeypatch.setattr("sentury.knowledge.retriever._EmbeddingBackend", _fake_fastembed)
    monkeypatch.setattr("sentury.knowledge.retriever._GeminiEmbeddingBackend", _fake_gemini)

    kb = KnowledgeBase(
        CHUNKS,
        use_embeddings=True,
        gemini_api_key="key",
        gemini_model="gemini-embedding-001",
    )
    assert kb.modo == "embeddings (gemini)"
    assert kb._backend._runtime_fallback.nome == "embeddings (fastembed)"
