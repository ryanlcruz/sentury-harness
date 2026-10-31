"""A tela de Memória mostra, ensina e apaga o que o Sentury lembra da pessoa."""
import pytest
from fastapi import HTTPException

from sentury.memory.session_store import InMemorySessionStore
from sentury.memory.user_memory import get_user_memory_store


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    # A memoria mora em disco: cada teste com a sua.
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))


async def test_id_nao_repete_depois_de_apagar():
    mem = get_user_memory_store(InMemorySessionStore())
    for texto in ("prefere tabelas", "trabalha com Python", "fuso de Lisboa"):
        await mem.remember("u", texto)
    assert await mem.remove("u", 2)
    await mem.remember("u", "gosta de respostas curtas")
    ids = [m["id"] for m in await mem.all("u")]
    assert ids == [1, 3, 4] and len(set(ids)) == len(ids)
    assert not await mem.remove("u", 99)


async def test_pelos_endpoints(monkeypatch):
    from sentury import main

    monkeypatch.setattr(main, "user_memory", get_user_memory_store(InMemorySessionStore()))
    assert (await main.memorias_do_usuario("ana", None)) == {"memorias": []}

    ensinar = main.MemoriaDoUsuarioRequest
    assert (await main.ensinar_memoria(ensinar(user_id="ana", texto="prefere gráficos de barra"), None))["guardada"]
    assert (await main.ensinar_memoria(ensinar(user_id="ana", texto="escreve em inglês no código"), None))["guardada"]
    repetida = await main.ensinar_memoria(ensinar(user_id="ana", texto="prefere gráficos de barra"), None)
    assert repetida == {"guardada": False}

    lista = (await main.memorias_do_usuario("ana", None))["memorias"]
    assert [m["texto"] for m in lista] == ["escreve em inglês no código", "prefere gráficos de barra"]
    assert lista[0]["idade"] == "hoje"
    assert (await main.memorias_do_usuario("outra", None))["memorias"] == []

    assert await main.apagar_memoria(lista[1]["id"], "ana", None) == {"removida": True}
    assert [m["texto"] for m in (await main.memorias_do_usuario("ana", None))["memorias"]] == ["escreve em inglês no código"]
    with pytest.raises(HTTPException) as erro:
        await main.apagar_memoria(lista[1]["id"], "ana", None)
    assert erro.value.status_code == 404


class _IndiceFalso:
    async def list(self, user_id):
        return [{"session_id": "s1", "title": "Planilha de vendas"}]


async def test_cada_lembranca_mostra_a_conversa_de_onde_veio(monkeypatch):
    """Sem a origem, a lista vira frases soltas: a pessoa não sabe por que o
    Sentury guardou aquilo."""
    from sentury import main

    mem = get_user_memory_store(InMemorySessionStore())
    monkeypatch.setattr(main, "user_memory", mem)
    monkeypatch.setattr(main, "session_index", _IndiceFalso())
    await mem.remember("ana", "trabalha com Python", sessao="s1")
    await mem.remember("ana", "prefere tabelas")
    await mem.remember("ana", "fuso de Lisboa", sessao="apagada")

    por_texto = {m["texto"]: m for m in (await main.memorias_do_usuario("ana", None))["memorias"]}
    assert por_texto["trabalha com Python"]["conversa"] == "Planilha de vendas"
    assert por_texto["prefere tabelas"]["sessao"] is None and por_texto["prefere tabelas"]["conversa"] is None
    assert por_texto["fuso de Lisboa"]["sessao"] == "apagada" and por_texto["fuso de Lisboa"]["conversa"] is None


async def test_desfazer_do_chat_apaga_so_o_texto_exato(monkeypatch):
    """`forget` apaga por trecho; o "Desfazer" não pode levar junto outra lembrança."""
    from sentury import main

    mem = get_user_memory_store(InMemorySessionStore())
    monkeypatch.setattr(main, "user_memory", mem)
    await mem.remember("ana", "usa Python")
    await mem.remember("ana", "trabalha com dados de vendas em Python no fim do mês")

    pedido = main.MemoriaDoUsuarioRequest(user_id="ana", texto="Usa Python")
    assert await main.esquecer_memoria_pelo_texto(pedido, None) == {"removida": True}
    assert [m["texto"] for m in await mem.all("ana")] == ["trabalha com dados de vendas em Python no fim do mês"]
    assert await main.esquecer_memoria_pelo_texto(pedido, None) == {"removida": False}


async def test_o_que_o_modelo_guarda_leva_a_conversa():
    """A lembrança guardada pela ferramenta sabe de que conversa veio."""
    import json

    from sentury.data.store import SemDados
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState

    class Modelo:
        supports_tools = False
        last_model = "teste"

        def __init__(self):
            self.roteiro = [
                {"plan": [{"tool": "memoria", "arguments": {"acao": "salvar", "fato": "prefere respostas curtas",
                                                            "tipo": "pessoa"}}]},
                {"plan": [], "message": "Guardado."},
            ]

        async def complete(self, messages, **kwargs):
            return json.dumps(self.roteiro.pop(0) if self.roteiro else {"plan": []})

    mem = get_user_memory_store(InMemorySessionStore())
    orq = SenturyOrchestrator(planner=Modelo(), responder=Modelo(), store=SemDados(), memory=mem)
    await orq.handle_message(AnalysisState.new("conversa-7", "ana"), "prefiro respostas curtas, leio no celular")
    itens = await mem.all("ana")
    assert [(i["texto"], i.get("sessao"), i["tipo"]) for i in itens] == [
        ("prefere respostas curtas", "conversa-7", "pessoa")]
