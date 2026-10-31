"""O catálogo de evals respeita o contrato do setor ativo."""
from sentury.domains.escopo import usar_setor


async def test_generalista_nao_ve_evals_que_exigem_analise():
    from sentury import main

    with usar_setor("generalista"):
        catalogo = await main.listar_evals(None)
    assert catalogo["setor"] == "generalista" and catalogo["casos"] == []


async def test_setor_com_analise_ve_as_goldens():
    from sentury import main
    from sentury.evals.golden import _CASES

    with usar_setor("setor_teste"):
        catalogo = await main.listar_evals(None)
    assert catalogo["setor"] == "setor_teste"
    assert [c["funcao"] for c in catalogo["casos"]] == [c.__name__ for c in _CASES]
    assert all(c["descricao"] for c in catalogo["casos"])


async def test_rodar_evals_pela_api_devolve_o_tempo():
    """A rota mede a rodada; no generalista não há caso, e mesmo assim ela responde."""
    from sentury import main

    with usar_setor("generalista"):
        rodada = await main.rodar_evals(None)
    assert rodada["total"] == 0
    assert rodada["ms"] >= 0
