"""As escolhas da instalação feitas pela tela: embeddings, voz e o que vier.

O cardápio de cada escolha mora em `ajustes.yaml`; o valor escolhido mora em
`~/.sentury/ajustes.json`, porque é decisão da máquina, não do repositório.
Nada aqui guarda chave: o provedor aponta o nome da variável que o cofre preenche.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)

ARQUIVO = "ajustes.json"
_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def cardapio() -> Dict[str, Any]:
    with open(Path(__file__).with_name("ajustes.yaml"), encoding="utf-8") as arquivo:
        return yaml.safe_load(arquivo) or {}


def _caminho() -> Path:
    from .tools.arquivos import casa_do_sentury

    return casa_do_sentury() / ARQUIVO


def _tudo() -> Dict[str, Any]:
    try:
        dados = json.loads(_caminho().read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        logger.warning("ajustes.json ilegível; seguindo com o padrão.", exc_info=True)
        return {}


def ler(secao: str) -> Dict[str, Any]:
    """O que foi escolhido na seção; vazio quando ninguém escolheu."""
    valor = _tudo().get(secao)
    return dict(valor) if isinstance(valor, dict) else {}


def gravar(secao: str, valores: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        tudo = _tudo()
        tudo[secao] = dict(valores)
        alvo = _caminho()
        alvo.parent.mkdir(parents=True, exist_ok=True)
        temporario = alvo.with_suffix(".tmp")
        temporario.write_text(json.dumps(tudo, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporario, alvo)
    return dict(valores)


def provedor(secao: str, nome: str) -> Dict[str, Any]:
    """A entrada do cardápio para o provedor, ou vazio se ele não existe."""
    return dict(((cardapio().get(secao) or {}).get("provedores") or {}).get(nome) or {})


def _valor(variavel: str) -> str:
    """O cofre primeiro; o ambiente e o `.env` só quando o cofre não tem a chave."""
    try:
        from robinbandit.accounts import secrets

        guardado = secrets.ler(variavel)
        if str(guardado or "").strip():
            return str(guardado)
    except Exception:
        pass
    from .config import settings

    return str(os.environ.get(variavel) or getattr(settings, variavel, "") or "")


def tem_chave(entrada: Dict[str, Any]) -> bool:
    """Se a chave do provedor existe; sem chave declarada, não precisa."""
    variavel = entrada.get("chave")
    return not variavel or bool(_valor(variavel).strip())


def chave(entrada: Dict[str, Any]) -> str:
    """A primeira chave da variável: o cofre guarda listas separadas por vírgula."""
    variavel = entrada.get("chave")
    return _valor(variavel).split(",")[0].strip() if variavel else ""
