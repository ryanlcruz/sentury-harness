"""O manual traz, como terceira fonte, pedidos parecidos já resolvidos aqui.

A busca é a mesma do manual, por radical: não depende da intenção do turno
nem de lista de palavras de uma língua. Skill escrita pelo agente entra no
manual sem reiniciar.
"""
import pytest

from sentury.harness.state import AnalysisState
from sentury.memory.experience_library import ExperienceLibrary
from sentury.tools.catalog import execute_tool


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from sentury.knowledge import manual

    manual.esquecer()
    yield
    manual.esquecer()


async def _biblioteca():
    exp = ExperienceLibrary()
    await exp.save("consultar", ["ler_arquivo", "executar_python", "generate_chart"],
                   user_message="faça um gráfico das vendas por mês a partir da planilha vendas.csv")
    await exp.save("alterar", ["executar_comando"], user_message="atualize os pacotes do projeto")
    return exp


async def test_pedido_parecido_vem_com_as_ferramentas_em_ordem():
    exp = await _biblioteca()
    achados = await exp.buscar("quero um gráfico mensal das vendas daquela planilha")
    assert achados and achados[0]["fonte"] == "experiencia"
    assert "ler_arquivo -> executar_python -> generate_chart" in achados[0]["texto"]
    assert "ferramenta:generate_chart" in achados[0]["relacionados"]


async def test_sem_parecido_nao_inventa():
    exp = await _biblioteca()
    assert await exp.buscar("qual a capital da Austrália") == []


async def test_buscar_conhecimento_junta_manual_e_experiencia():
    exp = await _biblioteca()
    achados = await execute_tool(None, AnalysisState.new("s", "u"), "buscar_conhecimento",
                                 {"consulta": "gráfico das vendas por mês da planilha"}, experience=exp)
    fontes = {a.get("fonte") for a in achados}
    assert "experiencia" in fontes and "manual" in fontes


async def test_skill_escrita_pelo_agente_entra_no_manual_sem_reiniciar():
    from sentury.knowledge.manual import manual
    from sentury.skills import escrita

    assert not any(a["id"] == "skill:conversao-de-moeda" for a in manual().buscar("conversao de moeda cotacao"))
    escrita.executar({"acao": "criar", "nome": "conversao-de-moeda", "descricao": "converte moeda pela cotacao",
                      "corpo": "1. Use a cotacao de fechamento do dia anterior."})
    assert any(a["id"] == "skill:conversao-de-moeda" for a in manual().buscar("conversao de moeda cotacao"))
