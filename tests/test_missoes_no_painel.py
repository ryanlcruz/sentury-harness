"""O painel Tasks lê as missões: quanto falta e o estado de cada unidade."""
import pytest
from fastapi import HTTPException

from sentury.memory.unidades import Missao


@pytest.fixture
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    return tmp_path


async def test_lista_com_o_que_falta_e_a_mais_recente_primeiro(casa):
    from sentury import main

    vagas = Missao("vagas-backend")
    vagas.registrar([("Vaga A", "pagina"), ("Vaga A", "empresa"), ("Vaga B", "pagina")])
    vagas.abrir("Vaga A", "pagina")
    vagas.fechar("Vaga A", "pagina", evidencia="https://exemplo.com/a")
    antiga = Missao("antiga")
    antiga.registrar([("x", "y")])
    vagas.fechar("Vaga B", "pagina", estado="descartada", nota="pede 5 anos")

    missoes = (await main.listar_missoes(None))["missoes"]
    assert [m["missao"] for m in missoes] == ["vagas-backend", "antiga"]
    assert missoes[0]["total"] == 3 and missoes[0]["faltam"] == 1
    assert missoes[0]["por_estado"] == {"feito": 1, "pendente": 1, "descartada": 1}


async def test_detalhe_traz_as_unidades_com_evidencia(casa):
    from sentury import main

    vagas = Missao("vagas-backend")
    vagas.registrar([("Vaga A", "pagina")])
    vagas.abrir("Vaga A", "pagina")
    vagas.fechar("Vaga A", "pagina", evidencia="https://exemplo.com/a")

    detalhe = await main.ver_missao("vagas-backend", None)
    assert detalhe["missao"]["faltam"] == 0
    assert detalhe["unidades"][0]["evidencia"] == "https://exemplo.com/a"


async def test_missao_que_nao_existe_e_404_e_nao_cria_arquivo(casa):
    from sentury import main

    with pytest.raises(HTTPException) as erro:
        await main.ver_missao("nao-existe", None)
    assert erro.value.status_code == 404
    assert not (casa / "missoes" / "nao-existe.json").exists()
