"""A lista numerada de links da página, sem navegador (degrau 1 da escada).

Só com o texto, os links se perdem: num catálogo de vagas o texto diz
"Engenheira Python · Remoto", mas o caminho para a vaga some, e o único jeito
de seguir seria abrir o navegador. Com a lista numerada (`[1] Engenheira
Python · Remoto`), o agente lê o catálogo em poucas centenas de tokens e segue
o link pela URL.

Só lê: não clica nem preenche. Para agir, o degrau é o `browser`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

MAX_LINKS = 60
MAX_TEXTO_DO_LINK = 90

_ESPACO = re.compile(r"\s+")
_A_REGEX = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
# Texto de link que nao diz nada sozinho: fica de fora da lista.
_VAZIOS = {"", "#", "aqui", "clique aqui", "saiba mais", "leia mais", "ver mais", "more", "here"}


def _candidatos(html: str) -> List[tuple]:
    try:
        from lxml import html as lxml_html

        arvore = lxml_html.fromstring(html)
        for ruido in arvore.xpath("//script|//style|//noscript"):
            ruido.getparent().remove(ruido)
        # Link para a mesma página em outro idioma (`hreflang`): a Wikipedia
        # abre com trezentos deles, e a lista acabava antes do conteúdo.
        return [(a.get("href") or "", a.text_content() or a.get("title") or a.get("aria-label") or "")
                for a in arvore.xpath("//a[@href]") if not a.get("hreflang")]
    except Exception:
        return [(href, _TAGS.sub(" ", texto)) for href, texto in _A_REGEX.findall(html or "")]


def links_numerados(html: str, base: str) -> List[Dict[str, Any]]:
    """`[{n, texto, url}]` em ordem de aparição, sem repetir URL nem link vazio."""
    vistos = set()
    saida: List[Dict[str, Any]] = []
    for href, texto in _candidatos(html):
        href = (href or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base, href).split("#", 1)[0]
        if urlparse(url).scheme not in ("http", "https") or url in vistos:
            continue
        rotulo = _ESPACO.sub(" ", texto or "").strip()
        if rotulo.lower() in _VAZIOS:
            continue
        vistos.add(url)
        saida.append({"n": len(saida) + 1, "texto": rotulo[:MAX_TEXTO_DO_LINK], "url": url})
        if len(saida) >= MAX_LINKS:
            break
    return saida


def em_linhas(links: List[Dict[str, Any]], orcamento: int = 0) -> str:
    """A forma compacta que vai para o modelo: `[3] Engenheira Python -> url`.

    Com `orcamento` (caracteres), para quando a lista estoura e diz quantos
    ficaram de fora, em vez de cortar no meio de uma URL."""
    linhas: List[str] = []
    usado = 0
    for i, l in enumerate(links):
        linha = f"[{l['n']}] {l['texto']} -> {l['url']}"
        if orcamento and usado + len(linha) > orcamento and linhas:
            linhas.append(f"(mais {len(links) - i} links nesta página)")
            break
        linhas.append(linha)
        usado += len(linha) + 1
    return "\n".join(linhas)


# Onde o conteúdo costuma morar. A ordem é de preferência: `main` e `article`
# são marcação de propósito; os ids cobrem wikis e documentação sem `main`.
_REGIOES = ("//main", "//article", "//*[@role='main']", "//*[@id='mw-content-text']",
            "//*[@id='content']", "//*[@id='main-content']")
_MINIMO_DA_REGIAO = 400


def regiao_principal(html: str) -> str:
    """O HTML só da região de conteúdo, quando a página marca uma.

    Menu, rodapé e barra lateral eram metade do texto devolvido (a lista de
    países da busca, o índice inteiro da documentação). Sem região marcada,
    ou com uma região quase vazia, devolve a página inteira."""
    try:
        from lxml import etree, html as lxml_html

        arvore = lxml_html.fromstring(html)
        corpo = len(" ".join(arvore.text_content().split()))
        for caminho in _REGIOES:
            for elemento in arvore.xpath(caminho):
                tamanho = len(" ".join(elemento.text_content().split()))
                if tamanho >= _MINIMO_DA_REGIAO and tamanho >= corpo * 0.2:
                    return etree.tostring(elemento, encoding="unicode", method="html")
    except Exception:
        pass
    return html


def em_partes(texto: str, orcamento: int) -> List[str]:
    """Fatias de até `orcamento` caracteres, cortadas em fim de linha.

    Cada fatia vai cheia: cortar antes de uma linha comprida deixava a primeira
    parte só com o título, e o agente gastava uma chamada para nada."""
    texto = texto or ""
    partes: List[str] = []
    inicio = 0
    while inicio < len(texto):
        fim = inicio + orcamento
        if fim < len(texto):
            # Prefere fim de linha, depois espaço, sem deixar a fatia a menos da metade.
            corte = texto.rfind("\n", inicio + orcamento // 2, fim)
            if corte < 0:
                corte = texto.rfind(" ", inicio + orcamento // 2, fim)
            fim = corte + 1 if corte >= 0 else fim
        partes.append(texto[inicio:fim].strip())
        inicio = fim
    return [p for p in partes if p] or [""]


def _nu(texto: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii").lower()


def procurar(texto: str, termo: str, orcamento: int) -> str:
    """As linhas que citam o termo, com a vizinha de cada lado, até o orçamento."""
    alvo = _nu(termo).strip()
    linhas = (texto or "").splitlines()
    if not alvo:
        return ""
    trechos: List[str] = []
    usado = 0
    ultimo = -2
    for i, linha in enumerate(linhas):
        if alvo not in _nu(linha):
            continue
        inicio = max(i - 1, ultimo + 1)
        bloco = "\n".join(linhas[inicio:i + 2])
        if usado + len(bloco) > orcamento and trechos:
            break
        trechos.append(bloco if inicio == ultimo + 1 else "…\n" + bloco)
        usado += len(bloco)
        ultimo = i + 1
    return "\n".join(trechos)


__all__ = ["em_linhas", "em_partes", "links_numerados", "procurar", "regiao_principal"]
