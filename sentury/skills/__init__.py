"""Carregamento progressivo de skills procedurais do Sentury.

Três níveis de carregamento:
  Nível 0: skills_list()          → índice leve ({name, description, category})
  Nível 1: load_skill(name)      → SKILL.md completo + metadados
  Nível 2: load_reference(name, path) → arquivo específico de references/templates/
"""

from .skill_schema import SkillContent, SkillEntry, SkillMetadata
from .skill_loader import SkillLoader
from .skill_discovery import SkillDiscoveryEngine

__all__ = [
    "SkillContent",
    "SkillEntry",
    "SkillMetadata",
    "SkillLoader",
    "SkillDiscoveryEngine",
]
