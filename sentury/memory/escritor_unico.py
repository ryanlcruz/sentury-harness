"""Um escritor por pasta de dados.

Dois processos no mesmo `~/.sentury` intercalam `seq` no journal e o store
recusa abrir na próxima vez: corrupção que só aparece depois. O lock troca
isso por uma recusa imediata, com o PID de quem já está lá.

Lock por arquivo, não por porta: o que precisa ser único é o escritor da pasta.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ARQUIVO = "escritor.lock"
_HOST = platform.node() or ""


class OutroEscritorAtivo(RuntimeError):
    """Já existe um Sentury escrevendo nesta pasta."""


def _vivo(pid: int) -> bool:
    """Se o processo ainda existe. Erra para 'vivo' quando não dá para saber:
    apagar o lock de um processo ativo é o dano que se quer evitar."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # Pergunta ao proprio Windows. `tasklist` depende de um processo
        # externo que nem sempre devolve saida, e ai nao da para decidir nada.
        import ctypes

        SINCRONIZAR = 0x00100000
        CONSULTAR = 0x00001000
        ATIVO = 259
        try:
            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.GetExitCodeProcess.restype = ctypes.c_int
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.restype = ctypes.c_int
            alca = kernel.OpenProcess(SINCRONIZAR | CONSULTAR, False, pid)
            if not alca:
                # 5 = acesso negado, ou seja: existe e nao e nosso.
                return kernel.GetLastError() == 5
            try:
                codigo = ctypes.c_ulong()
                if kernel.GetExitCodeProcess(alca, ctypes.byref(codigo)):
                    return codigo.value == ATIVO
                return True
            finally:
                kernel.CloseHandle(alca)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    return True


def _inicio_do_processo(pid: int) -> Optional[float]:
    """Horário de criação no Windows; permite distinguir um PID reutilizado.

    Se o sistema negar acesso, não presumimos que o lock é obsoleto.
    """
    if os.name != "nt":
        return None
    import ctypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p, ctypes.POINTER(FILETIME),
                                       ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                                       ctypes.POINTER(FILETIME)]
    kernel.GetProcessTimes.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    alca = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not alca:
        return None
    try:
        criado = FILETIME()
        saida = FILETIME()
        kernel_tempo = FILETIME()
        usuario_tempo = FILETIME()
        if not kernel.GetProcessTimes(alca, ctypes.byref(criado), ctypes.byref(saida),
                                      ctypes.byref(kernel_tempo), ctypes.byref(usuario_tempo)):
            return None
        ticks = (criado.high << 32) | criado.low
        return ticks / 10_000_000 - 11_644_473_600
    finally:
        kernel.CloseHandle(alca)


def _ler(caminho: Path) -> Optional[dict]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return None
    return dados if isinstance(dados, dict) else None


class Lock:
    """Segura a pasta enquanto o processo vive. `liberar()` é idempotente."""

    def __init__(self, pasta: Path):
        self.caminho = Path(pasta) / ARQUIVO
        self._meu = False

    def adquirir(self) -> "Lock":
        dono = _ler(self.caminho)
        if dono and str(dono.get("host") or _HOST) != _HOST:
            logger.info(
                "Lock gravado em outra maquina (%s); o PID nao vale aqui.",
                dono.get("host"),
            )
            dono = None
        if dono:
            pid = int(dono.get("pid") or 0)
            desde = float(dono.get("desde") or 0)
            inicio = _inicio_do_processo(pid) if pid != os.getpid() and desde else None
            pid_reutilizado = inicio is not None and inicio > desde + 1
            if pid != os.getpid() and _vivo(pid) and not pid_reutilizado:
                raise OutroEscritorAtivo(
                    f"outro Sentury (PID {pid}) ja escreve em {self.caminho.parent}. "
                    "Encerre-o, ou use SENTURY_HOME para apontar outra pasta."
                )
            if pid_reutilizado:
                logger.info("Lock com PID reutilizado (%s): o processo atual começou após o lock.", pid)
            elif pid != os.getpid():
                logger.info("Lock de um processo que ja morreu (PID %s); assumindo.", pid)

        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho.write_text(
            json.dumps({"pid": os.getpid(), "desde": time.time(), "host": _HOST}),
            encoding="utf-8")
        self._meu = True
        return self

    def liberar(self) -> None:
        if not self._meu:
            return
        dono = _ler(self.caminho)
        if dono and int(dono.get("pid") or 0) == os.getpid():
            try:
                self.caminho.unlink()
            except OSError:
                pass
        self._meu = False

    def __enter__(self) -> "Lock":
        return self.adquirir()

    def __exit__(self, *_) -> None:
        self.liberar()


__all__ = ["ARQUIVO", "Lock", "OutroEscritorAtivo"]
