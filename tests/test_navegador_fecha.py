"""O navegador de uma conversa parada fecha sozinho.

A sessao e memoizada por conversa e nao fechava nunca: nem quando a conversa
acabava, nem por inatividade, nem quando o processo saia. Chromium parado
ficava aberto comendo memoria.
"""
import asyncio

import pytest

from sentury.harness.state import AnalysisState
from sentury.tools import browser_registry, permissoes
from sentury.tools.browser_contracts import Action, BrowserCapability, Observation
from sentury.tools.browser_provider import BrowserProvider


class _Sessao(BrowserCapability):
    def __init__(self, session_id, dono, demora=0.0):
        self.session_id = session_id
        self._dono = dono
        self._demora = demora

    async def execute(self, action):
        if self._demora:
            await asyncio.sleep(self._demora)
        return Observation(fonte="falso", dados={})


class _Provedor(BrowserProvider):
    def __init__(self, demora=0.0):
        self.abertas, self.fechadas = [], []
        self._demora = demora

    @property
    def name(self):
        return "falso"

    def is_available(self):
        return True

    def create_session(self, task_id):
        self.abertas.append(task_id)
        return _Sessao(f"falso:{task_id}", self, self._demora)

    def close_session(self, session_id):
        self.fechadas.append(session_id)
        return True

    def emergency_cleanup(self, session_id):
        return None


@pytest.fixture
def provedor(monkeypatch):
    browser_registry._limpar_para_testes()
    monkeypatch.setattr(permissoes, "avaliar", lambda *a, **k: {
        "permitido": True, "precisa_perguntar": False, "chave": "x", "motivo": "teste"})
    falso = _Provedor()
    browser_registry.registrar(falso)
    yield falso
    browser_registry._limpar_para_testes()


async def _usar(sessao):
    return await browser_registry.despachar(
        Action("snapshot", {}), AnalysisState.new(sessao, "u"), provider_name="falso")


class TestOcioso:
    async def test_padrao_preserva_a_sessao_entre_turnos(self, provedor, monkeypatch):
        from sentury.config import settings

        monkeypatch.setattr(settings, "SENTURY_BROWSER_OCIOSO_MIN", 0)
        await _usar("conversa-1")
        assert browser_registry.fechar_ociosos(agora=__import__("time").time() + 86400) == 0
        assert browser_registry.esta_aberta("conversa-1")
        assert provedor.abertas == ["conversa-1"] and provedor.fechadas == []

        await _usar("conversa-1")
        assert provedor.abertas == ["conversa-1"], "outro turno deve reutilizar a mesma pagina"

    async def test_sessao_que_falha_ao_verificar_saude_e_recriada(self, provedor, monkeypatch):
        await _usar("conversa-1")
        sessao = browser_registry._SESSOES[("conversa-1", "falso")]

        def falha():
            raise RuntimeError("navegador desconectado")

        monkeypatch.setattr(sessao, "esta_viva", falha, raising=False)
        await _usar("conversa-1")
        assert provedor.abertas == ["conversa-1", "conversa-1"]
        assert provedor.fechadas == [sessao.session_id]

    async def test_parado_alem_do_prazo_fecha(self, provedor):
        await _usar("conversa-1")
        daqui_a_11_min = __import__("time").time() + 11 * 60

        assert browser_registry.fechar_ociosos(10, agora=daqui_a_11_min) == 1
        assert provedor.fechadas == ["falso:conversa-1"]

    async def test_usado_ha_pouco_fica(self, provedor):
        await _usar("conversa-1")
        assert browser_registry.fechar_ociosos(10) == 0
        assert provedor.fechadas == []

    async def test_fechado_por_ocio_reabre_na_proxima_acao(self, provedor):
        await _usar("conversa-1")
        browser_registry.fechar_ociosos(10, agora=__import__("time").time() + 3600)
        await _usar("conversa-1")
        assert provedor.abertas == ["conversa-1", "conversa-1"]

    async def test_acao_em_curso_nunca_fecha(self, monkeypatch):
        """Um roteiro longo nao pode perder a pagina no meio."""
        browser_registry._limpar_para_testes()
        monkeypatch.setattr(permissoes, "avaliar", lambda *a, **k: {
            "permitido": True, "precisa_perguntar": False, "chave": "x", "motivo": "teste"})
        lento = _Provedor(demora=0.2)
        browser_registry.registrar(lento)
        try:
            tarefa = asyncio.create_task(_usar("conversa-lenta"))
            await asyncio.sleep(0.05)
            assert browser_registry.fechar_ociosos(10, agora=__import__("time").time() + 3600) == 0
            await tarefa
            assert lento.fechadas == []
        finally:
            browser_registry._limpar_para_testes()

    def test_zero_desliga(self, provedor):
        assert browser_registry.fechar_ociosos(0, agora=10**12) == 0


