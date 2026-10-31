"""A acao de navegador com consequencia para, pergunta, e roda quando autorizada.

Antes, o gate recusava a acao sem autorizacao e o laco tratava isso como
bloqueio: o agente tentava, desistia, e o cartao nunca abria. Com
`permitir_tudo` ligado era pior: rodava sem perguntar nada.
"""
import json

import pytest

from sentury.data.store import SemDados
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.tools import browser_registry, permissoes
from sentury.tools.browser_contracts import Observation
from sentury.tools.browser_provider import BrowserProvider

URL = "https://exemplo.com/vagas"


class _Sessao:
    def __init__(self, dono):
        self.session_id = "s"
        self._dono = dono

    async def execute(self, action):
        self._dono.acoes.append(action.para_dict())
        return Observation(fonte="falso", dados={"url": action.argumentos.get("url")})


class _ProvedorFalso(BrowserProvider):
    def __init__(self):
        self.acoes = []

    @property
    def name(self):
        return "falso"

    def is_available(self):
        return True

    def create_session(self, task_id):
        return _Sessao(self)

    def close_session(self, session_id):
        return True

    def emergency_cleanup(self, session_id):
        return None


class _Planner:
    last_model = "planner"

    def __init__(self, respostas):
        self.respostas = list(respostas)

    async def complete(self, messages, *args, **kwargs):
        return self.respostas.pop(0) if self.respostas else json.dumps({"plan": []})


class _Responder:
    last_model = "responder"

    async def complete(self, messages, *args, **kwargs):
        return "feito"


@pytest.fixture
def provedor(monkeypatch):
    monkeypatch.setattr("sentury.tools.web._enderecos", lambda _host: ["93.184.216.34"])
    browser_registry._limpar_para_testes()
    falso = _ProvedorFalso()
    browser_registry.registrar(falso)
    yield falso
    browser_registry._limpar_para_testes()


def _orq(plano):
    return SenturyOrchestrator(planner=_Planner([json.dumps({"plan": plano})]),
                               responder=_Responder(),
                               store=SemDados(), memory=None, skills=None)


@pytest.mark.asyncio
async def test_clicar_abre_o_cartao_e_a_aprovacao_executa_sem_pedir_de_novo(provedor):
    passo = {"tool": "browser", "arguments": {"acao": "clicar", "argumentos": {"ref": "candidatar"}}}
    orq = _orq([passo])
    state = AnalysisState.new("browser-e2e", "u")
    permissoes.definir_permitir_tudo(False)

    await orq.handle_message(state, "se candidata nessa vaga")

    pendente = state.tarefa_pendente
    assert pendente, "a acao nao parou para perguntar"
    assert pendente["ferramenta"] == "browser"
    assert pendente["argumentos"]["argumentos"]["ref"] == "candidatar"
    assert provedor.acoes == [], "rodou antes da autorizacao"

    # o que o cartao manda quando a pessoa clica "so desta vez"
    permissoes.responder("browser_clicar candidatar", "uma_vez", state.session_id)
    await orq.handle_message(state, "pode seguir")

    assert state.tarefa_pendente is None, state.tarefa_pendente
    assert provedor.acoes == [{"acao": "clicar", "argumentos": {"ref": "candidatar"}}]


@pytest.mark.asyncio
async def test_navegar_nao_pergunta(provedor):
    passo = {"tool": "browser", "arguments": {"acao": "navegar", "argumentos": {"url": URL}}}
    state = AnalysisState.new("browser-nav", "u")
    permissoes.definir_permitir_tudo(False)

    await _orq([passo]).handle_message(state, "abre a pagina de vagas")

    assert state.tarefa_pendente is None
    assert provedor.acoes == [{"acao": "navegar", "argumentos": {"url": URL}}]


def test_consultar_nao_gasta_o_credito_de_uma_vez():
    """A pre-checagem do plano consulta antes de executar; se gastasse o
    credito ali, a execucao perguntava de novo (valia para o shell tambem)."""
    permissoes.definir_permitir_tudo(False)
    permissoes.responder("git push", "uma_vez", "sessao-credito")
    assert permissoes.avaliar("git push", "sessao-credito", consumir=False)["permitido"]
    assert permissoes.avaliar("git push", "sessao-credito")["permitido"]
    assert not permissoes.avaliar("git push", "sessao-credito")["permitido"]
