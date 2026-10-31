"""Discovery de skills: tokenização (acento/pontuação) e ranqueamento em PT."""
import pytest

from sentury.skills.skill_discovery import _tokens


def test_tokens_normaliza_acento_e_pontuacao():
    t = _tokens("Grupo, causa-raiz! jornada.")
    assert {"grupo", "causa", "raiz", "jornada"}.issubset(t)
    # descarta tokens de 1 char e pontuação
    assert "" not in t and "," not in t


def test_discovery_acha_skill_certa_em_pt(setor_teste):
    import sentury.main as m
    disc = m.orchestrator.skill_discovery
    # PT com acento tem que casar a skill certa (antes do fix, dava vazio)
    top = disc.discover("faça uma análise de causa raiz", "ANALYSIS", top_k=1)
    assert top and top[0][0].name == "consulta-medida"
    top = disc.discover("monte um plano de ação", "DECISION", top_k=1)
    assert top and top[0][0].name == "plano-de-acao"


def test_discovery_nome_citado_pontua_alto():
    # /skill (nome citado) → score >= 2.0 (dispara o skill-boost pra CRITICAL)
    import sentury.main as m
    disc = m.orchestrator.skill_discovery
    top = disc.discover("/concept-diagrams desenhe a causa raiz", "TOOL_USE", top_k=1)
    assert top and top[0][0].name == "concept-diagrams" and top[0][1] >= 2.0


@pytest.mark.parametrize("setor_nome", ["generalista", "setor_teste"])
def test_plano_geral_sem_metodologias_do_setor(setor_nome):
    """O índice geral oferece planejamento, sem carregar o diagnóstico do setor."""
    import sentury.main as m
    from sentury.domains.escopo import usar_setor

    disc = m.orchestrator.skill_discovery
    with usar_setor(setor_nome):
        nomes = {e.name for e in disc.loader.scan_skills()}
        assert {"dmaic", "ishikawa", "root-cause-analysis"}.isdisjoint(nomes)
        top = disc.discover("monte um plano de ação sobre isso", "DECISION", top_k=1)
        assert top and top[0][0].name == "plano-de-acao"


def test_catalogo_generalista_e_plano_nao_anunciam_diagnostico_do_setor(tmp_path):
    from pathlib import Path

    from sentury.domains.escopo import usar_setor
    from sentury.skills.skill_discovery import SkillDiscoveryEngine
    from sentury.skills.skill_loader import SkillLoader, vitrine_das_skills

    loader = SkillLoader(Path(__file__).parents[1] / "sentury/skills", tmp_path, com_setor=True)
    with usar_setor("generalista"):
        indice = SkillDiscoveryEngine(loader).build_index_prompt().lower()
        plano = loader.load_skill("plano-de-acao")
        assert plano is not None
        for termo in ("ishikawa", "dmaic", "six sigma", "5 porquês"):
            assert termo not in indice
            assert termo not in plano.body.lower()
        assert {"dmaic", "ishikawa"}.isdisjoint(vitrine_das_skills())
        assert "5W2H" in plano.body and "Gravidade × Urgência × Tendência" in plano.body