class TestFimDaConversa:
    async def test_encerrar_pelo_agente_nao_cria_outra_sessao(self, provedor):
        state = AnalysisState.new("conversa-1", "u")
        assert not browser_registry.esta_aberta(state.session_id)
        await _usar(state.session_id)
        resultado = await browser_registry.despachar(Action("encerrar"), state, provider_name="falso")
        assert resultado["ok"] and resultado["encerradas"] == 1
        assert not browser_registry.esta_aberta(state.session_id)
        assert provedor.abertas == [state.session_id]

    async def test_encerrar_todos_na_saida(self, provedor):
        await _usar("conversa-1")
        await _usar("conversa-2")
        assert browser_registry.encerrar_todos() == 2

    async def test_apagar_a_conversa_fecha_o_navegador_dela(self, provedor, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        import sentury.main as main

        class _Store:
            async def delete(self, session_id):
                pass

        class _Indice:
            async def remove(self, user_id, session_id):
                pass

        monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
        monkeypatch.setattr(main, "session_store", _Store())
        monkeypatch.setattr(main, "session_index", _Indice())
        await _usar("conversa-1")
        await _usar("conversa-2")
        main.app.dependency_overrides[main.verify_api_token] = lambda: None
        try:
            # Sem o `with`: o startup registraria o Playwright real e o laco.
            TestClient(main.app).delete("/sentury/sessions/conversa-1?user_id=eu")
        finally:
            main.app.dependency_overrides.clear()

        assert provedor.fechadas == ["falso:conversa-1"]


class TestDoisTurnosNoMesmoNavegador:
    """A regra e RECUSA: a acao do turno novo entrava entre os passos do roteiro
    do anterior e mudava a pagina debaixo dele. Fila deixaria o turno novo
    parado em silencio atras de um roteiro longo."""

    @pytest.fixture
    def lento(self, monkeypatch):
        browser_registry._limpar_para_testes()
        monkeypatch.setattr(permissoes, "avaliar", lambda *a, **k: {
            "permitido": True, "precisa_perguntar": False, "chave": "x", "motivo": "teste"})
        provedor = _Provedor(demora=0.2)
        browser_registry.registrar(provedor)
        yield provedor
        browser_registry._limpar_para_testes()

    async def test_segunda_acao_da_mesma_conversa_e_recusada_na_hora(self, lento):
        primeira = asyncio.create_task(_usar("conversa-1"))
        await asyncio.sleep(0.05)

        segunda = await _usar("conversa-1")
        assert segunda["ok"] is False and segunda["fase"] == "ocupado"
        assert (await primeira)["ok"] is True

    async def test_outra_conversa_nao_espera(self, lento):
        primeira = asyncio.create_task(_usar("conversa-1"))
        await asyncio.sleep(0.05)

        assert (await _usar("conversa-2"))["ok"] is True
        await primeira

    async def test_depois_que_termina_libera(self, lento):
        await _usar("conversa-1")
        assert (await _usar("conversa-1"))["ok"] is True
