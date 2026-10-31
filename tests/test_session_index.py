import pytest

from sentury.harness.state import AnalysisState
from sentury.memory.session_index import SessionIndex
from sentury.memory.session_store import InMemorySessionStore


@pytest.mark.asyncio
async def test_session_index_lista_carrega_e_respeita_usuario():
    store = InMemorySessionStore()
    index = SessionIndex(store, ttl=60, max_items=5)
    state = AnalysisState.new("sess-1", "user-1")
    state.history = [
        {"role": "user", "content": "me informe o NPS geral"},
        {
            "role": "assistant",
            "content": "O NPS geral esta em -31,2.",
            "attachment": {"type": "markdown", "title": "Plano", "content": "# Plano"},
        },
    ]

    meta = await index.remember(state)
    sessions = await index.list("user-1")
    loaded = await index.load("user-1", "sess-1")

    assert meta["title"] == "me informe o NPS geral"
    assert sessions[0]["session_id"] == "sess-1"
    assert sessions[0]["artifact_count"] == 1
    assert loaded["history"][1]["attachment"]["title"] == "Plano"
    assert await index.load("outro-user", "sess-1") is None


@pytest.mark.asyncio
async def test_session_index_renomeia_titulo_manual():
    store = InMemorySessionStore()
    index = SessionIndex(store, ttl=60, max_items=5)
    state = AnalysisState.new("sess-2", "user-1")
    state.history = [{"role": "user", "content": "tickets criticos da semana"}]
    await index.remember(state)

    renamed = await index.rename("user-1", "sess-2", "Tickets Criticos")
    sessions = await index.list("user-1")

    assert renamed["title"] == "Tickets Criticos"
    assert renamed["title_source"] == "manual"
    assert sessions[0]["title"] == "Tickets Criticos"
