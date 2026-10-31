"""Curator: Gerenciador de ciclo de vida e telemetria de inatividade.

Mantém as skills procedurais físicas ativas para sempre no filesystem.
Apenas monitora os logs de uso no `.usage.json` e sinaliza inatividade ('stale')
para exibição visual de telemetria no Dashboard.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .skill_usage import SkillUsageTracker

logger = logging.getLogger(__name__)


class SkillCurator:
    """Orquestrador de telemetria e inatividade informativa para as skills."""

    def __init__(self, skills_dir: Path, usage_tracker: SkillUsageTracker):
        self.skills_dir = Path(skills_dir)
        self.usage_tracker = usage_tracker

    def _parse_timestamp(self, ts_str: Optional[str]) -> Optional[datetime]:
        if not ts_str:
            return None
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            return None

    def run_curator(self, stale_days: int = 30, archive_days: int = 90, dry_run: bool = False) -> Dict[str, List[str]]:
        """Varre as skills procedurais e atualiza o estado de inatividade apenas no JSON.
        
        As skills procedurais físicas NUNCA são removidas ou movidas do filesystem (se mantêm ativas).
        """
        report = {
            "marked_stale": [],
            "archived": [],
            "skipped_pinned": []
        }

        usage_data = self.usage_tracker._read_usage()
        now = datetime.now(timezone.utc)

        # Mapeia as pastas físicas que existem
        for folder in self.skills_dir.iterdir():
            if not folder.is_dir() or folder.name.startswith(".") or folder.name in (
                "software-development", "github", "data-science", "research", "creative", "productivity", "media"
            ):
                continue

            name = folder.name.lower()
            record = usage_data.get(name)

            if not record:
                mtime = datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc)
                anchor = mtime
            else:
                last_used = self._parse_timestamp(record.get("last_used_at"))
                created = self._parse_timestamp(record.get("created_at"))
                anchor = last_used or created or now

            if record and record.get("pinned"):
                report["skipped_pinned"].append(name)
                continue

            delta_days = (now - anchor).days

            # Apenas atualiza o status de inatividade no usage tracker para exibição visual
            if delta_days >= stale_days:
                if not dry_run:
                    data = self.usage_tracker._read_usage()
                    record = self.usage_tracker.get_record(name)
                    record["state"] = "stale"
                    data[name] = record
                    self.usage_tracker._write_usage(data)
                report["marked_stale"].append(name)

        return report

    def restore_skill(self, name: str) -> bool:
        """Sempre ativo por padrão, pois as skills procedurais físicas nunca são arquivadas."""
        name = name.strip().lower()
        data = self.usage_tracker._read_usage()
        if name in data:
            data[name]["state"] = "active"
            self.usage_tracker._write_usage(data)
            return True
        return False

