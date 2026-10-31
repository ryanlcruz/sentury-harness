"""O catálogo vira lista numerada de links, sem navegador."""
from sentury.tools.destilador import em_linhas, links_numerados

BASE = "https://vagas.exemplo.com/lista"

CATALOGO = """
<html><head><title>Vagas</title><script>var rastreio = "x".repeat(9000);</script>
<style>.a{color:red}</style></head><body>
<nav><a href="/">Início</a> <a href="#topo">Topo</a> <a href="javascript:void(0)">Menu</a></nav>
<ul>
  <li><a href="/vaga/1"><span>Engenheira Python</span> · Remoto</a></li>
  <li><a href="/vaga/2">Backend Júnior Go</a></li>
  <li><a href="/vaga/1#detalhes">Engenheira Python (de novo)</a></li>
  <li><a href="https://empresa.exemplo.com/carreiras">Carreiras da empresa</a></li>
  <li><a href="/vaga/3">saiba mais</a></li>
  <li><a href="mailto:rh@exemplo.com">Fale com o RH</a></li>
</ul>
</body></html>
"""


def test_links_uteis_em_ordem_com_url_absoluta():
    links = links_numerados(CATALOGO, BASE)
    assert [l["url"] for l in links] == [
        "https://vagas.exemplo.com/",
        "https://vagas.exemplo.com/vaga/1",
        "https://vagas.exemplo.com/vaga/2",
        "https://empresa.exemplo.com/carreiras",
    ]
    assert links[1]["texto"] == "Engenheira Python · Remoto"
    assert [l["n"] for l in links] == [1, 2, 3, 4]


def test_forma_compacta_e_bem_menor_que_o_html():
    pagina = CATALOGO + "<div>" + ("<span class='x'>enfeite</span>" * 400) + "</div>"
    linhas = em_linhas(links_numerados(pagina, BASE))
    assert "[2] Engenheira Python · Remoto -> https://vagas.exemplo.com/vaga/1" in linhas
    assert len(linhas) * 20 < len(pagina)


def test_html_quebrado_nao_derruba():
    assert links_numerados("<a href='/x'>X", BASE)[0]["url"] == "https://vagas.exemplo.com/x"
    assert links_numerados("", BASE) == []


from sentury.tools.destilador import em_partes, procurar, regiao_principal

PAGINA_COM_MENU = (
    "<html><body><div id='menu'>" + " ".join(f"<a href='/p{i}'>Pais {i}</a>" for i in range(80)) + "</div>"
    "<main><h1>Vaga de backend</h1>" + "<p>Requisito: Python e SQL. </p>" * 40 + "</main></body></html>"
)


def test_regiao_principal_tira_o_menu():
    principal = regiao_principal(PAGINA_COM_MENU)
    assert "Requisito" in principal and "Pais 3" not in principal


def test_pagina_sem_regiao_marcada_fica_inteira():
    assert regiao_principal(CATALOGO) == CATALOGO


def test_link_de_outro_idioma_fica_fora():
    html = "<a href='/a' hreflang='af'>Afrikaans</a><a href='/b'>Conteudo</a>"
    assert [l["texto"] for l in links_numerados(html, BASE)] == ["Conteudo"]


def test_lista_de_links_respeita_o_orcamento():
    links = [{"n": i, "texto": f"vaga {i}", "url": f"{BASE}/{i}"} for i in range(1, 50)]
    saida = em_linhas(links, orcamento=200)
    assert len(saida) < 260 and saida.endswith("links nesta página)")


def test_partes_vem_cheias_mesmo_com_linha_comprida():
    """Cortar antes da linha comprida deixava a parte 1 só com o título."""
    partes = em_partes("Titulo\n" + "palavra " * 2000, 3200)
    assert len(partes[0]) > 1600
    assert "".join(p.replace(" ", "") for p in partes).count("palavra") == 2000


def test_procurar_traz_o_trecho_com_a_vizinhanca():
    texto = "intro\ndump(obj)\nsort_keys ordena as chaves\nfim\noutra coisa"
    trecho = procurar(texto, "SORT_KEYS", 500)
    assert "dump(obj)" in trecho and "sort_keys ordena" in trecho and "outra coisa" not in trecho


async def test_ler_pagina_entrega_em_partes_e_le_a_pagina_uma_vez(monkeypatch):
    from sentury.tools import web

    leituras = []

    async def _inteira(url, timeout):
        leituras.append(url)
        texto = "\n".join(f"paragrafo {i} " + "texto " * 60 for i in range(40))
        return {"ok": True, "url": url, "titulo": "Doc", "texto": texto + "\nsort_keys ordena",
                "links": [{"n": 1, "texto": "Proxima", "url": url + "/2"}], "truncado": False}

    monkeypatch.setattr(web, "_ler_inteira", _inteira)
    monkeypatch.setattr(web, "_LIDAS", {})
    url = "https://docs.exemplo.com/json"

    primeira = await web.ler_pagina(url)
    assert primeira["parte"] == 1 and primeira["partes"] > 2
    assert len(primeira["texto"]) <= web.ORCAMENTO_TEXTO and "[1] Proxima" in primeira["links"]
    assert "parte=2" in primeira["continua"]

    segunda = await web.ler_pagina(url, parte=2)
    assert segunda["texto"] != primeira["texto"] and "links" not in segunda

    achado = await web.ler_pagina(url, procurar="sort_keys")
    assert "sort_keys ordena" in achado["texto"]
    assert leituras == [url]
