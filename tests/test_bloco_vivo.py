"""O bloco vivo: HTML e SVG do modelo rodam isolados, com o kit do Sentury.

O quadro roda script mas nunca ganha a origem da página; o documento corta
rede e recurso de fora; os ícones que a skill promete ao modelo são os que o
código monta.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

CLIENT = Path("sentury/client")
BLOCO = CLIENT / "src/domain/blocoVivo"
SKILL = Path("sentury/skills/creative/bloco-vivo/SKILL.md")

CARREGADOR = r"""
const fs = require('fs'), path = require('path'), ts = require('typescript');
const assert = require('node:assert/strict');
const cache = new Map();
function carregar(nome) {
  const arquivo = path.resolve(nome);
  if (cache.has(arquivo)) return cache.get(arquivo).exports;
  const modulo = {exports: {}}; cache.set(arquivo, modulo);
  const codigo = ts.transpileModule(fs.readFileSync(arquivo, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}
  }).outputText;
  const local = nome => {
    if (nome.endsWith('?raw')) return {default: fs.readFileSync(path.resolve(path.dirname(arquivo), nome.slice(0, -4)), 'utf8')};
    return nome.startsWith('.') ? carregar(path.resolve(path.dirname(arquivo), nome + '.ts')) : require(nome);
  };
  new Function('require', 'exports', 'module', codigo)(local, modulo.exports, modulo);
  return modulo.exports;
}
"""


def _rodar(script):
    node = shutil.which("node")
    if not node or not (CLIENT / "node_modules/lucide-react").exists():
        pytest.skip("o teste precisa das dependências locais do client")
    resultado = subprocess.run([node, "-e", CARREGADOR + script], cwd=CLIENT,
                               capture_output=True, text=True, timeout=60)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    return resultado.stdout


def _icones_do_codigo():
    return re.findall(r"icons/([a-z0-9-]+)\.mjs", (BLOCO / "icones.ts").read_text(encoding="utf-8"))


def test_os_icones_da_skill_sao_os_do_codigo():
    texto = SKILL.read_text(encoding="utf-8")
    lista = texto.split("com NOME um destes:", 1)[1].split("\n\n", 2)[1]
    da_skill = [n.strip() for n in lista.replace("\n", " ").split(",") if n.strip()]
    assert da_skill == _icones_do_codigo()


def test_o_quadro_roda_script_mas_nunca_ganha_a_origem_da_pagina():
    moldura = (BLOCO / "moldura.ts").read_text(encoding="utf-8")
    markdown = (CLIENT / "src/domain/markdown.ts").read_text(encoding="utf-8")
    assert re.findall(r"setAttribute\('sandbox', '([^']*)'\)", moldura) == ["allow-scripts"]
    assert "sandbox" not in markdown, "o quadro só nasce na moldura"
    limpeza = markdown.split("DOMPurify.sanitize(", 1)[1].split("});", 1)[0]
    for proibido in ("'iframe'", "'srcdoc'", "'sandbox'", "'style'"):
        assert proibido not in limpeza, f"{proibido} passaria pela limpeza vindo do modelo"


EMPACOTADOR = r"""
const path = require('path'), fs = require('fs'), esbuild = require('esbuild');
const raw = {name: 'raw', setup(b) {
  b.onResolve({filter: /\?raw$/}, a => ({path: path.resolve(a.resolveDir, a.path.slice(0, -4)), namespace: 'raw'}));
  b.onLoad({filter: /.*/, namespace: 'raw'}, a => ({contents: fs.readFileSync(a.path, 'utf8'), loader: 'text'}));
}};
esbuild.build({
  stdin: {contents: "export {renderMarkdown, cercarHtmlSolto} from './src/domain/markdown';"
    + "export {aoClicarNoCodigo} from './src/domain/blocoVivo/visualizar';", resolveDir: '.', loader: 'ts'},
  bundle: true, format: 'iife', globalName: 'Md', platform: 'browser', outfile: process.argv[1], plugins: [raw], logLevel: 'error',
}).catch(e => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def navegador(tmp_path_factory):
    """O markdown do client num Chromium de verdade, com o DOMPurify real: a
    limpeza do HTML é onde o bloco vivo pode sumir sem erro nenhum."""
    sync_api = pytest.importorskip("playwright.sync_api")
    node = shutil.which("node")
    if not node or not (CLIENT / "node_modules/esbuild").exists():
        pytest.skip("o teste precisa das dependências locais do client")
    pacote = tmp_path_factory.mktemp("bloco") / "markdown.js"
    gerado = subprocess.run([node, "-e", EMPACOTADOR, str(pacote)], cwd=CLIENT,
                            capture_output=True, text=True, timeout=120)
    assert gerado.returncode == 0, gerado.stderr
    with sync_api.sync_playwright() as p:
        try:
            from sentury.tools.navegador_local import abrir

            chromium = abrir(p, headless=True)
        except Exception as erro:  # sem Chrome e sem o navegador do Playwright
            pytest.skip(f"sem navegador para o teste: {erro}")
        pagina = chromium.new_page()
        pagina.set_content("<!doctype html><meta charset=utf-8><body><div id=r></div></body>")
        pagina.add_script_tag(path=str(pacote))
        yield pagina
        chromium.close()


def _montar(pagina, md):
    return pagina.evaluate("md => { const r = document.getElementById('r'); "
                           "r.innerHTML = Md.renderMarkdown(md); return r.innerHTML; }", md)


def _corpo_do_quadro(pagina):
    quadro = pagina.locator("#r iframe.bloco-vivo__quadro").first.element_handle().content_frame()
    quadro.wait_for_load_state()
    return quadro.evaluate("document.body.innerText")


def test_vivo_e_painel_desenham_depois_da_limpeza(navegador):
    cerca = "`" * 3
    _montar(navegador, f'{cerca}vivo\n<div class="cartao">oi do bloco</div>\n{cerca}')
    assert navegador.locator("#r iframe.bloco-vivo__quadro").get_attribute("sandbox") == "allow-scripts"
    assert "oi do bloco" in _corpo_do_quadro(navegador)

    _montar(navegador, f'{cerca}painel\n[{{"tipo": "texto", "texto": "oi do painel"}}]\n{cerca}')
    assert "oi do painel" in _corpo_do_quadro(navegador)

    _montar(navegador, 'Veja:\n\n<div class="cartao">oi solto</div>\n\nFim.')
    assert "oi solto" in _corpo_do_quadro(navegador)


def test_codigo_pedido_continua_codigo_e_visualiza_quando_a_pessoa_quer(navegador):
    """Quem pede o código de uma página quer ler e copiar, não ver o resultado.
    Só `vivo` e `painel` viram quadro; `html` e `svg` ficam código, com o botão
    para visualizar quando a pessoa quiser."""
    cerca = "`" * 3
    for idioma in ("html", "svg"):
        html = _montar(navegador, f'{cerca}{idioma}\n<div class="cartao">oi</div>\n{cerca}')
        assert "<iframe" not in html, f"{idioma} não desenha sozinho"
        assert "&lt;div class=\"cartao\"&gt;oi" in html, f"{idioma} aparece como código"
        assert "data-visualizar" in html and "data-copy" in html

    navegador.evaluate("Md.aoClicarNoCodigo(document.querySelector('[data-visualizar]'))")
    assert "oi" in _corpo_do_quadro(navegador)
    assert navegador.locator("#r pre").get_attribute("hidden") == ""
    copiado = navegador.evaluate("Md.aoClicarNoCodigo(document.querySelector('[data-copy]'))")
    assert copiado.strip() == '<div class="cartao">oi</div>'

    assert "data-visualizar" not in _montar(navegador, f"{cerca}python\nprint(1)\n{cerca}")
    pedido = f"{cerca}html\n<div>oi</div>\n{cerca}"
    assert navegador.evaluate("md => Md.cercarHtmlSolto(md)", pedido) == pedido


def test_iframe_escrito_pelo_modelo_nao_passa(navegador):
    html = _montar(navegador, 'Olha <iframe src="https://exemplo.invalid/x"></iframe> aqui.')
    assert "<iframe" not in html


def test_o_documento_corta_rede_e_leva_o_kit():
    saida = _rodar(r"""
    const {documentoDoBloco} = carregar('src/domain/blocoVivo/moldura.ts');
    const doc = documentoDoBloco('<div class="cartao" id="meu">oi</div>');
    assert.match(doc, /Content-Security-Policy" content="default-src 'none'/);
    assert.ok(!/connect-src|https?:\/\/(?!www\.w3\.org)/.test(doc), 'nenhuma origem de rede liberada');
    assert.ok(doc.includes('--ouro: #f5c400'), 'tokens do Sentury');
    assert.ok(doc.includes('<div class="cartao" id="meu">oi</div></body>'), 'conteúdo no corpo');
    const ids = [...doc.matchAll(/<symbol id="ic-([a-z0-9-]+)"/g)].map(m => m[1]);
    console.log(JSON.stringify(ids));
    """)
    import json

    assert json.loads(saida.strip().splitlines()[-1]) == _icones_do_codigo()


def test_os_componentes_da_skill_sao_os_do_codigo():
    import json

    texto = SKILL.read_text(encoding="utf-8")
    secao = texto.split("Componentes (`tipo`):", 1)[1].split("```painel", 1)[0]
    da_skill = re.findall(r"^- `([a-z_]+)`:", secao, re.M)
    saida = _rodar("""
    const {TIPOS} = carregar('src/domain/blocoVivo/painel.ts');
    console.log(JSON.stringify(TIPOS));
    """)
    assert da_skill == json.loads(saida.strip().splitlines()[-1])


def test_o_painel_monta_avisa_e_nao_executa_codigo_do_modelo():
    _rodar(r"""
    const {htmlDoPainel} = carregar('src/domain/blocoVivo/painel.ts');
    const html = htmlDoPainel(JSON.stringify([
      {tipo: 'numeros', itens: [{rotulo: 'Vendas', valor: 'R$ 120,4 mil', variacao: '8%', sentido: 'bom'}]},
      {tipo: 'grafico3d'},
      {tipo: 'simulador', controle: {rotulo: 'Reajuste', min: 0, max: 20, inicial: 5},
       resultados: [{rotulo: 'ok', formula: '120.4 * (1 + x / 100)'},
                    {rotulo: 'ruim', formula: 'fetch("http://x")'}],
       enviar: 'fim </script><script>alert(1)</script>'},
    ]));
    assert.ok(html.includes('class="numero">R$ 120,4 mil'));
    assert.ok(html.includes('Componente desconhecido: grafico3d'));
    assert.ok(html.includes('120.4 * (1 + x / 100)') && !html.includes('fetch('), 'só aritmética vira fórmula');
    assert.equal(html.split('</script>').length, 2, 'o texto do modelo não fecha o script');
    assert.ok(htmlDoPainel('{"tipo": "numeros", ').includes('JSON veio incompleto'));
    assert.ok(!/new Function|eval\(/.test(html), 'a política do bloco corta eval');
    """)


def test_a_tabela_de_programas_usa_icones_e_cores_do_kit():
    import json

    apps = json.loads((BLOCO / "apps.json").read_text(encoding="utf-8"))
    assert {app["icone"] for app in apps.values()} <= set(_icones_do_codigo())
    assert all(re.fullmatch(r"#[0-9a-f]{6}", app["cor"]) for app in apps.values())


def test_programa_ganha_o_selo_da_tabela_ou_a_inicial():
    """Programa conhecido sai com o ícone e a cor dele; desconhecido ganha a
    inicial, sempre na mesma cor, em Linux ou Windows, sem pacote nenhum."""
    _rodar(r"""
    const {htmlDoPainel} = carregar('src/domain/blocoVivo/painel.ts');
    const html = htmlDoPainel(JSON.stringify([{tipo: 'lista', itens: [
      {app: 'Steam', valor: '151 GB'}, {app: 'VS Code'}, {app: 'Zorbix'}]}]));
    assert.ok(html.includes('#ic-gamepad-2') && html.includes('#1b2838'), 'Steam da tabela');
    assert.ok(html.includes('<b>Steam</b>') && html.includes('<b>VS Code</b>'), 'o nome vira título');
    assert.ok(html.includes('#ic-code'), 'apelido "VS Code" acha o vscode');
    assert.ok(html.includes('selo--letra') && html.includes('>Z</span>'), 'desconhecido ganha a inicial');
    const tom = h => h.match(/selo--letra" style="background:(#[0-9a-f]+)/)[1];
    const de_novo = htmlDoPainel(JSON.stringify([{tipo: 'lista', itens: [{app: 'zorbix'}]}]));
    assert.equal(tom(html), tom(de_novo), 'o mesmo programa tem sempre a mesma cor');
    const progresso = htmlDoPainel(JSON.stringify([{tipo: 'progresso', itens: [{app: 'spotify', usado: 2, total: 10}]}]));
    assert.ok(progresso.includes('#ic-music') && progresso.includes('<b>Spotify</b>'));
    """)
