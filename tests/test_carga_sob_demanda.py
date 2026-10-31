"""Quais ferramentas vão em cada chamada ao modelo.

Enquanto o catálogo inteiro cabe no teto, ele vai todo: carregar no meio do
turno é um passo a mais em que o modelo erra. Acima do teto vai o núcleo com a
ponte, que chama pelo nome sem a lista mudar. Se o catálogo inteiro não couber na
janela do modelo, o turno passa a sob demanda antes de compactar a conversa.
"""
import json

import pytest

from sentury.config import settings
from sentury.data.store import SemDados
from sentury.harness import descoberta
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState

ARGUMENTOS = {"nome": "nina", "papel": "organizadora", "objetivo": "manter as tarefas em dia",
              "ferramentas": ["buscar_web"]}


class Modelo:
    """Anota as ferramentas de cada chamada e responde o que o teste mandar."""

    supports_tools = True
    last_model = "teste:nativo"

    def __init__(self, respostas=(), recusar_acima_de=None):
        self.respostas = list(respostas)
        self.recusar_acima_de = recusar_acima_de
        self.listas = []
        self.last_tool_calls = None

    async def complete(self, messages, **kwargs):
        nomes = {t["function"]["name"] for t in kwargs.get("tools") or []}
        self.listas.append(nomes)
        if self.recusar_acima_de is not None and len(nomes) > self.recusar_acima_de:
            raise Recusa()
        resposta = self.respostas.pop(0) if self.respostas else None
        self.last_tool_calls = [{"id": "c1", "function": resposta}] if resposta else None
        return "" if resposta else "fim"


class Recusa(Exception):
    """Como a cadeia recusa um pedido maior que a janela de todos os provedores."""

    tipos = ["context_length"]


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_PROGRESSIVE_CAPABILITIES", True)


async def _turno(modelo, mensagem="me ajude com uma coisa"):
    orq = SenturyOrchestrator(planner=modelo, responder=modelo, store=SemDados())
    return await orq.handle_message(AnalysisState.new("sob-demanda", "u"), mensagem)


async def test_abaixo_do_teto_vai_o_catalogo_inteiro_sem_ponte(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_FERRAMENTAS_TETO_TOKENS", 10**6)
    modelo = Modelo()
    await _turno(modelo)
    assert "criar_agente" in modelo.listas[0], "o catálogo inteiro traz o que a busca não acharia"
    assert "usar_ferramenta" not in modelo.listas[0]


async def test_acima_do_teto_vai_o_nucleo_com_a_ponte(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_FERRAMENTAS_TETO_TOKENS", 0)
    modelo = Modelo()
    await _turno(modelo)
    assert "usar_ferramenta" in modelo.listas[0] and "search_tools" in modelo.listas[0]
    assert "criar_agente" not in modelo.listas[0]


async def test_a_ponte_vira_a_ferramenta_de_dentro_antes_da_permissao(monkeypatch):
    """Permissão, cartão e tela veem `criar_agente`; a ponte não fura a aprovação."""
    monkeypatch.setattr(settings, "SENTURY_FERRAMENTAS_TETO_TOKENS", 0)
    pela_ponte = {"name": "usar_ferramenta",
                  "arguments": json.dumps({"nome": "criar_agente", "argumentos": ARGUMENTOS})}
    saida = await _turno(Modelo([pela_ponte]))
    assert (saida.get("permissao") or {}).get("ferramenta") == "criar_agente"


@pytest.mark.parametrize("passo", [
    {"tool": "usar_ferramenta", "arguments": {}},
    {"tool": "usar_ferramenta", "arguments": {"nome": "usar_ferramenta", "argumentos": {}}},
    {"tool": "ler_arquivo", "arguments": {"caminho": "x"}},
])
def test_a_ponte_sem_nome_ou_apontando_para_si_fica_como_veio(passo):
    assert descoberta.desembrulhar(passo) == passo


def test_a_ponte_aceita_argumentos_em_texto_e_limpa_o_prefixo():
    passo = {"tool": "usar_ferramenta", "id": "c9",
             "arguments": {"nome": "default_api:ler_arquivo", "argumentos": '{"caminho": "a.txt"}'}}
    assert descoberta.desembrulhar(passo) == {"tool": "ler_arquivo", "id": "c9", "arguments": {"caminho": "a.txt"}}


async def test_catalogo_que_nao_cabe_passa_a_sob_demanda_antes_de_compactar(monkeypatch):
    """A janela pequena recusa a lista inteira; a nova tentativa sai com o núcleo
    e a ponte, e a conversa não é compactada por isso."""
    monkeypatch.setattr(settings, "SENTURY_FERRAMENTAS_TETO_TOKENS", 10**6)
    compactou = []

    async def compactar(*_a, **_k):
        compactou.append(True)
        return True

    monkeypatch.setattr("sentury.harness.pedido_grande.compactar_para_caber", compactar)
    modelo = Modelo(recusar_acima_de=20)
    saida = await _turno(modelo)
    assert len(modelo.listas[0]) > 20 and "usar_ferramenta" not in modelo.listas[0]
    assert "usar_ferramenta" in modelo.listas[1] and len(modelo.listas[1]) <= 20
    assert compactou == []
    assert saida.get("message") == "fim"
