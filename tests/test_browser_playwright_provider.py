from pathlib import Path

import pytest

from sentury.tools.browser_contracts import Action
from sentury.tools.browser_playwright_provider import PlaywrightBrowserProvider


FIXTURE = Path("tests/fixtures/browser/vagas.html")

# Playwright é opcional (`pip install -e ".[extras]"` + `playwright install
# chromium`). Sem ele estes testes não têm nada a provar; quem sabe responder é
# o próprio provider, pelo `is_available()`.
pytestmark = pytest.mark.skipif(
    not PlaywrightBrowserProvider(fixture=FIXTURE).is_available(),
    reason='Playwright nao instalado (pip install -e ".[extras]")',
)


@pytest.mark.asyncio
async def test_fixture_vira_arvore_de_acessibilidade_sem_screenshot():
    provider = PlaywrightBrowserProvider(fixture=FIXTURE)
    assert provider.is_available()
    sessao = provider.create_session("pw-fixture")
    try:
        jsonld = await sessao.execute(Action("snapshot", {"representacao": "jsonld"}))
        dom = await sessao.execute(Action("snapshot", {"representacao": "dom"}))
        assert '"@type":"JobPosting"' in jsonld.dados[0]
        assert "Ver vaga Python" in dom.dados
        assert jsonld.metadados["screenshot"] is False
        assert dom.metadados["screenshot"] is False

        primeira = await sessao.execute(Action("snapshot", {"completo": True}))
        assert primeira.fonte == "playwright_accessibility"
        assert primeira.metadados["screenshot"] is False
        assert primeira.interativa is True
        botao = next(
            item for item in primeira.dados["arvore"]
            if item["role"] == "button" and item["name"] == "Ver vaga Python"
        )
        assert botao["ref"].startswith("e")

        mudou = await sessao.execute(Action("clicar", {"ref": botao["ref"]}))
        assert mudou.dados["modo"] == "diff"
        assert any(
            item["role"] == "heading" and item["name"] == "Engenheira Python"
            for item in mudou.dados["entrou"]
        )
    finally:
        await sessao.aclose()


def test_o_navegador_valida_a_url_como_navegador_da_pessoa():
    """O Playwright roda na máquina da pessoa: navegação e clique usam a regra do
    navegador (página em http ou https, local inclusive), não a da leitura
    pelo servidor."""
    from sentury.tools import browser_playwright_provider as modulo

    fonte = Path(modulo.__file__).read_text(encoding="utf-8")
    assert "web.validar_url(" not in fonte and fonte.count("web.validar_url_do_navegador(") == 3


@pytest.mark.asyncio
async def test_digitar_no_campo_em_foco_e_enviar_com_enter():
    """Clicar na busca e depois digitar sem `ref` escreve no campo em foco; `enviar`
    aperta Enter, que é como uma busca sai."""
    provider = PlaywrightBrowserProvider(fixture=Path("tests/fixtures/browser/busca.html"))
    sessao = provider.create_session("pw-busca")
    try:
        arvore = (await sessao.execute(Action("snapshot", {"completo": True}))).dados["arvore"]
        busca = next(item for item in arvore if item["role"] == "searchbox")
        await sessao.execute(Action("clicar", {"ref": busca["ref"]}))
        depois = await sessao.execute(Action("digitar", {"texto": "chatgpt", "enviar": True}))
        textos = str(depois.dados)
        assert "Resultados para chatgpt" in textos
    finally:
        await sessao.aclose()


@pytest.mark.asyncio
async def test_digitar_sem_campo_em_foco_recusa_em_vez_de_digitar_no_vazio():
    provider = PlaywrightBrowserProvider(fixture=Path("tests/fixtures/browser/busca.html"))
    sessao = provider.create_session("pw-sem-foco")
    try:
        await sessao.execute(Action("snapshot", {"completo": True}))
        with pytest.raises(ValueError, match="nenhum campo de texto com o foco"):
            await sessao.execute(Action("digitar", {"texto": "chatgpt"}))
    finally:
        await sessao.aclose()


@pytest.mark.asyncio
async def test_escolhe_opcao_de_lista_sem_clicar_na_opcao_fechada():
    """Opção de <select> fechado não tem caixa: o clique quebrava com 'Could not
    compute box model'. A opção (ou a lista com `texto`) é escolhida no controle."""
    provider = PlaywrightBrowserProvider(fixture=Path("tests/fixtures/browser/formulario.html"))
    sessao = provider.create_session("pw-lista")
    try:
        arvore = (await sessao.execute(Action("snapshot", {"completo": True}))).dados["arvore"]
        parceria = next(i for i in arvore if i["role"] == "option" and i["name"] == "Parceria")
        await sessao.execute(Action("clicar", {"ref": parceria["ref"]}))
        assert await sessao._page.evaluate("document.getElementById('assunto').value") == "Parceria"
        lista = next(i for i in arvore if i["role"] == "combobox")
        await sessao.execute(Action("digitar", {"ref": lista["ref"], "texto": "Suporte"}))
        assert await sessao._page.evaluate("document.getElementById('eventos').textContent") == "change:Parceria change:Suporte "
        with pytest.raises(ValueError, match="sem opção"):
            await sessao.execute(Action("digitar", {"ref": lista["ref"], "texto": "Vendas"}))
    finally:
        await sessao.aclose()
