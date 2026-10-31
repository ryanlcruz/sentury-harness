"""Leitura dos arquivos de configuração do Sentury.

O que é POLÍTICA fica em YAML: catálogo de artefato, o que o shell pode
rodar, como as skills aparecem. O que é LÓGICA continua em código:
expressão regular de parsing não é configuração, é implementação.

Duas decisões que valem estar escritas:

1. **Cache com invalidação por mtime.** Ler YAML a cada turno é desperdício;
   nunca reler obriga a reiniciar o processo para trocar uma linha.
2. **Arquivo ilegível devolve o padrão embutido, e avisa.** Config quebrada
   não pode derrubar o agente nem, pior, abrir o que ela deveria fechar.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_CACHE: Dict[str, Dict[str, Any]] = {}


def pasta_de_config() -> Path:
    """Onde os YAML moram. `SENTURY_POLICIES_DIR` aponta para outra pasta."""
    escolhida = os.environ.get("SENTURY_POLICIES_DIR")
    if escolhida:
        return Path(escolhida).expanduser()
    return Path(__file__).resolve().parent


def carregar(nome: str, padrao: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Lê `<nome>.yaml`; releitura só quando o arquivo muda."""
    caminho = pasta_de_config() / f"{nome}.yaml"
    try:
        mtime = caminho.stat().st_mtime
    except OSError:
        logger.warning("Config '%s' ausente em %s; usando o padrao embutido", nome, caminho)
        return dict(padrao or {})

    with _LOCK:
        guardado = _CACHE.get(nome)
        if guardado and guardado.get("mtime") == mtime:
            return guardado["dados"]

    try:
        import yaml

        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        if not isinstance(dados, dict):
            raise ValueError("o arquivo nao descreve um mapa")
    except Exception as exc:
        logger.warning("Config '%s' ilegivel (%s); usando o padrao embutido", nome, exc)
        return dict(padrao or {})

    completo = {**(padrao or {}), **dados}
    with _LOCK:
        _CACHE[nome] = {"mtime": mtime, "dados": completo}
    return completo


def limpar_cache() -> None:
    with _LOCK:
        _CACHE.clear()
