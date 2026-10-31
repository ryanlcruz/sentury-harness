"""Ação declarada `destrutiva` no tools.yaml pergunta sempre, na hora.

"Permitir tudo", "sempre" e "nesta conversa" não valem para ela: o que apaga
ou não dá para desfazer passa só com a aprovação desta vez, e ela vale para
uma execução.
"""
import pytest

from sentury.exec.politica import cartao_de_destrutiva
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.tools import permissoes
from sentury.tools.registry import TOOL_REGISTRY
from tests.test_descoberta_multilingue import _Nativo
from tests.test_orchestrator import EchoResponder, _store


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.setattr(permissoes, "_DA_SESSAO", {})
    monkeypatch.setattr(permissoes, "_CREDITO_UNICO", {})
    permissoes.definir_permitir_tudo(True)
    # `esquecer` da memória passa a ser declarado destrutivo só neste teste.
    entrada = dict(TOOL_REGISTRY["memoria"])
    entrada["acoes"] = {**entrada["acoes"], "esquecer": "destrutiva"}
    monkeypatch.setitem(TOOL_REGISTRY, "memoria", entrada)
    yield
    permissoes.definir_permitir_tudo(False)


def test_leitura_e_escrita_nao_passam_pela_guarda():
    assert cartao_de_destrutiva("memoria", {"acao": "listar"}, "s") is None
    assert cartao_de_destrutiva("memoria", {"acao": "salvar", "fato": "x"}, "s") is None


def test_destrutiva_pergunta_mesmo_com_permitir_tudo_e_sempre():
    cartao = cartao_de_destrutiva("memoria", {"acao": "esquecer"}, "s")
    assert cartao["precisa_permissao"] and cartao["so_desta_vez"]
    permissoes.responder(cartao["comando"], "sempre", "s")
    assert cartao_de_destrutiva("memoria", {"acao": "esquecer"}, "s")["precisa_permissao"]


def test_aprovacao_desta_vez_vale_uma_execucao():
    cartao = cartao_de_destrutiva("memoria", {"acao": "esquecer"}, "s")
    permissoes.responder(cartao["comando"], "uma_vez", "s")
    assert cartao_de_destrutiva("memoria", {"acao": "esquecer"}, "s") is None
    assert cartao_de_destrutiva("memoria", {"acao": "esquecer"}, "s")["precisa_permissao"]


async def test_o_turno_para_no_cartao_antes_de_apagar():
    class Memoria:
        def __init__(self):
            self.esquecidas = 0

        async def forget(self, user_id, termo=None):
            self.esquecidas += 1
            return 1

        async def all(self, user_id):
            return []

    memoria = Memoria()
    planner = _Nativo([("memoria", {"acao": "esquecer"}), "Pronto."])
    orq = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store(), memory=memoria)
    resultado = await orq.handle_message(AnalysisState.new("s-destrutiva", "u"), "esqueça a memoria inteira")
    assert resultado.get("permissao"), "a ação destrutiva precisa abrir o cartão"
    assert memoria.esquecidas == 0


async def test_passo_que_pausa_no_cartao_fecha_como_pendente():
    """O turno acaba no cartão e a retomada abre um passo novo: o que pausou
    precisa fechar, senão a mensagem mostra um passo rodando para sempre."""
    class Memoria:
        async def forget(self, user_id, termo=None):
            return 1

        async def all(self, user_id):
            return []

    eventos = []
    planner = _Nativo([("memoria", {"acao": "esquecer"}), "Pronto."])
    orq = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store(), memory=Memoria())
    await orq.handle_message(AnalysisState.new("s-pausa", "u"), "esqueça a memoria inteira",
                             progress_cb=eventos.append)
    iniciados = {e["id"] for e in eventos if e.get("type") == "tool_start"}
    fechados = {e["id"]: e["status"] for e in eventos if e.get("type") == "tool_complete"}
    assert iniciados and iniciados <= set(fechados)
    assert "pending" in fechados.values()
    tipos = [e.get("type") for e in eventos]
    assert tipos.index("permissao") > max(i for i, t in enumerate(tipos) if t == "tool_complete")
