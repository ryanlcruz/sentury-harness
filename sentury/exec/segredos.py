"""Redige credenciais nas cópias de diagnóstico, sem alterar o que a API usa."""
from __future__ import annotations

import re
import threading
from urllib.parse import quote, quote_plus, unquote

MARCA = "[redigido]"
_trava = threading.RLock()
_valores: set[str] = set()
_CHAVE = re.compile(r"(?i)(api[_-]?key|token|secret|password|credential|authorization|senha)")
_ATRIBUICAO = re.compile(
    r'''(?i)(["']?\b[A-Z0-9_-]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION|SENHA)[A-Z0-9_-]*["']?\s*[=:]\s*)'''
    r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\[[^\]\r\n]*\]|[^\s"'<>\)\}]+)'''
)
_PREFIXO = re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{12,}|gsk_[A-Za-z0-9_\-]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._=+\-/]{8,}")
_USERINFO = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+:[^@/\s]+@")
_BOT = re.compile(r"\b\d{5,16}(?::|%3[aA])[A-Za-z0-9_\-]{20,128}\b")
_BOT_URL = re.compile(r"(?i)(https?://api\.telegram\.org/(?:file/)?bot)[^/\s\"'<>]+")


def chave_sensivel(nome: str) -> bool:
    return bool(_CHAVE.search(str(nome))) and str(nome).casefold() != "tokens"


def registrar_configuracao(dados: dict) -> None:
    candidatos = []
    for nome, valor in dados.items():
        if not chave_sensivel(nome):
            continue
        valores = valor if isinstance(valor, (list, tuple)) else [valor]
        for item in valores:
            if isinstance(item, str):
                candidatos.extend(parte.strip() for parte in item.split(","))
    with _trava:
        for valor in candidatos:
            # Valores curtos como "ollama" também nomeiam provedores no diagnóstico.
            if len(valor) >= 8 and valor != MARCA:
                _valores.update((valor, quote(valor, safe=""), quote_plus(valor)))


def redigir_segredos(texto: str) -> str:
    saida = texto or ""
    with _trava:
        conhecidos = sorted(_valores, key=len, reverse=True)
    for valor in conhecidos:
        saida = saida.replace(valor, MARCA)
    def ocultar(match):
        valor = match.group(2)
        nome = match.group(1).rstrip(" :=").strip("\"'").casefold()
        if valor.isdigit() and (nome == "tokens" or nome.endswith("_tokens") or nome.endswith("token_count")):
            return match.group(0)
        aspa = valor[0] if valor[:1] in ("'", '"') else ""
        return match.group(1) + aspa + MARCA + aspa
    saida = _ATRIBUICAO.sub(ocultar, saida)
    saida = _BOT_URL.sub(lambda match: match.group(1) + MARCA, saida)
    saida = _BOT.sub(MARCA, saida)
    saida = _PREFIXO.sub(MARCA, saida)
    saida = _USERINFO.sub(lambda match: match.group(1) + MARCA + "@", saida)
    return _BEARER.sub(lambda match: match.group(1) + " " + MARCA, saida)


def tem_segredo(texto: str) -> bool:
    bruto = texto or ""
    return any(redigir_segredos(valor) != valor for valor in (bruto, unquote(bruto)))


def sanitizar_dados(valor):
    if isinstance(valor, dict):
        return {nome: (MARCA if chave_sensivel(nome) and isinstance(item, (str, list, tuple, dict)) and item
                       else sanitizar_dados(item)) for nome, item in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [sanitizar_dados(item) for item in valor]
    return redigir_segredos(valor) if isinstance(valor, str) else valor
