"""A skill que guia a montagem de uma equipe de residentes.

Uma equipe montada no improviso sai com papéis sobrepostos e vozes iguais, e a
Mesa vira fila de "concordo". Estes testes protegem o que faz a skill servir:
ela é achada no pedido de equipe, cita só ferramentas que existem e ensina os
três pontos que mudam o resultado.
"""
import re
from pathlib import Path

import pytest

from sentury.skills.skill_loader import SkillLoader
from sentury.tools.registry import TOOL_REGISTRY

RAIZ = Path(__file__).resolve().parents[1] / "sentury" / "skills"


@pytest.fixture(scope="module")
def entrada():
    achadas = [e for e in SkillLoader(RAIZ, com_setor=True).scan_skills() if e.name == "montar-equipe"]
    assert achadas, "a skill nao esta no catalogo"
    return achadas[0]


@pytest.fixture(scope="module")
def skill():
    conteudo = SkillLoader(RAIZ, com_setor=True).load_skill("montar-equipe")
    assert conteudo is not None
    return conteudo


def _dispara(entrada, frase: str) -> bool:
    return any(re.search(g, frase, re.IGNORECASE) for g in entrada.gatilhos)


@pytest.mark.parametrize("frase", [
    "monta uma equipe de CX pra mim",
    "quero um time para pesquisar concorrentes",
    "crie uns residentes para cuidar do suporte",
    "forme um time de lançamento com 4 pessoas",
    "crie o quinto agente da equipe",
    "quero mais um residente pro time de CX",
    "complete a equipe com quem falta",
])
def test_dispara_no_pedido_de_equipe(entrada, frase):
    assert _dispara(entrada, frase)


@pytest.mark.parametrize("frase", [
    "monte uma planilha com as vendas",
    "o agente falhou na tarefa de ontem",
    "crie um relatório do time de CX",
    "peça ao Tito o cronograma",
])
def test_fica_de_fora_do_pedido_comum(entrada, frase):
    """Gatilho largo demais rouba a vez de outras skills e enche o turno de texto inútil."""
    assert not _dispara(entrada, frase)


def test_so_cita_ferramenta_que_existe(skill):
    citadas = set(re.findall(r"`([a-z_]+)`", skill.body))
    ferramentas = {c for c in citadas if c in ("criar_agente", "pedir_ao_agente", "perguntar_usuario", "pedir_ferramenta")}
    assert ferramentas == {"criar_agente", "pedir_ao_agente", "perguntar_usuario", "pedir_ferramenta"}
    assert all(f in TOOL_REGISTRY for f in ferramentas)


def test_ensina_papel_que_recusa_voz_que_discorda_e_aprovacao(skill):
    corpo = skill.body
    assert "o que não é com ele" in corpo
    assert "otimizam coisas diferentes" in corpo
    assert "Criar é" in corpo and "propor" in corpo
