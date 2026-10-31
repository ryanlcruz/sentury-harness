"""Checar pacote antes de rodá-lo, contra a base pública OSV.

Um servidor MCP declarado como `npx -y algum-pacote` baixa e executa código de
terceiro na máquina. A declaração vem do usuário, mas o conteúdo do pacote não.

Malware e vulnerabilidade recebem tratamento diferente de propósito:

- **Malware bloqueia.** Um pacote publicado para roubar credencial não tem
  versão segura nem uso legítimo.
- **CVE avisa.** Vulnerabilidade conhecida é comum em dependência viva;
  bloquear tudo tornaria a checagem inútil e ela seria desligada no primeiro
  falso impedimento.

Falha de rede **libera**, com aviso no log: uma checagem que derruba o agente
quando a internet cai protege menos do que atrapalha.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ENDPOINT = os.environ.get("OSV_ENDPOINT", "https://api.osv.dev/v1/query")
TIMEOUT = 10.0

# Comando → ecossistema no vocabulário do OSV.
_ECOSSISTEMA = {
    "npx": "npm", "npm": "npm", "pnpm": "npm", "yarn": "npm", "bunx": "npm",
    "uvx": "PyPI", "pipx": "PyPI", "pip": "PyPI", "uv": "PyPI",
}

_FLAG = re.compile(r"^-")


# No Windows o npx é `npx.cmd`: sem tirar a extensão, a checagem não rodaria
# justamente onde o comando tem outro nome.
_EXTENSOES = (".exe", ".cmd", ".bat", ".ps1")


def ecossistema_de(comando: str) -> str:
    nome = str(comando or "").strip().lower()
    nome = nome.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    for extensao in _EXTENSOES:
        if nome.endswith(extensao):
            nome = nome[: -len(extensao)]
            break
    return _ECOSSISTEMA.get(nome, "")


def pacote_de(args: List[str]) -> str:
    """O primeiro argumento que não é flag. `npx -y pacote` → `pacote`."""
    for bruto in args or []:
        item = str(bruto).strip()
        if not item or _FLAG.match(item):
            continue
        # `pacote@1.2.3` e `@escopo/pacote@1.2.3`: a versão sai, o escopo fica.
        if item.startswith("@"):
            partes = item.split("@")
            return "@" + partes[1] if len(partes) > 1 else item
        return item.split("@")[0]
    return ""


async def consultar(pacote: str, ecossistema: str, versao: str = "") -> Dict[str, Any]:
    """Pergunta ao OSV o que se sabe sobre o pacote."""
    if not pacote or not ecossistema:
        return {"ok": False, "motivo": "pacote ou ecossistema desconhecido", "consultado": False}

    import httpx

    corpo: Dict[str, Any] = {"package": {"name": pacote, "ecosystem": ecossistema}}
    if versao:
        corpo["version"] = versao

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as cliente:
            resposta = await cliente.post(ENDPOINT, json=corpo)
            resposta.raise_for_status()
            dados = resposta.json()
    except Exception as exc:
        logger.warning("OSV indisponivel para %s (%s): liberando.", pacote, type(exc).__name__)
        return {"ok": True, "consultado": False, "motivo": f"OSV indisponivel: {type(exc).__name__}",
                "malware": [], "vulnerabilidades": []}

    achados = dados.get("vulns") or []
    malware, vulneraveis = [], []
    for item in achados:
        identificador = str(item.get("id") or "")
        registro = {
            "id": identificador,
            "resumo": str(item.get("summary") or "")[:200],
        }
        # MAL-* é a família que o OSV usa para malware confirmado.
        (malware if identificador.upper().startswith("MAL-") else vulneraveis).append(registro)

    return {"ok": True, "consultado": True, "pacote": pacote, "ecossistema": ecossistema,
            "malware": malware, "vulnerabilidades": vulneraveis}


async def verificar(pacote: str, ecossistema: str, versao: str = "") -> Dict[str, Any]:
    """Veredito: pode rodar, e o que se sabe."""
    achado = await consultar(pacote, ecossistema, versao)
    malware = achado.get("malware") or []
    vulneraveis = achado.get("vulnerabilidades") or []

    if malware:
        ids = ", ".join(m["id"] for m in malware)
        return {
            "permitido": False,
            "pacote": pacote,
            "motivo": f"'{pacote}' tem alerta de malware no OSV ({ids})",
            "malware": malware,
            "vulnerabilidades": vulneraveis,
        }

    aviso = ""
    if vulneraveis:
        aviso = (f"'{pacote}' tem {len(vulneraveis)} vulnerabilidade(s) conhecida(s): "
                 + ", ".join(v["id"] for v in vulneraveis[:5]))
    return {
        "permitido": True,
        "pacote": pacote,
        "aviso": aviso,
        "consultado": achado.get("consultado", False),
        "malware": [],
        "vulnerabilidades": vulneraveis,
    }


async def verificar_comando(comando: str, args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Checa o que um comando vai baixar antes de rodá-lo.

    Comando que não baixa pacote passa direto: checar `python meu_script.py`
    contra a base de pacotes não diria nada sobre nada.
    """
    ecossistema = ecossistema_de(comando)
    if not ecossistema:
        return {"permitido": True, "consultado": False,
                "motivo": "comando nao baixa pacote de repositorio publico"}

    pacote = pacote_de(args or [])
    if not pacote:
        return {"permitido": True, "consultado": False, "motivo": "nao identifiquei o pacote"}
    return await verificar(pacote, ecossistema)


__all__ = ["consultar", "ecossistema_de", "pacote_de", "verificar", "verificar_comando"]
