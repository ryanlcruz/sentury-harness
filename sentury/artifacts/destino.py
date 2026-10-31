"""Onde fica o arquivo que o Sentury entrega: gráfico, planilha, PDF, HTML.

É entrega para a pessoa, não parte do projeto dela nem estado interno do
Sentury, então vai para a pasta de documentos do sistema, em `Sentury/`. Quem
quer outro lugar define `SENTURY_ARTEFATOS_DIR`. O trabalho intermediário
continua no rascunho da conversa (`tools/arquivos.py`).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

SUBPASTA = "Sentury"


def _documentos_do_windows() -> Optional[Path]:
    """A pasta que o Windows informa, que pode estar redirecionada ao OneDrive."""
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        id_ = uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")  # FOLDERID_Documents
        guid = _GUID(id_.fields[0], id_.fields[1], id_.fields[2], (ctypes.c_ubyte * 8)(*id_.bytes[8:]))
        caminho = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(caminho)) != 0:
            return None
        try:
            return Path(caminho.value) if caminho.value else None
        finally:
            ctypes.windll.ole32.CoTaskMemFree(caminho)
    except Exception:
        return None


def _documentos_do_xdg(casa: Path) -> Optional[Path]:
    """`XDG_DOCUMENTS_DIR`, da variável ou de `user-dirs.dirs`: é onde o nome
    traduzido (Documentos, Dokumente) está declarado."""
    valor = os.environ.get("XDG_DOCUMENTS_DIR", "")
    if not valor:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or casa / ".config") / "user-dirs.dirs"
        try:
            achado = re.search(r'^XDG_DOCUMENTS_DIR="([^"]+)"', config.read_text(encoding="utf-8"), re.M)
            valor = achado.group(1) if achado else ""
        except OSError:
            valor = ""
    if not valor:
        return None
    caminho = Path(valor.replace("$HOME", str(casa)))
    # Sem pasta própria de documentos o XDG aponta para o home: isso não é Documentos.
    return caminho if caminho.resolve() != casa.resolve() else None


def pasta_de_documentos() -> Optional[Path]:
    casa = Path.home()
    if sys.platform == "win32":
        return _documentos_do_windows() or (casa / "Documents")
    if sys.platform != "darwin":
        declarada = _documentos_do_xdg(casa)
        if declarada:
            return declarada
    for nome in ("Documents", "Documentos"):
        if (casa / nome).is_dir():
            return casa / nome
    return None


def pasta_de_entregas() -> Path:
    """`SENTURY_ARTEFATOS_DIR`, ou Documentos/Sentury; num servidor sem pasta de
    documentos, `~/Sentury`."""
    escolhida = os.environ.get("SENTURY_ARTEFATOS_DIR", "").strip()
    if escolhida:
        alvo = Path(escolhida).expanduser()
    else:
        documentos = pasta_de_documentos()
        alvo = (documentos / SUBPASTA) if documentos else (Path.home() / SUBPASTA)
    alvo.mkdir(parents=True, exist_ok=True)
    return alvo.resolve()


def caminho_livre(nome: str, pasta: Optional[Path] = None) -> Path:
    """Um caminho na pasta de entregas que não sobrescreve arquivo da pessoa."""
    pasta = pasta or pasta_de_entregas()
    limpo = Path(str(nome or "resultado")).name or "resultado"
    alvo = pasta / limpo
    base, ext = alvo.stem, alvo.suffix
    n = 2
    while alvo.exists():
        alvo = pasta / f"{base}-{n}{ext}"
        n += 1
    return alvo
