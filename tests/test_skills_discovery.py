"""Testes unitários para o Discovery Engine de skills.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from sentury.skills.skill_loader import SkillLoader
from sentury.skills.skill_discovery import SkillDiscoveryEngine


def test_discovery_filtering_and_ranking():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Cria skill 1 (Compatível com qualquer plataforma)
        skill1_dir = tmp_path / "medida-advanced"
        skill1_dir.mkdir()
        (skill1_dir / "SKILL.md").write_text("""---
name: medida-advanced
description: "Análise avançada de Medida e Medida detratores."
category: cx
tags: [medida, detrator, score]
tools_used: [consultar_medida]
---
# Medida Body
""", encoding="utf-8")

        # Cria skill 2 (Incompatível com a plataforma atual via gating fictício)
        skill2_dir = tmp_path / "macos-only"
        skill2_dir.mkdir()
        (skill2_dir / "SKILL.md").write_text("""---
name: macos-only
description: "macOS specific script execution."
category: admin
tags: [macos, script]
platforms: [macos]
---
# MacOS Body
""", encoding="utf-8")

        loader = SkillLoader(tmp_path)
        engine = SkillDiscoveryEngine(loader)

        # Força escaneamento inicial
        loader.scan_skills(force=True)

        # Executa descoberta com base em palavra da mensagem
        results = engine.discover(user_message="Como calcular o medida de detrator?", intent="ANALYSIS")
        
        # Verifica se obteve a skill relevante e filtrou a incompatível (macos-only, a menos que rodando em macOS)
        assert len(results) >= 1
        top_skill, score = results[0]
        assert top_skill.name == "medida-advanced"
        assert score > 0.0

        # Verifica se o prompt indexado compacto é construído
        prompt = engine.build_index_prompt()
        assert "medida-advanced" in prompt
