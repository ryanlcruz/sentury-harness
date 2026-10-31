"""O navegador que o Sentury abre sozinho: a aba do provedor Playwright, a
verificação de renderização e os testes.

Prefere o navegador instalado, que é assinado: o Windows com Controle
Inteligente de Aplicativos barra o Chromium que o Playwright baixa. Tenta o
Google Chrome, depois o Microsoft Edge; sem nenhum dos dois (um servidor Linux,
por exemplo), abre o Chromium do Playwright. `SENTURY_NAVEGADOR_CANAL` fixa a
escolha (`chrome`, `msedge` ou `chromium`). O perfil é sempre temporário, nunca
o da pessoa.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, List

_CHROME_AUSENTE = ("is not found", "executable doesn't exist", "distribution 'chrome'",
                   "distribution 'msedge'")

_INSTALADOS = ("chrome", "msedge")


def _caminhos(canal: str) -> List[Path]:
    """Onde o Playwright procura cada canal: os locais padrão de instalação."""
    if sys.platform == "win32":
        pasta = {"chrome": Path("Google", "Chrome", "Application", "chrome.exe"),
                 "msedge": Path("Microsoft", "Edge", "Application", "msedge.exe")}[canal]
        raizes = [os.environ.get(v) for v in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)")]
        return [Path(r) / pasta for r in raizes if r]
    if sys.platform == "darwin":
        app = {"chrome": "Google Chrome", "msedge": "Microsoft Edge"}[canal]
        return [Path("/Applications", f"{app}.app", "Contents", "MacOS", app)]
    return [Path({"chrome": "/opt/google/chrome/chrome", "msedge": "/opt/microsoft/msedge/msedge"}[canal])]


def instalado(canal: str) -> bool:
    return canal in _INSTALADOS and any(c.is_file() for c in _caminhos(canal))


def navegador_instalado() -> str:
    """O canal do primeiro navegador instalado (`chrome` ou `msedge`), ou vazio.
    Com ele na máquina, o Chromium do Playwright não precisa ser baixado."""
    return next((c for c in _INSTALADOS if instalado(c)), "")


def _canais() -> List[str]:
    escolhido = (os.environ.get("SENTURY_NAVEGADOR_CANAL") or "").strip().lower()
    if escolhido:
        return [] if escolhido == "chromium" else [escolhido]
    return list(_INSTALADOS)


def precisa_do_chromium() -> bool:
    """Nenhum canal tentado está instalado: só o Chromium do Playwright abre."""
    return not any(instalado(c) for c in _canais())


def _ausente(exc: Exception) -> bool:
    texto = str(exc).lower()
    return any(marca in texto for marca in _CHROME_AUSENTE)


def abrir(playwright: Any, **opcoes: Any) -> Any:
    for canal in _canais():
        try:
            return playwright.chromium.launch(channel=canal, **opcoes)
        except Exception as exc:
            if not _ausente(exc):
                raise
    return playwright.chromium.launch(**opcoes)


async def abrir_async(playwright: Any, **opcoes: Any) -> Any:
    for canal in _canais():
        try:
            return await playwright.chromium.launch(channel=canal, **opcoes)
        except Exception as exc:
            if not _ausente(exc):
                raise
    return await playwright.chromium.launch(**opcoes)


__all__ = ["abrir", "abrir_async", "instalado", "navegador_instalado", "precisa_do_chromium"]
