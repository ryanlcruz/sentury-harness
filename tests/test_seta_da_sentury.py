"""A borda, a seta e o balao da Sentury na pagina que ela controla.

Tres coisas que nao podem quebrar, cada uma com o Chromium de verdade:
- o modelo nao le a sobreposicao (arvore de acessibilidade e texto da pagina);
- o clique passa por ela;
- o print sai sem ela.

Precisa de um Chromium. O do Playwright instalado costuma ser outra revisao
do que existe na maquina; o teste acha um em /opt/pw-browsers ou em
SENTURY_TESTE_CHROMIUM e o passa como executavel.
"""
import glob
import os
from pathlib import Path

import pytest

from sentury.tools import browser_sobreposicao as sob
from sentury.tools.browser_contracts import Action


def _chromium():
    candidatos = [os.environ.get("SENTURY_TESTE_CHROMIUM") or ""]
    candidatos += sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"), reverse=True)
    return next((c for c in candidatos if c and Path(c).is_file()), None)


try:
    import playwright  # noqa: F401
    _TEM_PLAYWRIGHT = True
except ImportError:
    _TEM_PLAYWRIGHT = False

precisa_de_navegador = pytest.mark.skipif(
    not (_TEM_PLAYWRIGHT and _chromium()), reason="sem Playwright ou sem Chromium local")

PAGINA = """<!doctype html><html lang="pt-BR"><body>
<h1>Vagas</h1>
<label>Busca <input id="busca" aria-label="Busca"></label>
<button id="b" onclick="window.cliques=(window.cliques||0)+1"
  style="position:fixed;left:0;top:0;width:100vw;height:100vh">Filtrar remoto</button>
</body></html>"""


class TestRotulo:
    def test_digitar_mostra_o_campo_e_nunca_o_texto(self):
        texto = sob.rotulo("digitar", {"ref": "e1", "texto": "minha-senha-123"}, "Senha")
        assert texto == "digitar em “Senha”" and "minha-senha" not in texto

    def test_navegar_mostra_so_o_site(self):
        assert sob.rotulo("navegar", {"url": "https://vagas.exemplo.com.br/busca?q=x"}) == \
            "navegar · vagas.exemplo.com.br"

    def test_nome_comprido_encurta(self):
        assert sob.rotulo("clicar", {}, "x" * 100).endswith("…”")


