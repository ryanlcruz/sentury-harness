"""O setor da bancada usa o contrato real sem depender de um setor distribuído."""
import pytest

from sentury.domains import get_active_domain
from sentury.domains.escopo import usar_setor
from sentury.harness.state import AnalysisState
from sentury.tools.catalog import execute_tool
from sentury.tools.registry import TOOL_REGISTRY, ferramentas_do_setor_ativo
from tests.fixtures.setor_teste.dados import StoreTeste


def test_pacote_tem_uma_metrica_e_uma_ferramenta(setor_teste):
    assert set(get_active_domain().metric_names) == {"medida"}
    assert {n for n, m in TOOL_REGISTRY.items()
            if m.get("setor") == "setor_teste"} == {"consultar_medida"}


def test_recortes_saem_dos_registros(setor_teste):
    conn = StoreTeste().get_sqlite_conn()
    try:
        grupos = [r[0] for r in conn.execute(
            "SELECT DISTINCT grupo FROM registros ORDER BY grupo")]
    finally:
        conn.close()
    assert setor_teste.dimensoes == {"grupo": grupos}


@pytest.mark.parametrize("grupo,esperado", [
    (None, [{"grupo": "Alfa", "medida": 20.0}, {"grupo": "Beta", "medida": 40.0}]),
    ("Beta", [{"grupo": "Beta", "medida": 40.0}]),
    ("ausente", []),
])
async def test_consulta_real_passando_pelo_catalogo(setor_teste, grupo, esperado):
    state = AnalysisState.new("consulta", "teste")
    result = await execute_tool(StoreTeste(), state, "consultar_medida", {"grupo": grupo})
    assert result == esperado
    assert len(state.results) == int(bool(esperado))
    if esperado:
        assert state.results[state.last_result_id]["tool"] == "consultar_medida"
        assert state.results[state.last_result_id]["arguments"] == {"grupo": grupo}


def test_exportacoes_nao_tem_setor_dono():
    with usar_setor("generalista"):
        registro = ferramentas_do_setor_ativo()
    for nome in ("generate_chart", "export_csv", "export_xlsx", "export_pdf", "export_html"):
        assert nome in registro
        assert not registro[nome].get("setor")
        assert registro[nome]["destino_residente"] == "proibida"


def test_goldens_usam_o_pacote_selecionado(setor_teste):
    from sentury.evals import golden

    assert golden._setor_de_eval() == "setor_teste"
    assert golden.casos_do_setor("setor_teste") == golden._CASES
    assert golden.casos_do_setor("nao_instalado") == []
