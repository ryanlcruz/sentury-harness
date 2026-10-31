"""O Chrome em que o agente navega pela tela, escolhido pela pessoa.

`pessoa` (o padrão) é o Chrome dela, com as contas dela: é o que serve para
trabalhar nas coisas dela, como ver o CI no GitHub. `agente` é um perfil
separado, com pasta de dados própria: sem as extensões, os cookies e as contas
dela, e com a reputação dele nos sites. O nome é dela também: vira "Chrome do
<nome>" no menu Iniciar e o título da janela, para `focar` achar a certa.

`python -m sentury.tools.perfil_do_agente [nome]` cria o atalho uma vez.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

PADRAO = "Agente"


def _escolha() -> dict:
    """A escolha da tela (`ajustes.json`); o `.env` só vale quando ela não existe."""
    try:
        from .. import ajustes

        return ajustes.ler("navegador")
    except Exception:
        return {}


def nome_do_perfil() -> str:
    escolhido = str(_escolha().get("nome") or "").strip()
    if escolhido:
        return escolhido
    try:
        from ..config import settings

        return str(getattr(settings, "SENTURY_NAVEGADOR_AGENTE_NOME", PADRAO) or PADRAO).strip() or PADRAO
    except Exception:
        return PADRAO


def perfil_escolhido() -> str:
    """'pessoa' ou 'agente'."""
    perfil = str(_escolha().get("perfil") or "").strip().lower()
    if not perfil:
        try:
            from ..config import settings

            perfil = str(getattr(settings, "SENTURY_NAVEGADOR_PERFIL", "pessoa") or "pessoa").strip().lower()
        except Exception:
            perfil = "pessoa"
    return "agente" if perfil == "agente" else "pessoa"


def navegador_escolhido() -> str:
    """O que o agente lê no começo do turno: em qual Chrome navegar."""
    if perfil_escolhido() == "agente":
        nome = nome_do_perfil()
        return (f'a pessoa escolheu o "Chrome do {nome}" para você navegar: `abrir` com esse nome, e a janela '
                f'tem "{nome}" no título. É um perfil separado, sem as contas dela')
    return "a pessoa escolheu o Chrome dela para você navegar, com as contas e as sessões dela"


def pasta_do_perfil(nome: str = PADRAO) -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    pasta = "".join(c if c.isalnum() else "-" for c in nome.lower()).strip("-") or "agente"
    return Path(base) / "Sentury" / f"chrome-{pasta}"


def _chrome() -> Optional[str]:
    """O chrome.exe pelo registro do Windows (App Paths), ou None."""
    try:
        import winreg
    except ImportError:
        return None
    for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(raiz, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as chave:
                caminho = winreg.QueryValue(chave, None)
                if caminho and Path(caminho).exists():
                    return caminho
        except OSError:
            continue
    return None


def argumentos(nome: str = PADRAO) -> str:
    return (f'--user-data-dir="{pasta_do_perfil(nome)}" --window-name="{nome}" '
            "--no-first-run --no-default-browser-check")


def criar_atalho(nome: str = PADRAO) -> Path:
    """Cria (ou refaz) o atalho no menu Iniciar da pessoa e devolve o caminho."""
    chrome = _chrome()
    if chrome is None:
        raise RuntimeError("não achei o Google Chrome instalado")
    pasta_do_perfil(nome).mkdir(parents=True, exist_ok=True)
    atalho = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
              / f"Chrome do {nome}.lnk")
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TATO_ATALHO); "
        "$s.TargetPath = $env:TATO_ALVO; $s.Arguments = $env:TATO_ARGS; "
        "$s.IconLocation = $env:TATO_ALVO + ',0'; $s.Description = 'Chrome separado para o agente'; $s.Save()"
    )
    ambiente = {**os.environ, "TATO_ATALHO": str(atalho), "TATO_ALVO": chrome, "TATO_ARGS": argumentos(nome)}
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=ambiente,
                   check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return atalho


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("o atalho do menu Iniciar é do Windows")
    nome = " ".join(sys.argv[1:]).strip() or nome_do_perfil()
    print(f"atalho criado: {criar_atalho(nome)}")
    print(f"perfil em: {pasta_do_perfil(nome)}")
