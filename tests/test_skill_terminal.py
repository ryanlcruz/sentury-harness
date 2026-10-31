"""A skill de terminal disputa pedidos de arquivos sem esconder as skills do setor."""
from pathlib import Path

import pytest

from sentury.skills.skill_discovery import SkillDiscoveryEngine
from sentury.skills.skill_loader import SkillLoader

RAIZ = Path(__file__).resolve().parents[1] / "sentury" / "skills"
SKILL = "executar-no-terminal"


@pytest.fixture(scope="module")
def descoberta():
    """A bancada inclui skills do motor e do setor de teste."""
    do_setor = Path(__file__).parent / "fixtures" / "setor_teste" / "skills"
    return SkillDiscoveryEngine(SkillLoader(RAIZ, do_setor))


def _melhor(descoberta, pedido: str) -> str:
    achadas = descoberta.discover(pedido, "ANALYSIS") or []
    return achadas[0][0].name if achadas else ""


def test_a_skill_existe_e_e_carregada(descoberta):
    nomes = {s.name for s in descoberta.get_available_skills()}
    assert SKILL in nomes


@pytest.mark.parametrize("pedido", [
    "analise o banco de dados nesta pasta",
    "le esse csv e me diz o total",
    "roda um script nos meus arquivos",
])
def test_ganha_quando_o_trabalho_e_sobre_arquivo_do_usuario(descoberta, pedido):
    assert _melhor(descoberta, pedido) == SKILL, pedido


@pytest.mark.parametrize("pedido", [
    "faz um grafico do medida",
    "qual o medida medio",
    # Este caiu de verdade: `analise`/`analisar` nas tags roubaram a causa raiz
    # da skill que sabe faze-la. Verbo generico demais nao e sinal.
    "faca uma analise de causa raiz",
])
def test_nao_rouba_o_que_e_do_dominio(descoberta, pedido):
    """Abrir espaco para o generalista nao pode custar o especialista: a skill
    de terminal nao tem o que dizer sobre uma pergunta de Medida."""
    assert _melhor(descoberta, pedido) != SKILL, pedido


def test_ensina_a_olhar_antes_de_calcular():
    """O turno com LLM real falhou exatamente aqui: o agente chutou o nome das
    colunas do CSV, errou e devolveu o erro ao usuario."""
    texto = (RAIZ / "cognitive" / SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "Olhe antes de calcular" in texto
    assert "ler_arquivo" in texto


def test_diz_que_artefato_continua_no_sandbox():
    """Grafico, slide e PDF continuam pelo `executar_python`, que anexa sozinho.
    Pelo terminal o arquivo fica no disco e ninguem entrega: sem isso escrito,
    a skill empurraria o agente para perder a entrega."""
    texto = (RAIZ / "cognitive" / SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "executar_python" in texto
    assert "entregar_arquivo" in texto


def test_avisa_do_metacaractere():
    """O shell roda sem shell interpretado: `|`, `;` e `&&` sao recusados. Sem
    o aviso, o agente descobre isso falhando no meio do turno."""
    texto = (RAIZ / "cognitive" / SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "&&" in texto and "sem shell interpretado" in texto
