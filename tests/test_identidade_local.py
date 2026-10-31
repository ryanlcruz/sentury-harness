"""Dono das conversas e arrumacao da barra lateral.

Id sorteado no navegador vira um usuario por origem, e a lista abre vazia com
o historico intacto no disco.
"""
import pytest

from sentury.memory import identidade, preferencias_ui
from sentury.memory.local_session_store import LocalSessionStore
from sentury.memory.session_index import index_key


@pytest.fixture
def store(tmp_path):
    return LocalSessionStore(str(tmp_path))


async def _semear(store, user_id, *titulos, quando=1000.0):
    sessoes = [
        {"session_id": f"{user_id}-{i}", "user_id": user_id, "title": titulo,
         "updated_at": quando + i}
        for i, titulo in enumerate(titulos)
    ]
    await store.set(index_key(user_id), {"user_id": user_id, "sessions": sessoes})


@pytest.mark.asyncio
async def test_identidade_e_a_mesma_em_qualquer_porta(tmp_path, store):
    """A maquina e dona do id: duas chamadas, mesmo usuario."""
    primeira = await identidade.resolver(store, str(tmp_path))
    segunda = await identidade.resolver(store, str(tmp_path))
    assert primeira == segunda
    assert identidade.caminho(str(tmp_path)).is_file()


@pytest.mark.asyncio
async def test_herda_o_id_que_ja_tinha_conversa(tmp_path, store):
    """Quem ja usou o Sentury reabre e encontra o historico onde deixou."""
    await _semear(store, "local-" + "a" * 36, "Uma", "Duas")
    await _semear(store, "local-" + "b" * 36, "Sozinha")
    assert await identidade.resolver(store, str(tmp_path)) == "local-" + "a" * 36


@pytest.mark.asyncio
async def test_conversas_espalhadas_se_juntam_numa_lista_so(tmp_path, store):
    from sentury.memory.session_index import SessionIndex

    await _semear(store, "local-" + "a" * 36, "Uma", "Duas")
    await _semear(store, "local-" + "b" * 36, "Terceira")
    dono = await identidade.resolver(store, str(tmp_path))

    titulos = {s["title"] for s in await SessionIndex(store).list(dono)}
    assert titulos == {"Uma", "Duas", "Terceira"}


@pytest.mark.asyncio
async def test_conversa_de_teste_cai_numa_pasta_a_parte(tmp_path, store):
    """Id nomeado a mao e teste de desenvolvimento: entra separado."""
    await _semear(store, "local-" + "a" * 36, "Conversa de verdade")
    await _semear(store, "tok", "Teste do agente")
    dono = await identidade.resolver(store, str(tmp_path))

    prefs = await preferencias_ui.ler(store, dono)
    nomes = {p["nome"] for p in prefs["pastas"]}
    assert identidade.PASTA_TESTES in nomes

    pasta_id = next(p["id"] for p in prefs["pastas"] if p["nome"] == identidade.PASTA_TESTES)
    assert prefs["sessoes"]["tok-0"]["pasta"] == pasta_id
    assert "local-" + "a" * 36 + "-0" not in prefs["sessoes"]


@pytest.mark.asyncio
async def test_a_conversa_guarda_de_onde_veio(tmp_path, store):
    from sentury.memory.session_index import SessionIndex

    await _semear(store, "local-" + "a" * 36, "Dele")
    await _semear(store, "diagnostico-local", "Meu teste")
    dono = await identidade.resolver(store, str(tmp_path))

    adotada = next(s for s in await SessionIndex(store).list(dono) if s["title"] == "Meu teste")
    assert adotada["origem_id"] == "diagnostico-local"
    assert adotada["user_id"] == dono


@pytest.mark.asyncio
async def test_identidade_escolhida_a_mao_manda(tmp_path, store):
    identidade.definir("time-suporte", str(tmp_path))
    assert await identidade.resolver(store, str(tmp_path)) == "time-suporte"
    # Vazio nao apaga o que ja existe.
    assert identidade.definir("", str(tmp_path)) is None
    assert await identidade.resolver(store, str(tmp_path)) == "time-suporte"


@pytest.mark.asyncio
async def test_unificar_nao_repete_conversa_ja_adotada(tmp_path, store):
    from sentury.memory.session_index import SessionIndex

    await _semear(store, "local-" + "a" * 36, "Uma")
    await _semear(store, "tok", "Teste")
    dono = await identidade.resolver(store, str(tmp_path))
    await identidade.unificar(store, dono)  # de novo

    ids = [s["session_id"] for s in await SessionIndex(store).list(dono)]
    assert len(ids) == len(set(ids)) == 2


@pytest.mark.asyncio
async def test_arrumacao_da_barra_lateral_sobrevive_ao_navegador(store):
    """Pasta e fixado ficam no servidor, nao na origem do navegador."""
    await preferencias_ui.gravar(store, "alguem", {
        "pastas": [{"id": "pasta-1", "nome": "Clientes", "recolhida": True}],
        "sessoes": {"sess-1": {"pinned": True, "pasta": "pasta-1"}},
    })
    lido = await preferencias_ui.ler(store, "alguem")
    assert lido["pastas"] == [{"id": "pasta-1", "nome": "Clientes", "recolhida": True}]
    assert lido["sessoes"]["sess-1"] == {"pinned": True, "pasta": "pasta-1"}


@pytest.mark.asyncio
async def test_sem_preferencia_nenhuma_a_barra_abre_vazia_sem_erro(store):
    assert await preferencias_ui.ler(store, "novo") == preferencias_ui.vazio()


@pytest.mark.asyncio
async def test_marcar_respeita_pasta_que_a_pessoa_ja_escolheu(store):
    await preferencias_ui.gravar(store, "alguem", {
        "pastas": [{"id": "minha", "nome": "Minha"}],
        "sessoes": {"sess-1": {"pasta": "minha"}},
    })
    await preferencias_ui.marcar(store, "alguem", ["sess-1", "sess-2"], "Testes")

    prefs = await preferencias_ui.ler(store, "alguem")
    assert prefs["sessoes"]["sess-1"]["pasta"] == "minha"
    assert prefs["sessoes"]["sess-2"]["pasta"] != "minha"