class TestQuandoAparece:
    @pytest.mark.parametrize("valor,esperado", [("sim", True), ("nao", False), ("0", False)])
    def test_explicito(self, valor, esperado):
        assert sob.navegador_visivel(valor) is esperado

    def test_auto_no_linux_depende_de_tela(self, monkeypatch):
        monkeypatch.setattr(sob.sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert sob.navegador_visivel("auto") is False
        monkeypatch.setenv("DISPLAY", ":0")
        assert sob.navegador_visivel("auto") is True

    def test_sem_tela_nao_injeta(self):
        from sentury.tools.browser_playwright_provider import PlaywrightBrowserSession

        assert PlaywrightBrowserSession("s", headless=True)._sobreposicao is False
        assert PlaywrightBrowserSession("s", headless=False)._sobreposicao is True


@pytest.fixture
async def pagina():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        navegador = await p.chromium.launch(executable_path=_chromium())
        contexto = await navegador.new_context()
        await contexto.add_init_script(script=sob.SCRIPT)
        pg = await contexto.new_page()
        await pg.set_content(PAGINA)
        yield pg
        await navegador.close()


def _estado(pg):
    return pg.evaluate("() => window.__tato.estado()")


@precisa_de_navegador
class TestNaPagina:
    async def test_aponta_e_acende(self, pagina, monkeypatch):
        monkeypatch.setenv("SENTURY_BROWSER_SETA_MS", "0")
        await sob.apontar_para(pagina, pagina.locator("#busca"), "digitar em “Busca”")
        estado = await _estado(pagina)
        assert estado["ligada"] and estado["texto"] == "digitar em “Busca”"
        assert estado["posicao"].startswith("translate(")

    async def test_o_modelo_nao_le_a_sobreposicao(self, pagina):
        await sob.apontar(pagina, 10, 10, "clicar · “Filtrar remoto”", esperar=False)
        cdp = await pagina.context.new_cdp_session(pagina)
        arvore = await cdp.send("Accessibility.getFullAXTree")
        nomes = " ".join(str((n.get("name") or {}).get("value") or "")
                         for n in arvore["nodes"] if not n.get("ignored"))
        assert "Sentury" not in nomes and "Filtrar remoto" in nomes
        assert "Sentury" not in await pagina.locator("body").inner_text()

    async def test_nenhuma_leitura_da_pagina_ve_a_camada(self, pagina):
        """Todo caminho por onde o Sentury le a pagina: HTML, texto, arvore."""
        await sob.apontar(pagina, 10, 10, "clicar · “Filtrar remoto”", esperar=False)
        html = sob.sem_sobreposicao(await pagina.content())
        assert "sentury" not in html.lower() and "Filtrar remoto" in html
        assert "usando esta aba" not in await pagina.evaluate("document.documentElement.textContent")
        assert "Sentury" not in await pagina.evaluate("document.documentElement.innerText")

    async def test_o_clique_passa_pela_sobreposicao(self, pagina):
        await sob.apontar(pagina, 200, 200, "clicar", clique=True, esperar=False)
        await pagina.locator("#b").click(timeout=2000)
        assert await pagina.evaluate("() => window.cliques") == 1

    async def test_o_print_e_identico_ao_da_pagina_sem_camada(self, pagina):
        """Pixel a pixel: o print com a camada escondida e o mesmo da pagina
        sem camada nenhuma. E com ela acesa ele muda: o teste mede algo."""
        await sob.apontar(pagina, 200, 200, "clicar", esperar=False)
        await pagina.wait_for_timeout(400)
        aceso = await pagina.screenshot(animations="disabled")
        await sob.esconder(pagina)
        escondido = await pagina.screenshot(animations="disabled")
        await pagina.evaluate("() => document.querySelector('tato-sobreposicao').remove()")
        sem_camada = await pagina.screenshot(animations="disabled")
        assert escondido == sem_camada
        assert aceso != sem_camada

    async def test_o_campo_ganha_contorno_e_a_proxima_acao_o_apaga(self, pagina, monkeypatch):
        monkeypatch.setenv("SENTURY_BROWSER_SETA_MS", "0")
        busca = pagina.locator("#busca")
        caixa = await busca.bounding_box()
        await sob.apontar_para(pagina, busca, "digitar em “Busca”", contornar=True)
        campo = (await _estado(pagina))["campo"]
        assert campo == {"left": f"{round(caixa['x'])}px", "top": f"{round(caixa['y'])}px",
                         "width": f"{round(caixa['width'])}px", "height": f"{round(caixa['height'])}px"}
        await sob.apontar(pagina, 200, 200, "clicar", clique=True, esperar=False)
        assert (await _estado(pagina))["campo"] is None

    async def test_clicar_nao_contorna(self, pagina, monkeypatch):
        monkeypatch.setenv("SENTURY_BROWSER_SETA_MS", "0")
        await sob.apontar_para(pagina, pagina.locator("#busca"), "clicar", clique=True)
        assert (await _estado(pagina))["campo"] is None

    async def test_o_contorno_tambem_fica_fora_da_leitura(self, pagina, monkeypatch):
        monkeypatch.setenv("SENTURY_BROWSER_SETA_MS", "0")
        await sob.apontar_para(pagina, pagina.locator("#busca"), "digitar em “Busca”", contornar=True)
        assert "sentury" not in sob.sem_sobreposicao(await pagina.content()).lower()
        await pagina.locator("#busca").fill("remoto", timeout=2000)
        assert await pagina.locator("#busca").input_value() == "remoto"

    async def test_com_movimento_a_borda_pulsa_e_a_seta_desliza(self, pagina):
        await sob.apontar(pagina, 10, 10, "ver", esperar=False)
        estado = await _estado(pagina)
        assert estado["animacaoDaBorda"] == "pulso" and estado["transicaoDaSeta"] == "0.45s"

    async def test_movimento_reduzido_a_borda_para_e_a_seta_pula(self, pagina):
        await pagina.emulate_media(reduced_motion="reduce")
        await sob.apontar(pagina, 10, 10, "ver", esperar=False)
        estado = await _estado(pagina)
        assert estado["animacaoDaBorda"] == "none" and estado["transicaoDaSeta"] == "0s"
        assert estado["ligada"] and estado["texto"] == "ver"

    async def test_o_print_sai_sem_ela(self, pagina):
        await sob.apontar(pagina, 50, 50, "ver", esperar=False)
        await sob.esconder(pagina)
        assert (await _estado(pagina))["visivel"] is False
        await sob.mostrar(pagina)
        assert (await _estado(pagina))["visivel"] is True


@precisa_de_navegador
async def test_a_sessao_anuncia_antes_de_agir(monkeypatch):
    """Pela sessao de verdade: o balao diz o nome do alvo lido na arvore."""
    from playwright.async_api._generated import BrowserType

    from sentury.tools.browser_playwright_provider import PlaywrightBrowserSession

    original = BrowserType.launch

    async def launch(self, **kw):
        kw.setdefault("executable_path", _chromium())
        return await original(self, **kw)

    monkeypatch.setattr(BrowserType, "launch", launch)
    monkeypatch.setenv("SENTURY_BROWSER_SETA_MS", "0")
    fixture = Path("tests/fixtures/browser/vagas.html").resolve()
    sessao = PlaywrightBrowserSession("t", headless=True, fixture=fixture, sobreposicao=True)
    try:
        primeira = await sessao.execute(Action("snapshot", {"completo": True}))
        assert not any("Sentury" in str(i.get("name")) for i in primeira.dados["arvore"])
        botao = next(i for i in primeira.dados["arvore"] if i["name"] == "Ver vaga Python")
        await sessao.execute(Action("clicar", {"ref": botao["ref"]}))
        estado = await sessao._page.evaluate("() => window.__tato.estado()")
        assert estado["texto"] == "clicar · “Ver vaga Python”" and estado["ligada"]

        dom = await sessao.execute(Action("snapshot", {"representacao": "dom"}))
        assert "tato-sobreposicao" not in dom.dados and "Ver vaga Python" in dom.dados

        imagem = await sessao.execute(Action("imagens", {}))
        assert imagem.metadados["screenshot"] is True
        assert (await sessao._page.evaluate("() => window.__tato.estado()"))["visivel"] is True
    finally:
        await sessao.aclose()


@precisa_de_navegador
async def test_a_sessao_contorna_o_campo_ao_digitar(monkeypatch, tmp_path):
    """O `digitar` da sessao contorna o campo; o balao continua sem o texto."""
    from playwright.async_api._generated import BrowserType

    from sentury.tools.browser_playwright_provider import PlaywrightBrowserSession

    original = BrowserType.launch

    async def launch(self, **kw):
        kw.setdefault("executable_path", _chromium())
        return await original(self, **kw)

    monkeypatch.setattr(BrowserType, "launch", launch)
    monkeypatch.setenv("SENTURY_BROWSER_SETA_MS", "0")
    fixture = tmp_path / "login.html"
    fixture.write_text('<!doctype html><html lang="pt-BR"><body><h1>Entrar</h1>'
                       '<label>Senha <input type="password" aria-label="Senha"></label></body></html>',
                       encoding="utf-8")
    sessao = PlaywrightBrowserSession("t", headless=True, fixture=fixture, sobreposicao=True)
    try:
        arvore = (await sessao.execute(Action("snapshot", {"completo": True}))).dados["arvore"]
        senha = next(i for i in arvore if i["name"] == "Senha" and i.get("ref"))
        await sessao.execute(Action("digitar", {"ref": senha["ref"], "texto": "minha-senha-123"}))
        estado = await sessao._page.evaluate("() => window.__tato.estado()")
        assert estado["campo"] is not None
        assert estado["texto"] == "digitar em “Senha”" and "minha-senha" not in estado["texto"]
    finally:
        await sessao.aclose()


@precisa_de_navegador
class TestBordaViva:
    """A borda fica enquanto a aba é do Sentury; a seta e o balão são o
    instante da ação. Juntas, a borda sumia entre uma ação e outra."""

    async def test_a_pagina_nasce_com_a_borda_acesa(self, pagina):
        estado = await _estado(pagina)
        assert estado["borda"] and not estado["ligada"]

    async def test_o_fim_do_turno_tira_a_seta_e_deixa_a_borda(self, pagina, monkeypatch):
        monkeypatch.setenv("SENTURY_BROWSER_SETA_MS", "0")
        await sob.apontar_para(pagina, pagina.locator("#busca"), "digitar em “Busca”")
        await pagina.evaluate("() => window.__tato.soltar()")
        estado = await _estado(pagina)
        assert estado["borda"] and not estado["ligada"]

    async def test_o_fim_da_sessao_tira_tudo(self, pagina):
        await pagina.evaluate("() => window.__tato.encerrar()")
        estado = await _estado(pagina)
        assert not estado["borda"] and not estado["ligada"]
