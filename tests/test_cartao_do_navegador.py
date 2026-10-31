"""O cartao do navegador no chat: cada passo avisado, e o resumo guardado.

Roda no provedor falso. O cartao e montado dos eventos `navegador`, que o
registry emite pelo canal do turno (`harness/emissor.py`).
"""
from pathlib import Path

import pytest

from sentury.harness import cartao_do_navegador as cartao
from sentury.harness.emissor import EMISSOR
from sentury.harness.state import AnalysisState
from sentury.tools import browser_registry, permissoes
from sentury.tools.browser_contracts import Action
from sentury.tools.browser_fake_provider import FakeBrowserProvider

FIXTURE = Path(__file__).parent / "fixtures" / "browser" / "vagas.html"


@pytest.fixture
def eventos():
    browser_registry._limpar_para_testes()
    browser_registry.registrar(FakeBrowserProvider(FIXTURE))
    permissoes.definir_permitir_tudo(False)
    vistos = []
    token = EMISSOR.set(vistos.append)
    yield vistos
    EMISSOR.reset(token)
    browser_registry._limpar_para_testes()


def _montar(eventos):
    c = None
    for i, e in enumerate(eventos):
        c = cartao.aplicar(c, e, agora=100.0 + i)
    return c


async def _rodar(action):
    return await browser_registry.despachar(action, AnalysisState.new("conversa", "u"))


async def test_roteiro_avisa_cada_passo(eventos):
    await _rodar(Action("snapshot", {"completo": True}))  # o falso so da nome depois de ler
    await _rodar(Action("roteiro", {"passos": [
        {"acao": "clicar", "argumentos": {"ref": "e1"}, "consequencia": "nenhuma"},
        {"acao": "conferir", "argumentos": {"texto": "Engenheira Python"}},
        {"acao": "ver"},
    ]}))
    c = _montar(eventos)
    assert [p["rotulo"] for p in c["passos"]][1:] == [
        "clicar", "conferir · “Engenheira Python”", "ver · print da página"]
    assert [p["status"] for p in c["passos"]] == ["ok", "ok", "ok", "ok"]
    assert c["textos"] == 3 and c["prints"] == 1 and c["status"] == "ok"


async def test_conferir_que_falha_mostra_onde_parou(eventos):
    await _rodar(Action("roteiro", {"passos": [
        {"acao": "conferir", "argumentos": {"texto": "nao existe"}},
        {"acao": "clicar", "argumentos": {"ref": "e1"}, "consequencia": "nenhuma"},
    ]}))
    c = _montar(eventos)
    assert [p["status"] for p in c["passos"]] == ["error", "pendente"]
    assert c["status"] == "parou" and "conferir falhou" in c["motivo"]


async def test_sem_turno_ouvindo_nao_quebra():
    browser_registry._limpar_para_testes()
    browser_registry.registrar(FakeBrowserProvider(FIXTURE))
    try:
        r = await _rodar(Action("snapshot", {"completo": True}))
        assert r["ok"]
    finally:
        browser_registry._limpar_para_testes()


def test_varias_chamadas_somam_num_cartao_so():
    c = None
    for e in [
        {"fase": "inicio", "site": "a.com", "passos": [{"acao": "navegar", "rotulo": "navegar · a.com"}]},
        {"fase": "passo", "indice": 0, "status": "ok", "leitura": "texto"},
        {"fase": "fim", "status": "ok", "site": "a.com"},
        {"fase": "inicio", "site": "a.com", "passos": [{"acao": "imagens", "rotulo": "print da página"}]},
        {"fase": "passo", "indice": 0, "status": "ok", "leitura": "print"},
        {"fase": "fim", "status": "ok", "site": "a.com"},
    ]:
        c = cartao.aplicar(c, {"type": "navegador", **e}, agora=10.0)
    assert [p["rotulo"] for p in c["passos"]] == ["navegar · a.com", "print da página"]
    assert c["textos"] == 1 and c["prints"] == 1
    guardado = cartao.para_guardar(c)
    assert "_base" not in guardado and "inicio" not in guardado


def test_o_registrador_do_turno_monta_o_cartao():
    from sentury.harness.processo_do_turno import criar_registrador

    estado = AnalysisState.new("s", "u")
    registrar = criar_registrador([], estado)
    registrar({"type": "navegador", "fase": "inicio", "site": "x.com",
               "passos": [{"acao": "navegar", "rotulo": "navegar · x.com"}]})
    registrar({"type": "navegador", "fase": "fim", "status": "ok"})
    assert estado.navegador_do_turno["site"] == "x.com"


def test_retomada_e_recibo_nao_ficam_rodando():
    c = cartao.aplicar(None, {"fase": "inicio", "site": "x.com", "retomada": True,
                            "passos": [{"acao": "snapshot", "rotulo": "ler a página"}]})
    guardado = cartao.para_guardar(c)
    assert guardado["retomada"] is True
    assert guardado["status"] == "ok"


def test_o_main_guarda_o_cartao_na_mensagem():
    import sentury.main as main

    estado = AnalysisState.new("s", "u")
    estado.history.append({"role": "assistant", "content": "pronto"})
    estado.navegador_do_turno = cartao.aplicar(None, {
        "type": "navegador", "fase": "inicio", "site": "x.com",
        "passos": [{"acao": "navegar", "rotulo": "navegar · x.com"}]})
    main._attach_result_to_last_assistant(estado, {})
    assert estado.history[-1]["navegador"]["site"] == "x.com"
    assert estado.navegador_do_turno is None


async def test_mostrar_janela_sem_janela_diz_que_nao():
    browser_registry._limpar_para_testes()
    assert await browser_registry.trazer_para_frente("ninguem") is False


async def test_mostrar_janela_chama_a_sessao():
    class Sessao:
        _headless = False
        chamadas = 0

        async def trazer_para_frente(self):
            Sessao.chamadas += 1
            return True

    browser_registry._limpar_para_testes()
    browser_registry._SESSOES[("conversa", "pw")] = Sessao()
    try:
        assert await browser_registry.trazer_para_frente("conversa") is True
        assert Sessao.chamadas == 1
    finally:
        browser_registry._SESSOES.clear()


def test_cartoes_ao_vivo_vem_antes_do_passo_atual():
    """O passo atual (um shell depois do clique, por exemplo) nasce embaixo do
    cartão do computador e do navegador, na ordem em que aconteceu."""
    from pathlib import Path

    tela = Path("sentury/client/src/app/AppShell.tsx").read_text(encoding="utf-8")
    passo = tela.index("<ProcessingIndicator")
    assert tela.index("<ComputadorCard cartao={stream.computador}") < passo
    assert tela.index("<NavegadorCard cartao={stream.navegador}") < passo
