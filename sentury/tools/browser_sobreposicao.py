"""O agente visível na página que ele controla.

Com a janela do navegador aberta na frente da pessoa, cada ação vem
anunciada: a borda em degradê diz "estou mexendo aqui", a seta própria
(redonda, do ciano ao magenta) anda até o alvo, e o balão diz o que vai
acontecer. Tudo desenhado DENTRO da página por `browser_sobreposicao.js`: o
Playwright não move o mouse do sistema.

Sem tela (servidor, container, `SENTURY_BROWSER_VISIVEL=nao`) nada disso é
injetado: ninguém veria, e cada ação pagaria a espera da seta.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SCRIPT = (Path(__file__).parents[1] / "browser_extension" / "browser_sobreposicao.js").read_text(encoding="utf-8")
_SIM = {"1", "sim", "true", "yes", "on"}
_NAO = {"0", "nao", "não", "false", "no", "off"}


def _config(nome: str, padrao: Any) -> Any:
    """Ambiente primeiro (o teste e quem roda na mao), depois o `.env` lido
    pelo `settings`: o `.env` nao vira variavel de ambiente."""
    if nome in os.environ:
        return os.environ[nome]
    try:
        from ..config import settings

        return getattr(settings, nome, padrao)
    except Exception:
        return padrao


def navegador_visivel(valor: Optional[str] = None) -> bool:
    """`SENTURY_BROWSER_VISIVEL`: sim, nao ou auto (o padrão).

    No auto a janela abre quando existe tela: Windows e macOS sempre, Linux
    quando há DISPLAY ou WAYLAND_DISPLAY. Num servidor sem tela, abrir janela
    falharia na hora de lançar o Chromium.
    """
    bruto = str(valor if valor is not None else _config("SENTURY_BROWSER_VISIVEL", "auto"))
    bruto = bruto.strip().lower()
    if bruto in _SIM:
        return True
    if bruto in _NAO:
        return False
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def espera_da_seta_ms() -> int:
    """O tempo para a seta chegar antes da ação: sem ele o clique acontece
    antes de a pessoa ver para onde ela foi."""
    try:
        return max(0, int(_config("SENTURY_BROWSER_SETA_MS", 450)))
    except (TypeError, ValueError):
        return 450


def _curto(texto: Any, limite: int = 48) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def rotulo(tipo: str, argumentos: Mapping[str, Any], nome_do_alvo: str = "") -> str:
    """O texto do balão. Em `digitar` vai o CAMPO, nunca o que é digitado:
    senha e chave ficariam na tela de quem estiver olhando."""
    if tipo == "navegar":
        host = urlparse(str(argumentos.get("url") or "")).netloc
        return f"navegar · {host}" if host else "navegar"
    if tipo == "clicar":
        return f"clicar · “{_curto(nome_do_alvo)}”" if nome_do_alvo else "clicar"
    if tipo == "digitar":
        return f"digitar em “{_curto(nome_do_alvo)}”" if nome_do_alvo else "digitar"
    if tipo == "rolar":
        return "rolar"
    return tipo


async def apontar(page, x: float, y: float, texto: str, *, clique: bool = False, esperar: bool = True,
                  caixa: Optional[Mapping[str, float]] = None) -> None:
    """Leva a seta até (x, y). Falha aqui nunca derruba a ação: a seta é
    aviso, não parte do trabalho. `caixa` contorna o campo que vai receber
    texto; sem ela, o contorno anterior some."""
    from .computador_moldura import agente

    try:
        await page.evaluate(
            "([x, y, t, c, k, a]) => window.__tato && (window.__tato.usar(a), window.__tato.apontar(x, y, t, c, k))",
            [x, y, texto, clique, dict(caixa) if caixa else None, agente()],
        )
        if esperar and espera_da_seta_ms():
            await page.wait_for_timeout(espera_da_seta_ms())
    except Exception as exc:  # pagina navegando, fechada, frame trocado
        logger.debug("Seta nao apareceu: %s", exc)


async def apontar_para(page, locator, texto: str, *, clique: bool = False, contornar: bool = False) -> None:
    try:
        caixa = await locator.bounding_box()
    except Exception:
        caixa = None
    if caixa:
        x, y = caixa["x"] + caixa["width"] / 2, caixa["y"] + caixa["height"] / 2
    else:
        x, y = await _meio_da_tela(page)
    await apontar(page, x, y, texto, clique=clique, caixa=caixa if contornar else None)


async def apontar_no_topo(page, texto: str, *, esperar: bool = True) -> None:
    x, _ = await _meio_da_tela(page)
    await apontar(page, x, 48, texto, esperar=esperar)


async def _meio_da_tela(page) -> tuple:
    tamanho = page.viewport_size or {"width": 1280, "height": 720}
    return tamanho["width"] / 2, tamanho["height"] / 2


_TAG = re.compile(r"<tato-sobreposicao\b[^>]*>.*?</tato-sobreposicao>", re.S)


def sem_sobreposicao(html: str) -> str:
    """O HTML que o modelo le, sem a camada da sobreposicao. A sombra fechada ja
    nao sai no `page.content()`, mas a tag vazia saia: ruido que o modelo
    poderia tomar como parte do site."""
    return _TAG.sub("", html)


async def esconder(page) -> None:
    try:
        await page.evaluate("() => window.__tato && window.__tato.esconder()")
    except Exception:
        pass


async def mostrar(page) -> None:
    try:
        await page.evaluate("() => window.__tato && window.__tato.mostrar()")
    except Exception:
        pass


__all__ = ["SCRIPT", "apontar", "apontar_no_topo", "apontar_para", "esconder", "sem_sobreposicao",
           "espera_da_seta_ms", "mostrar", "navegador_visivel", "rotulo"]
