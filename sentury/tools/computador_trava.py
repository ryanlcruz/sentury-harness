"""Um computador, um agente: a trava entre processos.

Cada cliente MCP sobe o próprio servidor, e dois deles com a moldura aberta
disputariam o mesmo mouse e o mesmo teclado. Quem abre a moldura pega a trava
de um arquivo; o sistema a solta sozinho se o processo morrer.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import IO, Optional

_trava = threading.Lock()
_arquivo: Optional[IO] = None


def _caminho() -> Path:
    return Path(os.environ.get("SENTURY_HOME") or Path.home() / ".sentury") / "computador.trava"


def pegar() -> Optional[str]:
    """None quando este processo ficou com o computador; senão, o motivo."""
    global _arquivo
    with _trava:
        if _arquivo is not None:
            return None
        caminho = _caminho()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = open(caminho, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                arquivo.seek(0)
                msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            arquivo.close()
            return ("outro agente está usando o computador agora (outro cliente MCP ou outra janela do "
                    "Sentury); um mouse, um agente por vez. Espere ele encerrar ou peça à pessoa")
        _arquivo = arquivo
        return None


def soltar() -> None:
    global _arquivo
    with _trava:
        if _arquivo is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                _arquivo.seek(0)
                msvcrt.locking(_arquivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(_arquivo, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            _arquivo.close()
            _arquivo = None


__all__ = ["pegar", "soltar"]
