"""Lê o estado da máquina sem receber ou executar comandos da pessoa."""
from __future__ import annotations

import ipaddress
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
from pathlib import Path


_INDISPONIVEL = "indisponível aqui"
_TETO = 500
_PROC = Path("/proc")


def _windows(alvo):
    consultas = {
        "processos": "Get-Process | Select-Object -First 500 ProcessName,Id,CPU,WorkingSet64,Responding,MainWindowTitle",
        "janelas": "Get-Process | Where-Object MainWindowTitle | Select-Object -First 500 ProcessName,Id,Responding,MainWindowTitle",
        "portas": "Get-NetTCPConnection -State Listen | Select-Object -First 500 LocalAddress,LocalPort,OwningProcess",
    }
    programa = shutil.which("powershell.exe")
    if not programa:
        return _INDISPONIVEL
    script = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
              "$ErrorActionPreference = 'Stop'; @(" + consultas[alvo] + ") | ConvertTo-Json -Compress")
    processo = subprocess.run([programa, "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, encoding="utf-8", timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if processo.returncode:
        return _INDISPONIVEL
    dados = json.loads(processo.stdout.strip() or "[]")
    dados = dados if isinstance(dados, list) else [dados]
    if alvo == "portas":
        return [{"endereco": p.get("LocalAddress"), "porta": p.get("LocalPort"),
                 "pid": p.get("OwningProcess"), "protocolo": "tcp"} for p in dados]
    return [{"nome": p.get("ProcessName"), "pid": p.get("Id"),
             "cpu_segundos": p.get("CPU"), "memoria_bytes": p.get("WorkingSet64", _INDISPONIVEL),
             "respondendo": p.get("Responding", _INDISPONIVEL),
             "titulo_janela": p.get("MainWindowTitle") or ""} for p in dados]


def _processos_linux():
    dados = []
    ticks = os.sysconf("SC_CLK_TCK")
    pagina = os.sysconf("SC_PAGE_SIZE")
    for pasta in sorted(_PROC.iterdir(), key=lambda p: p.name):
        if not pasta.name.isdigit():
            continue
        try:
            linha = (pasta / "stat").read_text(encoding="utf-8")
            inicio, fim = linha.index("("), linha.rindex(")")
            campos = linha[fim + 2:].split()
            dados.append({"nome": linha[inicio + 1:fim], "pid": int(pasta.name),
                          "cpu_segundos": (int(campos[11]) + int(campos[12])) / ticks,
                          "memoria_bytes": int(campos[21]) * pagina,
                          "respondendo": _INDISPONIVEL, "titulo_janela": _INDISPONIVEL})
        except (OSError, ValueError, IndexError):
            continue
        if len(dados) >= _TETO:
            break
    return dados


def _portas_linux():
    dados = []
    lidos = 0
    for nome, ipv6 in (("tcp", False), ("tcp6", True)):
        try:
            linhas = (_PROC / "net" / nome).read_text(encoding="ascii").splitlines()[1:]
            lidos += 1
        except OSError:
            continue
        for linha in linhas:
            campos = linha.split()
            if len(campos) < 4 or campos[3] != "0A":
                continue
            endereco, porta = campos[1].split(":")
            if ipv6:
                bruto = b"".join(struct.pack("=I", int(endereco[i:i + 8], 16)) for i in range(0, 32, 8))
                ip = str(ipaddress.IPv6Address(bruto))
            else:
                ip = socket.inet_ntoa(struct.pack("=I", int(endereco, 16)))
            dados.append({"endereco": ip, "porta": int(porta, 16), "protocolo": "tcp"})
    return dados[:_TETO] if lidos else _INDISPONIVEL


def _sistema():
    container = Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()
    try:
        cgroup = (_PROC / "1" / "cgroup").read_text(encoding="utf-8")
        container |= any(marca in cgroup for marca in ("docker", "kubepods", "containerd"))
    except OSError:
        pass
    produto = ""
    try:
        produto = Path("/sys/class/dmi/id/product_name").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    nuvem = any(marca in produto.casefold() for marca in ("amazon", "google compute", "openstack", "oraclecloud"))
    systemd = bool(os.environ.get("INVOCATION_ID"))
    desktop = platform.system() == "Windows" or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    onde = ("container" if container else "VM de nuvem" if nuvem else "serviço systemd" if systemd
            else "computador pessoal" if desktop else _INDISPONIVEL)
    return {"so": platform.system(), "versao": platform.release(), "arquitetura": platform.machine(),
            "onde_roda": onde, "container": container, "vm_de_nuvem": nuvem,
            "servico_systemd": systemd,
            "nota": "onde_roda usa sinais locais; sem evidência suficiente, a localização fica indisponível"}


def inspecionar(alvo="sistema", **extras):
    from .registry import TOOL_REGISTRY

    permitidos = TOOL_REGISTRY["inspecionar_ambiente"]["parametros"]["properties"]["alvo"]["enum"]
    if extras or alvo not in permitidos:
        return {"ok": False, "erro": "a inspeção aceita apenas um alvo do esquema, sem comando livre"}
    try:
        if alvo == "sistema":
            dados = _sistema()
        elif alvo == "disco":
            uso = shutil.disk_usage(Path.cwd().anchor or "/")
            dados = {"total_bytes": uso.total, "usado_bytes": uso.used, "livre_bytes": uso.free}
        elif platform.system() == "Windows":
            dados = _windows(alvo)
        elif platform.system() == "Linux" and alvo == "processos":
            dados = _processos_linux()
        elif platform.system() == "Linux" and alvo == "portas":
            dados = _portas_linux()
        else:
            dados = _INDISPONIVEL
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        dados = _INDISPONIVEL
    return {"ok": True, "alvo": alvo, "dados": dados,
            "limite": _TETO, "cpu_unidade": "segundos acumulados"}
