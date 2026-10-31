"""Memoria EPISODICA: o que ja foi conversado com este usuario.

Distinta da experiencia (que traz o PROCEDIMENTO que funcionou) e da base de
conhecimento (que traz conceito). Aqui e o que foi dito antes.
"""
import pytest

from sentury.memory.session_index import SessionIndex, search_digest
from sentury.memory.session_store import InMemorySessionStore


class _Estado:
    def __init__(self, session_id, user_id, history, updated_at=1000.0):
        self.session_id = session_id
        self.user_id = user_id
        self.history = history
        self.updated_at = updated_at

    def to_dict(self):
        return {"session_id": self.session_id, "history": self.history}


def _conversa(perguntas):
    h = []
    for q, r in perguntas:
        h.append({"role": "user", "content": q})
        h.append({"role": "assistant", "content": r})
    return h


async def _indice_com_historico():
    idx = SessionIndex(InMemorySessionStore())
    await idx.remember(_Estado("s1", "u1", _conversa([
        ("por que o NPS do Sudeste caiu?", "O backlog de 45,4% e o motor da queda."),
    ]), updated_at=100.0))
    await idx.remember(_Estado("s2", "u1", _conversa([
        ("compare o CSAT das filiais de Rental", "Rental esta abaixo da media."),
    ]), updated_at=200.0))
    await idx.remember(_Estado("s3", "u2", _conversa([
        ("qual o backlog do Sudeste?", "33,6% no consolidado."),
    ]), updated_at=300.0))
    return idx


def test_digest_prioriza_a_fala_do_usuario():
    """E a pergunta que carrega o assunto; a resposta repete o enunciado."""
    d = search_digest(_conversa([("por que o NPS do Sudeste caiu?", "x" * 500)]))
    assert "Sudeste" in d
    assert len(d) < 800


async def test_acha_conversa_anterior_pelo_assunto():
    idx = await _indice_com_historico()
    r = await idx.search("u1", "o que a gente viu sobre o Sudeste?")
    assert r and r[0]["session_id"] == "s1"
    assert "sudeste" in r[0]["casou_em"]


async def test_nunca_vaza_conversa_de_outro_usuario():
    """Escopo por user_id e regra, nao detalhe: u2 falou de Sudeste tambem."""
    idx = await _indice_com_historico()
    for r in await idx.search("u1", "backlog do Sudeste"):
        assert r["session_id"] != "s3"
    assert await idx.search("u3", "Sudeste") == []


async def test_exclui_a_sessao_corrente():
    """Sem isso o agente 'encontra' o que acabou de dizer."""
    idx = await _indice_com_historico()
    r = await idx.search("u1", "Sudeste", excluir="s1")
    assert all(x["session_id"] != "s1" for x in r)


async def test_consulta_sem_termo_util_nao_devolve_tudo():
    idx = await _indice_com_historico()
    assert await idx.search("u1", "o de que a") == []
    assert await idx.search("u1", "") == []


async def test_ordena_por_relevancia_depois_por_recencia():
    idx = await _indice_com_historico()
    r = await idx.search("u1", "NPS Sudeste backlog")
    assert r[0]["session_id"] == "s1"
    assert r[0]["relevancia"] > 0
