import pytest

from tests.fixtures.setor_teste.dados import StoreTeste
from sentury.harness.state import AnalysisState
from sentury.memory.session_store import InMemorySessionStore
from sentury.memory.user_memory import (
    UserMemoryStore,
    build_memory_context,
    detect_recurring_interest,
    get_user_memory_store,
)
from sentury.tools.catalog import execute_tool


@pytest.fixture(scope="module")
def store() -> StoreTeste:
    return StoreTeste()


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    # A memoria mora em disco: cada teste com a sua.
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))


def _mem():
    return get_user_memory_store(InMemorySessionStore())


def test_recurring_interest_ignores_prose_mentions():
    # Investigar um PROBLEMA no Alfa faz o gestor citar "Alfa" muitas vezes
    # na conversa: isso NÃO é preferência e não deve virar memória (bug antigo).
    history = [{"role": "user", "content": f"o que houve no Alfa? ({i})"} for i in range(15)]
    assert detect_recurring_interest(history, {}) is None


def test_recurring_interest_learns_from_deliberate_filters(setor_teste):
    # Restringir (filtrar) 2+ análises à mesma grupo é uma ação deliberada = foco.
    results = {
        "r1": {"arguments": {"grupo": "Beta"}},
        "r2": {"arguments": {"grupo": "Beta"}},
    }
    fato = detect_recurring_interest([], results)
    assert fato and "Beta" in fato


def test_recurring_interest_single_filter_is_not_enough():
    results = {"r1": {"arguments": {"grupo": "Beta"}}}
    assert detect_recurring_interest([], results) is None


async def test_remember_recall_and_dedup():
    mem = _mem()
    assert await mem.remember("u1", "prefere Ishikawa") is True
    assert await mem.remember("u1", "prefere Ishikawa") is False  # dedup
    todas = await mem.all("u1")
    assert len(todas) == 1 and todas[0]["texto"] == "prefere Ishikawa"


async def test_forget_by_term_and_all():
    mem = _mem()
    await mem.remember("u1", "foco em Centro-Oeste")
    await mem.remember("u1", "prefere Ishikawa")
    assert await mem.forget("u1", "ishikawa") == 1
    assert len(await mem.all("u1")) == 1
    assert await mem.forget("u1") == 1  # limpa o resto
    assert await mem.all("u1") == []


async def test_memory_is_per_user():
    mem = _mem()
    await mem.remember("u1", "foco em Peças")
    assert await mem.all("u2") == []


def test_build_memory_context_none_when_empty():
    assert build_memory_context([]) is None
    ctx = build_memory_context([{"texto": "prefere Ishikawa"}])
    assert "Ishikawa" in ctx


async def test_memory_tools_via_catalog(store):
    mem = _mem()
    state = AnalysisState.new("s", "u9")
    salvo = await execute_tool(store, state, "salvar_memoria", {"fato": "meta de Medida -20"}, None, mem)
    assert salvo["status"] == "salvo"
    listado = await execute_tool(store, state, "listar_memorias", {}, None, mem)
    assert any("meta de Medida" in m["texto"] for m in listado)
    removido = await execute_tool(store, state, "esquecer_memoria", {"termo": "meta"}, None, mem)
    assert removido["removidos"] == 1
