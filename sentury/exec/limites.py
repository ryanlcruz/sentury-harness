"""Encerrar de verdade um processo que passou do tempo.

`subprocess.run(timeout=...)` mata o filho direto e deixa os netos vivos. Um
script que chama outro programa deixa esse programa rodando para sempre, e o
timeout vira ficcao. Aqui a arvore inteira cai.
"""
from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


class LimiteDeProcesso:
    """Recurso nativo que acompanha o processo (Job Object no Windows)."""

    def __init__(self, handle: Any = None):
        self.handle = handle

    def fechar(self) -> None:
        if not self.handle:
            return
        try:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self.handle)
        except Exception:
            pass
        self.handle = None


def aplicar_limites(processo: Any, memoria_mb: int = 0) -> LimiteDeProcesso | None:
    """Prende o filho num Job Object que morre com o pai e limita memoria.

    No POSIX o trabalhador aplica ``RLIMIT_AS`` em si mesmo; aqui fica somente
    o ramo Windows, onde o limite precisa ser imposto pelo processo pai.
    """
    if os.name != "nt" or processo is None:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        ULONG_PTR = ctypes.c_size_t
        SIZE_T = ctypes.c_size_t

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", SIZE_T),
                ("MaximumWorkingSetSize", SIZE_T),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ULONG_PTR),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", SIZE_T),
                ("JobMemoryLimit", SIZE_T),
                ("PeakProcessMemoryUsed", SIZE_T),
                ("PeakJobMemoryUsed", SIZE_T),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.BasicLimitInformation.LimitFlags = 0x00002000
        if int(memoria_mb or 0) > 0:
            info.BasicLimitInformation.LimitFlags |= 0x00000100
            info.ProcessMemoryLimit = int(memoria_mb) * 1024 * 1024
        ok = kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok or not kernel32.AssignProcessToJobObject(handle, wintypes.HANDLE(processo._handle)):
            kernel32.CloseHandle(handle)
            return None
        return LimiteDeProcesso(handle)
    except Exception:
        return None


def matar_arvore(processo: Any, limite: LimiteDeProcesso | None = None) -> None:
    """Derruba o processo e seus descendentes, sem levantar se ja morreu."""
    if processo is None or processo.poll() is not None:
        if limite:
            limite.fechar()
        return
    if os.name == "nt":
        # Fechar um Job com KILL_ON_JOB_CLOSE derruba toda a arvore de forma
        # atomica. `taskkill` fica como fallback para hosts que recusam Jobs.
        if limite and limite.handle:
            limite.fechar()
            try:
                processo.wait(timeout=3)
                return
            except subprocess.TimeoutExpired:
                pass
        # `taskkill /T` desce a arvore pelo registro do proprio Windows. Matar
        # so o pai deixa o neto orfao segurando o pipe de saida.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(processo.pid), "/T", "/F"],
                capture_output=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        # `start_new_session` deu ao filho um grupo proprio; o sinal vai ao grupo.
        for sinal in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(processo.pid), sinal)
            except (ProcessLookupError, PermissionError, OSError):
                break
            try:
                processo.wait(timeout=3)
                return
            except subprocess.TimeoutExpired:
                continue
    try:
        processo.kill()
    except OSError:
        pass
    if limite:
        limite.fechar()
