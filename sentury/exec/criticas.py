"""Reconhece consequências que exigem confirmação pontual pela política local."""
from __future__ import annotations

import ntpath
import hashlib
import os
import posixpath
import re
from pathlib import Path


def remoto() -> bool:
    from ..tools.ambiente import _sistema

    dados = _sistema()
    # Ausência de sinal de desktop não prova que seja seguro agir como no PC.
    return bool(dados["container"] or dados["vm_de_nuvem"] or dados["servico_systemd"]
                or dados["onde_roda"] != "computador pessoal")


def _normalizar(caminho: str) -> str:
    texto = os.path.expandvars(os.path.expanduser(caminho)).replace("\\", "/")
    if re.match(r"^[a-z]:/", texto, re.I):
        return ntpath.normpath(texto).replace("\\", "/").casefold()
    return posixpath.normpath(texto).casefold()


def _conteudo(partes: list, tabela: dict, diretorio: str = "") -> str:
    if not partes or ntpath.basename(partes[0]).casefold().removesuffix(".exe") not in (tabela.get("executa") or {}):
        return ""
    arquivo = next((p for p in partes[1:] if not p.startswith("-")), "")
    try:
        alvo = Path(arquivo).expanduser()
        if diretorio and not alvo.is_absolute():
            alvo = Path(diretorio) / alvo
        if alvo.is_file() and alvo.stat().st_size <= 2 * 1024 * 1024:
            return alvo.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeError):
        pass
    return ""


def _contexto(comando: str) -> tuple[str, str]:
    from ..tools.shell import composto, partes_do_comando

    trechos = composto(comando)
    if trechos and len(trechos[0]) == 2:
        primeiro = partes_do_comando(trechos[0][0])
        if len(primeiro) == 2 and primeiro[0] == "cd":
            return trechos[0][1], primeiro[1]
    return comando, ""


def identidade(comando: str) -> str:
    from ..tools.shell import partes_do_comando, politica

    try:
        linha, diretorio = _contexto(comando)
        corpo = _conteudo(partes_do_comando(linha), politica(), diretorio)
    except ValueError:
        corpo = ""
    return hashlib.sha256((comando.strip() + "\0" + corpo).encode("utf-8")).hexdigest()[:32]


def _alcanca(texto: str, caminhos: list, diretorio: str = "") -> bool:
    from ..tools.shell import partes_do_comando

    try:
        partes = partes_do_comando(texto)
    except ValueError:
        partes = []
    candidatos = []
    for parte in partes[1:]:
        alvo = parte.split("=", 1)[-1]
        candidatos.append(_normalizar(alvo))
        try:
            caminho = Path(alvo).expanduser()
            if diretorio and not caminho.is_absolute():
                caminho = Path(diretorio) / caminho
            candidatos.append(_normalizar(str(caminho.resolve())))
        except (OSError, ValueError):
            pass
    bruto = texto.replace("\\", "/").casefold()
    for caminho in caminhos:
        marca = _normalizar(str(caminho)).rstrip("/")
        if any(c == marca or c.startswith(marca + "/") for c in candidatos):
            return True
        # O corpo de um script pode referenciar o alvo sem formar um argv de shell.
        if re.search(r"(?<![\w./-])" + re.escape(marca) + r"(?=$|[/\s\"'])", bruto):
            return True
    return False


def no_diretorio(comando: str, diretorio: str = "") -> str:
    if diretorio and motivo(comando, diretorio=diretorio):
        raiz = str(Path(diretorio).expanduser().resolve()).replace("\\", "/")
        return f'cd "{raiz}" && {comando}'
    return comando


def motivo(comando: str, *, corpo: str = "", diretorio: str = "") -> str:
    from ..tools.shell import partes_do_comando, politica, so_leitura

    tabela = politica()
    regras = tabela.get("confirmar_na_hora") or {}
    if not regras:
        return ""
    try:
        if not corpo and so_leitura(comando):
            return ""
        comando, contexto = _contexto(comando)
        diretorio = diretorio or contexto
        partes = partes_do_comando(comando)
    except ValueError:
        partes = []
    programa = ntpath.basename(partes[0]).casefold().removesuffix(".exe") if partes else ""
    corpo = corpo or _conteudo(partes, tabela, diretorio)
    if _alcanca(comando, regras.get("caminhos") or [], diretorio) or (corpo and _alcanca(corpo, regras.get("caminhos") or [], diretorio)):
        return "Esta ação alcança um caminho crítico; confirme só esta execução."
    if not remoto():
        return ""
    if programa in (regras.get("programas_remotos") or []):
        return "Esta ação pode alterar a infraestrutura remota; confirme só esta execução."
    for regra in regras.get("servicos_remotos") or []:
        if programa != regra.get("programa"):
            continue
        argumentos = {p.casefold() for p in partes[1:]}
        if argumentos.intersection(regra.get("acoes") or []) and argumentos.intersection(regra.get("alvos") or []):
            return "Esta ação pode alterar um serviço crítico; confirme só esta execução."
    # Código arbitrário pode construir nomes dinamicamente; busca textual não o isola.
    if regras.get("interpretadores_remotos") and programa in (tabela.get("executa") or {}):
        return "Código arbitrário na máquina remota pode alterar a infraestrutura; confirme só esta execução."
    return ""
