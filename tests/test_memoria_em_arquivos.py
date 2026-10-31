"""A memória da pessoa mora em arquivos .md que ela pode abrir.

Um fato por arquivo, com tipo e descrição; o índice refeito a cada escrita;
o mesmo nome atualiza o item; nada expira; o que estava no backend de sessão
vem junto na primeira leitura.
"""
import pytest

from sentury.harness.state import AnalysisState
from sentury.memory.memoria_em_arquivos import MemoriaEmArquivos
from sentury.memory.session_store import InMemorySessionStore
from sentury.memory.user_memory import UserMemoryStore, build_memory_context, get_user_memory_store
from sentury.tools.catalog import execute_tool


@pytest.fixture
def mem(tmp_path):
    return MemoriaEmArquivos(tmp_path)


async def test_um_fato_por_arquivo_e_o_indice(mem, tmp_path):
    assert await mem.remember("ana", "prefere respostas curtas: lê no celular", tipo="pessoa",
                              nome="respostas-curtas", descricao="Prefere respostas curtas")
    assert await mem.remember("ana", "o banco migra para Postgres em março", tipo="decisao")
    pasta = tmp_path / "ana"
    assert (pasta / "respostas-curtas.md").is_file()
    indice = (pasta / "MEMORIA.md").read_text(encoding="utf-8")
    assert "[Prefere respostas curtas](respostas-curtas.md) · pessoa" in indice
    assert "· decisao" in indice


async def test_mesmo_nome_atualiza_em_vez_de_duplicar(mem):
    await mem.remember("ana", "usa Python 3.12", nome="versao-do-python", tipo="projeto")
    assert await mem.remember("ana", "usa Python 3.13", nome="versao-do-python", tipo="projeto")
    itens = await mem.all("ana")
    assert [(i["nome"], i["texto"]) for i in itens] == [("versao-do-python", "usa Python 3.13")]


async def test_ler_traz_o_texto_inteiro_pela_ferramenta(mem):
    await mem.remember("ana", "decidimos não usar Redis: estado em disco local", nome="sem-redis", tipo="decisao")
    estado = AnalysisState.new("s", "ana")
    item = await execute_tool(None, estado, "memoria", {"acao": "ler", "nome": "sem-redis"}, None, mem)
    assert item["texto"] == "decidimos não usar Redis: estado em disco local" and item["tipo"] == "decisao"
    faltou = await execute_tool(None, estado, "memoria", {"acao": "ler", "nome": "nao-existe"}, None, mem)
    assert "erro" in faltou


async def test_o_contexto_do_turno_mostra_tipo_idade_e_nome(mem):
    await mem.remember("ana", "prefere tabelas", nome="tabelas", descricao="Prefere tabelas a gráficos")
    contexto = build_memory_context(await mem.all("ana"))
    assert "- Prefere tabelas a gráficos (pessoa, hoje) `tabelas`" in contexto
    assert "pano de fundo" in contexto


async def test_o_que_estava_no_backend_de_sessao_vem_uma_vez(tmp_path):
    sessao = InMemorySessionStore()
    antigo = UserMemoryStore(sessao)
    await antigo.remember("ana", "trabalha com dados de vendas", sessao="s1")
    mem = get_user_memory_store(sessao, raiz=tmp_path)
    itens = await mem.all("ana")
    assert [(i["texto"], i.get("sessao")) for i in itens] == [("trabalha com dados de vendas", "s1")]
    await mem.forget("ana")
    assert await mem.all("ana") == []  # apagado não volta do backend antigo


async def test_parecido_volta_com_o_nome_para_o_modelo_atualizar(mem):
    estado = AnalysisState.new("s", "ana")
    salvar = {"acao": "salvar", "fato": "o projeto Atlas usa Python 3.12", "tipo": "projeto"}
    assert (await execute_tool(None, estado, "memoria", salvar, None, mem))["status"] == "salvo"
    nome = (await mem.all("ana"))[0]["nome"]
    novo = {"acao": "salvar", "fato": "o projeto Atlas usa Python 3.13", "tipo": "projeto"}
    recusado = await execute_tool(None, estado, "memoria", novo, None, mem)
    assert recusado["status"] == "não salvo" and recusado["parecido"]["nome"] == nome
    assert (await execute_tool(None, estado, "memoria", {**novo, "nome": nome}, None, mem))["status"] == "salvo"
    assert [i["texto"] for i in await mem.all("ana")] == ["o projeto Atlas usa Python 3.13"]


def test_uma_palavra_em_comum_nao_e_parecido():
    from sentury.memory.semelhanca import semelhantes

    acervo = {"tabelas": "prefere tabelas", "contrato": "revisa contrato de aluguel"}
    assert semelhantes("prefere gráficos de barra", acervo) == []
    assert semelhantes("controlar o estoque", acervo) == []
    assert semelhantes("revisa o contrato de aluguel novo", acervo)[0][0] == "contrato"
