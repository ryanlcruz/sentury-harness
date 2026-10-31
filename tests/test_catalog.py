import pytest
import pandas as pd

from tests.fixtures.setor_teste.dados import StoreTeste
from sentury.harness.state import AnalysisState
from sentury.tools.catalog import execute_tool


@pytest.fixture(scope="module")
def store() -> StoreTeste:
    return StoreTeste()


def _state() -> AnalysisState:
    return AnalysisState.new("s1", "u1")


async def test_analysis_tool_registers_result_when_data_exists(store, setor_teste):
    state = _state()
    await execute_tool(store, state, "consultar_medida", {"grupo": None})
    assert len(state.results) == 1
    assert state.last_result_id is not None


async def test_analysis_tool_does_not_register_when_no_data(store, setor_teste):
    state = _state()
    resultado = await execute_tool(store, state, "consultar_medida", {"grupo": "Marte"})
    assert resultado == []
    assert state.results == {}


async def test_unknown_tool_raises(store):
    state = _state()
    with pytest.raises(ValueError):
        await execute_tool(store, state, "apagar_dataset", {})


async def test_export_without_prior_result_raises(store):
    state = _state()
    with pytest.raises(ValueError):
        await execute_tool(store, state, "export_csv", {})


async def test_export_recomputes_from_recipe_not_from_invented_args(store, setor_teste):
    state = _state()
    await execute_tool(store, state, "consultar_medida", {"grupo": None})
    csv_bytes = await execute_tool(store, state, "export_csv", {"source": state.last_result_id})
    assert isinstance(csv_bytes, bytes)
    assert len(csv_bytes) > 0


async def test_save_analysis_renames_result(store, setor_teste):
    state = _state()
    await execute_tool(store, state, "consultar_medida", {"grupo": None})
    saved = await execute_tool(store, state, "save_analysis", {"nome": "Medida Geral"})
    assert saved["nome"] == "Medida Geral"
    assert state.results[saved["source"]]["nome"] == "Medida Geral"


async def test_save_analysis_without_result_raises(store):
    state = _state()
    with pytest.raises(ValueError):
        await execute_tool(store, state, "save_analysis", {"nome": "X"})
