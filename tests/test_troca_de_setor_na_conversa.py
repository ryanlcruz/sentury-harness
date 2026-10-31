"""Trocar de setor no meio de uma conversa deixa marca.

Sem isto a persona mudava em silencio: o historico acima continuava ali,
escrito com o vocabulario e as ferramentas do setor antigo, e o modelo lia
tudo como se fosse do setor de agora.
"""
import pytest

from sentury.harness.abertura_do_turno import _marcar_troca_de_setor
from sentury.harness.state import AnalysisState


def _marcas(state):
    return [m["content"] for m in state.history
            if m.get("role") == "system" and "[SETOR]" in str(m.get("content") or "")]


@pytest.fixture
def setor(monkeypatch, tmp_path):
    def ligar(nome):
        monkeypatch.setattr("sentury.domains.escolha.ler", lambda sentury_home="": nome)
    return ligar


def test_conversa_vazia_nao_ganha_marca(setor):
    setor("setor_teste")
    state = AnalysisState(session_id="s", user_id="u")
    _marcar_troca_de_setor(state)
    assert _marcas(state) == []


def test_primeiro_turno_carimba_o_setor(setor):
    setor("setor_teste")
    state = AnalysisState(session_id="s", user_id="u")
    state.history.append({"role": "user", "content": "como esta o Medida?"})
    _marcar_troca_de_setor(state)
    assert _marcas(state) == ["[SETOR] setor_teste"]


def test_mesmo_setor_nao_repete_marca(setor):
    setor("setor_teste")
    state = AnalysisState(session_id="s", user_id="u")
    state.history.append({"role": "user", "content": "oi"})
    _marcar_troca_de_setor(state)
    _marcar_troca_de_setor(state)
    assert len(_marcas(state)) == 1


def test_troca_avisa_o_que_veio_de_antes(setor):
    setor("setor_teste")
    state = AnalysisState(session_id="s", user_id="u")
    state.history.append({"role": "user", "content": "como esta o Medida?"})
    _marcar_troca_de_setor(state)

    setor("generalista")
    state.history.append({"role": "user", "content": "e agora?"})
    _marcar_troca_de_setor(state)

    ultima = _marcas(state)[-1]
    assert "de 'setor_teste' para 'generalista'" in ultima
    assert "nao prometa" in ultima.lower().replace("ã", "a").replace("á", "a")
