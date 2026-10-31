"""O diario local para de crescer sem teto.

Numa maquina real, `~/.sentury` tinha 88 MB, 85 so em `store-events.jsonl`:
cada `set` grava o estado INTEIRO da sessao, e o diario guardava todas as
versoes de todas as conversas. Compactar mantem o ultimo evento de cada chave:
o diario continua sendo a fonte, e a projecao se refaz a partir dele.
"""
import gzip
import json

from sentury.memory import local_session_store as modulo
from sentury.memory.local_session_store import LocalSessionStore


def _linhas(store):
    return [json.loads(l) for l in store.journal_path.read_text("utf-8").splitlines() if l.strip()]


async def _historico(store):
    for turno in range(5):
        await store.set("conversa-a", {"turnos": turno})
    for turno in range(3):
        await store.set("conversa-b", {"turnos": turno})
    await store.delete("conversa-b")
    await store.set("conversa-c", {"turnos": 0})


async def test_fica_o_ultimo_evento_de_cada_chave(tmp_path):
    store = LocalSessionStore(tmp_path)
    await _historico(store)
    antes = _linhas(store)

    resultado = store.compactar()

    depois = _linhas(store)
    assert resultado["eventos_antes"] == len(antes) == 10
    assert [(e["key"], e["type"]) for e in depois] == [
        ("conversa-a", "memory.recorded"),
        ("conversa-b", "memory.forgotten"),
        ("conversa-c", "memory.recorded"),
    ]
    assert [e["seq"] for e in depois] == sorted(e["seq"] for e in depois), "seq continua em ordem"
    assert max(e["seq"] for e in depois) == max(e["seq"] for e in antes), "o maior seq sobrevive"


async def test_reabrir_depois_de_compactar_da_o_mesmo_estado(tmp_path):
    store = LocalSessionStore(tmp_path)
    await _historico(store)
    store.compactar()

    reaberto = LocalSessionStore(tmp_path)
    assert await reaberto.get("conversa-a") == {"turnos": 4}
    assert await reaberto.get("conversa-b") is None, "esquecida nao volta"
    assert await reaberto.get("conversa-c") == {"turnos": 0}


async def test_a_projecao_se_refaz_so_com_o_diario_compactado(tmp_path):
    """O diario e a fonte: sem o SQLite, tudo tem que voltar dele."""
    store = LocalSessionStore(tmp_path)
    await _historico(store)
    store.compactar()
    store.catalog_path.unlink()

    refeito = LocalSessionStore(tmp_path)
    assert await refeito.get("conversa-a") == {"turnos": 4}
    assert await refeito.get("conversa-b") is None
    await refeito.set("conversa-d", {"turnos": 1})
    assert _linhas(refeito)[-1]["seq"] > _linhas(refeito)[-2]["seq"], "a numeracao segue de onde parou"


async def test_a_versao_anterior_fica_guardada_uma_vez(tmp_path):
    store = LocalSessionStore(tmp_path)
    await _historico(store)
    store.compactar()

    copia = store.journal_path.with_name("store-events.anterior.jsonl.gz")
    with gzip.open(copia, "rt", encoding="utf-8") as arquivo:
        assert len([l for l in arquivo if l.strip()]) == 10


async def test_compacta_sozinho_ao_passar_do_teto(tmp_path, monkeypatch):
    monkeypatch.setattr(modulo, "DIARIO_MAXIMO_BYTES", 2000)
    store = LocalSessionStore(tmp_path)
    for turno in range(60):
        await store.set("conversa-longa", {"historico": ["x" * 50] * 3, "turno": turno})

    assert len(_linhas(store)) < 60
    assert await store.get("conversa-longa") == {"historico": ["x" * 50] * 3, "turno": 59}


async def test_estado_vivo_maior_que_o_teto_nao_compacta_a_cada_escrita(tmp_path, monkeypatch):
    """Se o que esta VIVO ja passa do teto, compactar de novo nao reduz nada."""
    monkeypatch.setattr(modulo, "DIARIO_MAXIMO_BYTES", 100)
    store = LocalSessionStore(tmp_path)
    chamadas = []
    original = store.compactar
    monkeypatch.setattr(store, "compactar", lambda: chamadas.append(1) or original())

    for chave in range(20):
        await store.set(f"conversa-{chave}", {"texto": "y" * 200})

    assert 0 < len(chamadas) < 10


async def test_diario_da_sessao_grande_fica_com_o_ultimo(tmp_path, monkeypatch):
    monkeypatch.setattr(LocalSessionStore, "_SESSAO_MAXIMA_BYTES", 500)
    store = LocalSessionStore(tmp_path)
    for turno in range(30):
        await store.set("sessao-x", {"texto": "z" * 40, "turno": turno})

    store.compactar()
    arquivo = next(store.sessions_dir.glob("*/*/*/sessao-x/events.jsonl"))
    linhas = [json.loads(l) for l in arquivo.read_text("utf-8").splitlines() if l.strip()]
    assert len(linhas) == 1 and linhas[0]["value"]["turno"] == 29
