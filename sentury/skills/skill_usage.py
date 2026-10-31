"""Rastreamento de telemetria e uso de skills no Sentury.

Salva contadores de execução, status de pino e timestamps de última atividade
em um arquivo sidecar JSON chamado '.usage.json' no diretório de skills do usuário.
Garante resiliência e processos de escrita atômica.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SkillUsageTracker:
    """Rastreia telemetria e uso de skills procedurais."""

    def __init__(self, usage_file: Path):
        self.usage_file = Path(usage_file)

    def _read_usage(self) -> Dict[str, Any]:
        if not self.usage_file.is_file():
            return {}
        try:
            content = self.usage_file.read_text(encoding="utf-8")
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.debug("Falha ao ler telemetria de uso de skills: %s. Iniciando nova base.", exc)
            return {}

    def _write_usage(self, data: Dict[str, Any]) -> None:
        try:
            self.usage_file.parent.mkdir(parents=True, exist_ok=True)
            # Escrita atômica usando arquivo temporário para evitar corrupção
            temp_file = self.usage_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            temp_file.replace(self.usage_file)
        except Exception as exc:
            logger.error("Falha ao salvar telemetria de uso de skills: %s", exc)

    def get_record(self, name: str) -> Dict[str, Any]:
        """Retorna o registro de telemetria de uma skill ou um modelo padrão."""
        name = name.strip().lower()
        data = self._read_usage()
        return data.get(name, {
            "name": name,
            "use_count": 0,
            "success_count": 0,
            "last_used_at": None,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "state": "active",
            "pinned": False,
            "is_agent_created": False
        })

    def bump_use(self, name: str, success: bool = True, is_agent_created: bool = False) -> None:
        """Soma contadores de uso e ajusta data de última atividade da skill."""
        name = name.strip().lower()
        data = self._read_usage()
        
        record = data.get(name, {
            "name": name,
            "use_count": 0,
            "success_count": 0,
            "last_used_at": None,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "state": "active",
            "pinned": False,
            "is_agent_created": is_agent_created
        })

        record["use_count"] += 1
        if success:
            record["success_count"] += 1
        record["last_used_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record["state"] = "active"  # Qualquer uso reativa o status da skill

        data[name] = record
        self._write_usage(data)

    def set_pinned(self, name: str, pinned: bool) -> bool:
        """Define o pino de proteção da skill (impede arquivamento pelo Curator)."""
        name = name.strip().lower()
        data = self._read_usage()
        if name not in data:
            record = self.get_record(name)
            record["pinned"] = pinned
            data[name] = record
        else:
            data[name]["pinned"] = pinned
        self._write_usage(data)
        return True
