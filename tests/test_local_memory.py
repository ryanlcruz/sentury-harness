import json

from sentury.memory.experience_library import ExperienceLibrary
from sentury.memory.local_session_store import LocalSessionStore


async def test_local_store_survives_restart_and_keeps_complete_warm_state(tmp_path):
    first = LocalSessionStore(tmp_path)
    state = {
        "session_id": "session-1",
        "user_id": "user-1",
        "history": [{"role": "user", "content": "lembre disto"}],
        "conversation_state": {"current_topic": "memoria"},
    }
    await first.set("session-1", state, hot_ttl=0, warm_ttl=60)

    restarted = LocalSessionStore(tmp_path)
    restored = await restarted.get("session-1")

    assert restored["history"] == state["history"]
    assert restored["conversation_state"] == state["conversation_state"]
    assert "recovered" not in restored


async def test_jsonl_is_truth_and_rebuilds_sqlite_projection(tmp_path):
    store = LocalSessionStore(tmp_path)
    await store.set("key", {"value": 42}, hot_ttl=60, warm_ttl=120)
    store.catalog_path.unlink()

    rebuilt = LocalSessionStore(tmp_path)

    assert await rebuilt.get("key") == {"value": 42}
    events = [json.loads(line) for line in rebuilt.journal_path.read_text("utf-8").splitlines()]
    assert events[-1]["type"] == "memory.recorded"
    assert events[-1]["value"] == {"value": 42}


async def test_delete_is_a_durable_event(tmp_path):
    store = LocalSessionStore(tmp_path)
    await store.set("key", {"value": 1})
    await store.delete("key")

    restarted = LocalSessionStore(tmp_path)

    assert await restarted.get("key") is None
    assert "memory.forgotten" in restarted.journal_path.read_text("utf-8")


async def test_local_records_do_not_expire_silently(tmp_path):
    store = LocalSessionStore(tmp_path)
    await store.set("session", {"session_id": "session", "history": []}, hot_ttl=0, warm_ttl=0)

    assert await LocalSessionStore(tmp_path).get("session") == {
        "session_id": "session",
        "history": [],
    }


async def test_experience_library_really_persists(tmp_path):
    store = LocalSessionStore(tmp_path)
    first = ExperienceLibrary(store)
    await first.save(
        "CUSTOM",
        ["inspect", "verify"],
        user_message="investigue e verifique este caso",
    )

    restarted = ExperienceLibrary(LocalSessionStore(tmp_path))
    match = await restarted.find_similar("CUSTOM", "investigue e verifique novamente")

    assert match is not None
    assert match["flow"] == ["inspect", "verify"]
