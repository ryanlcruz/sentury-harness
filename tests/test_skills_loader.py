"""Testes unitários para o carregamento e pré-processamento de skills.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from sentury.skills.skill_loader import SkillLoader, parse_frontmatter


def test_parse_frontmatter():
    content = """---
name: test-skill
category: tests
tags: [unit, debug]
---
# Test Content
Procedure steps here.
"""
    fm, body = parse_frontmatter(content)
    assert fm["name"] == "test-skill"
    assert fm["category"] == "tests"
    assert "unit" in fm["tags"]
    assert "# Test Content" in body


def test_skill_loader_scan_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Cria uma skill dummy
        skill_dir = tmp_path / "dummy-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: dummy-skill
description: "Test description of dummy skill."
category: custom
family: artifacts
priority: 70
tags: [dummy, test]
tools_used: [executar_python]
platforms: [linux, macos, windows]
---
# Dummy Skill body
${SENTURY_SKILLS_DIR}
""", encoding="utf-8")

        # Cria subpasta de referências
        ref_dir = skill_dir / "references"
        ref_dir.mkdir()
        ref_txt = ref_dir / "helper.txt"
        ref_txt.write_text("Reference content here", encoding="utf-8")

        # Instancia o loader
        loader = SkillLoader(tmp_path)
        
        # 1. Testa scan
        entries = loader.scan_skills(force=True)
        assert len(entries) == 1
        assert entries[0].name == "dummy-skill"
        assert entries[0].category == "custom"
        assert entries[0].family == "artifacts"
        assert entries[0].priority == 70
        assert "dummy" in entries[0].tags

        # 2. Testa load completo (Nível 1)
        content = loader.load_skill("dummy-skill")
        assert content is not None
        assert content.metadata.name == "dummy-skill"
        assert content.metadata.family == "artifacts"
        assert content.metadata.priority == 70
        assert "references/helper.txt" in content.available_references
        
        # 3. Verifica se a variável de template foi substituída
        assert str(skill_dir.resolve()) in content.body

        # 4. Testa load de referência (Nível 2)
        ref_content = loader.load_reference("dummy-skill", "references/helper.txt")
        assert ref_content == "Reference content here"
