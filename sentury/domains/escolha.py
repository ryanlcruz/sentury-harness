"""Qual setor está ligado, escolhido pela interface.

A escolha mora em `~/.sentury/setor.json`, e não só em `SENTURY_DOMAIN`,
porque é decisão da instalação, não do repositório: duas máquinas com o mesmo
clone podem rodar setores diferentes.

Vazio é o generalista: o motor inteiro, sem métrica nem persona de setor.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .pack import DomainPack

logger = logging.getLogger(__name__)

ARQUIVO = "setor.json"
GENERALISTA = "generalista"

# Sem métrica e sem persona: nada de setor entra no prompt nem no caminho
# do turno. É o Sentury cru.
PACK_GENERALISTA = DomainPack(
    name=GENERALISTA,
    metric_meta={},
    higher_is_better={},
    cx_metrics=frozenset(),
    ops_metrics=frozenset(),
)


def caminho(sentury_home: str = "") -> Path:
    from ..config import settings
    from ..memory.local_session_store import default_sentury_home

    casa = sentury_home or getattr(settings, "SENTURY_HOME", "") or ""
    return default_sentury_home(casa) / ARQUIVO


def ler(sentury_home: str = "") -> Optional[str]:
    """O setor escolhido, ou `None` quando ninguém escolheu nada ainda."""
    try:
        dados = json.loads(caminho(sentury_home).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(dados, dict) or "setor" not in dados:
        return None
    return str(dados.get("setor") or "").strip()


def gravar(setor: str, sentury_home: str = "") -> str:
    escolhido = str(setor or "").strip() or GENERALISTA
    alvo = caminho(sentury_home)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(
        json.dumps({"setor": escolhido, "quando": time.time()}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    logger.info("Setor ativo passou a ser '%s'.", escolhido)
    return escolhido


__all__ = ["ARQUIVO", "GENERALISTA", "PACK_GENERALISTA", "caminho", "gravar", "ler"]
