"""O ambiente que o processo filho recebe: e o que ele nao recebe.

O filho herda o ambiente do servidor por padrao, e o ambiente do servidor tem as
chaves de API do `.env`. Um `env` impresso dentro de um comando vaza tudo para o
historico da conversa. Aqui o ambiente e montado de fora para dentro: parte do
que e essencial, nunca do que existe.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Dict, Iterable, List, Optional

# Nome que contem qualquer um destes nao atravessa. `PASS` fica de fora de
# proposito: pegaria `BYPASS_CACHE` e `COMPASS_DIR` sem motivo.
_MARCAS_DE_SEGREDO = (
    "KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "CREDS",
    "AUTH", "DSN", "WEBHOOK", "BEARER", "APIKEY",
)

# Prefixos que qualquer processo precisa para funcionar.
_PREFIXOS_SEGUROS = (
    "PATH", "HOME", "LANG", "LC_", "TERM", "TMP", "TEMP", "TZ",
    "XDG_", "PYTHONPATH", "VIRTUAL_ENV", "CONDA",
)

# No Windows nao basta o PATH: sem `SystemRoot` o processo nao acha as DLLs de
# socket e morre com WinError 10106; sem `COMSPEC`/`PATHEXT` nada resolve.
_ESSENCIAIS_WINDOWS = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
    "OS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROGRAMDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "USERNAME", "HOMEDRIVE", "HOMEPATH",
    "COMPUTERNAME", "PUBLIC", "ALLUSERSPROFILE", "SESSIONNAME",
)


def _e_segredo(nome: str) -> bool:
    alto = nome.upper()
    return any(marca in alto for marca in _MARCAS_DE_SEGREDO)


def preparar_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Ambiente limpo para o filho, na ordem: base, essenciais, extra.

    O `extra` entra por ultimo e pode sobrescrever: quem chama e codigo nosso,
    nao o modelo, e as vezes precisa passar um nome que parece credencial.
    """
    base: Dict[str, str] = {}
    for nome, valor in os.environ.items():
        alto = nome.upper()
        if _e_segredo(nome):
            continue
        if alto.startswith(_PREFIXOS_SEGUROS) or (os.name == "nt" and alto in _ESSENCIAIS_WINDOWS):
            base[nome] = valor

    if os.name == "nt":
        for nome in _ESSENCIAIS_WINDOWS:
            valor = os.environ.get(nome)
            if valor and nome not in base and not _e_segredo(nome):
                base[nome] = valor

    # Acento no caminho e saida com acento nao sobrevivem a codificacao ANSI do
    # console. Isto vale para qualquer maquina, nao so para a nossa.
    base.update({
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    if extra:
        base.update({str(k): str(v) for k, v in extra.items()})
    return base


def bandeiras_de_processo() -> Dict[str, object]:
    """Como criar o filho: sem janela no Windows, em sessao propria no POSIX.

    Sem `CREATE_NO_WINDOW` pisca um console a cada comando. `start_new_session`
    da um grupo proprio, que e o que permite matar a arvore inteira depois.
    """
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


def interpretadores(nomes: Iterable[str] = ()) -> List[str]:
    """Quais interpretadores existem NESTA maquina.

    O modelo supunha o que tinha: mandava `powershell` no Linux e `bash` onde so
    existe `cmd`. Descobrir e barato e evita um turno inteiro de tentativa.
    """
    candidatos = tuple(nomes) or (
        "powershell", "pwsh", "bash", "sh", "python", "python3", "node",
    )
    return [nome for nome in candidatos if shutil.which(nome)]
