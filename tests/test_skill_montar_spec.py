"""A spec de software deve entrar no pedido certo sem roubar planos gerais."""
from pathlib import Path

import pytest

from sentury.harness.roteamento_de_skill import escolher
from sentury.skills.skill_discovery import SkillDiscoveryEngine
from sentury.skills.skill_loader import SkillLoader
from sentury.tools.registry import TOOL_REGISTRY


RAIZ = Path(__file__).resolve().parents[1] / "sentury" / "skills"


@pytest.fixture(scope="module")
def loader():
    return SkillLoader(RAIZ, com_setor=False)


def test_skill_carrega_e_cita_ferramentas_reais(loader):
    skill = loader.load_skill("montar-spec")
    assert skill is not None
    assert skill.metadata.name == "montar-spec"
    for ferramenta in ("criar_plano", "ver_plano"):
        assert ferramenta in skill.body
        assert ferramenta in TOOL_REGISTRY


def test_contrato_da_spec_esta_no_contexto(loader):
    corpo = loader.load_skill("montar-spec").to_context_block()
    for trecho in (
        "EARS", "espere a aprovação", "design aprovados", "_Requisitos:",
        "criar_plano", "Não prometa `requirements.md`",
    ):
        assert trecho in corpo


@pytest.mark.parametrize("pedido, esperada", [
    ("[montar-spec] API de autenticação", "montar-spec"),
    ("/montar-spec módulo de pagamentos", "montar-spec"),
    ("quero requisitos em EARS para esta feature", None),
    ("monte um plano de ação para reduzir churn", None),
    ("quero um workflow de buscar vagas", None),
    ("corrija este bug no componente", None),
    ("me explique o que é uma API", None),
])
def test_so_ativacao_explicita_escolhe_skill(loader, pedido, esperada):
    entradas = lambda: loader.scan_skills()
    nomes = {entrada.name for entrada in entradas()}
    assert escolher(pedido, nomes, entradas)[0] == esperada


def test_gatilhos_sao_descricao_no_indice(loader):
    indice = SkillDiscoveryEngine(loader).build_index_prompt()
    assert "Pistas descritivas, sem ativação automática:" in indice
    assert next(e for e in loader.scan_skills() if e.name == "montar-spec").gatilhos[0] in indice


def test_sem_tags_genericas_no_discovery(loader):
    entrada = next(e for e in loader.scan_skills() if e.name == "montar-spec")
    assert entrada.gatilhos
    assert not entrada.tags
    assert not entrada.tools_used


def test_discovery_encontra_spec_sem_roubar_plano_de_acao(loader):
    discovery = SkillDiscoveryEngine(loader)
    for pedido in (
        "monte uma spec para a API de autenticação",
        "quero requisitos em EARS para esta feature",
    ):
        assert discovery.discover(pedido, "DECISION", top_k=1)[0][0].name == "montar-spec"
    assert discovery.discover("monte um plano de ação", "DECISION", top_k=1)[0][0].name == "plano-de-acao"
