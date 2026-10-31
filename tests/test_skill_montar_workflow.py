"""A skill que ensina o modelo a conduzir um trabalho de várias fases.

O plano já existia em disco; o que faltava era julgamento: quando criar, como
dividir, onde parar e perguntar, e com que prova marcar. Estes testes protegem
as três coisas que, se saírem do texto, fazem a skill virar enfeite.
"""
from pathlib import Path

import pytest

from sentury.skills.skill_loader import SkillLoader
from sentury.tools.registry import TOOL_REGISTRY

RAIZ = Path(__file__).resolve().parents[1] / "sentury" / "skills"


@pytest.fixture(scope="module")
def skill():
    carregador = SkillLoader(RAIZ, com_setor=True)
    conteudo = carregador.load_skill("montar-workflow")
    assert conteudo is not None, "a skill nao foi encontrada pelo carregador"
    return conteudo


def test_esta_no_catalogo_de_skills():
    nomes = {entrada.name for entrada in SkillLoader(RAIZ, com_setor=True).scan_skills()}
    assert "montar-workflow" in nomes


def test_so_cita_ferramenta_que_existe(skill):
    """Skill que ensina a usar ferramenta renomeada ensina a errar.

    As ferramentas sao citadas no corpo, e nao no frontmatter: `tools_used`
    tambem alimenta a descoberta difusa, e la elas puxavam a skill para frases
    que nao sao dela.
    """
    import re

    citadas = set(re.findall(r"`([a-z_]+)`", skill.body))
    conhecidas = {c for c in citadas if c.endswith(("_plano", "_tarefa", "_task", "_schedules", "_usuario"))}
    assert conhecidas, "a skill deixou de citar as ferramentas que ensina"
    ausentes = sorted(c for c in conhecidas if c not in TOOL_REGISTRY)
    assert not ausentes, f"a skill cita ferramenta inexistente: {ausentes}"


def test_dispara_por_gatilho_proprio_e_nao_por_palavra_solta(skill):
    """A descoberta difusa soma ponto por palavra, e "plano"/"tarefa" pertencem
    a outras skills. Esta declara os casos que sao dela, em regex."""
    entrada = [e for e in SkillLoader(RAIZ, com_setor=True).scan_skills()
               if e.name == "montar-workflow"][0]
    assert entrada.gatilhos, "sem gatilho proprio ela so existe por sorte do ranking"
    assert not entrada.tags, "tag generica rouba skill do setor e do terminal"


def test_ensina_os_tres_criterios_de_criacao(skill):
    corpo = skill.body
    assert "mais de uma fase" in corpo
    assert "altera alguma coisa" in corpo
    assert "não termina hoje" in corpo


def test_ensina_prova_positiva(skill):
    # "Nao deu erro" nunca foi prova de que a tarefa terminou.
    assert "prova positiva" in skill.body
    assert '"Não deu erro" não é prova' in skill.body


def test_ensina_proporcao_de_portoes(skill):
    """Portao em todo passo é aprovado no automático, e aí não protege nada."""
    assert "três portões em dez tarefas" in skill.body


def test_ensina_a_ler_o_plano_antes_de_recomecar(skill):
    assert "ver_plano" in skill.body


def test_cobre_a_rotina_que_roda_sozinha(skill):
    """Cron e opcional; workflow nao nasce definido pelo relogio."""
    assert "criar_workflow" in skill.body
    assert "Workflow **não precisa de gatilho**" in skill.body
    assert "Não chame `agenda` junto" in skill.body
    assert "Aprovar e começar" in skill.body


def test_nao_manda_escrever_o_markdown_por_python(skill):
    assert "Nunca use `executar_python`" in skill.body
    assert "escrever o arquivo por fora pula validação" in skill.body


def test_nao_manda_o_modelo_pensar_numa_ordem(skill):
    """Plano diz o que precisa ficar pronto; roteiro de raciocínio engessa.

    A skill fala de ordem de EXECUÇÃO (fases), nunca de ordem de pensamento:
    e o texto precisa dizer isso, senão o próximo item escrito nela escorrega.
    """
    assert "não diz **em que ordem pensar**" in skill.body


def test_o_bloco_de_contexto_carrega_as_regras(skill):
    bloco = skill.to_context_block()
    for pedaco in ("fase", "portão", "prova positiva"):
        assert pedaco in bloco, f"'{pedaco}' nao chega ao contexto do turno"


@pytest.mark.parametrize("frase, esperado", [
    ("acompanha ate fechar, por favor", True),
    ("conduz esse trabalho comigo", True),
    ("retoma de onde paramos ontem", True),
    ("toda segunda de manha pega o relatorio e atualiza a base", True),
    ("todo dia as 8 analisa a fila e me avisa", True),
    # O que NAO e dela: pergunta curta, leitura de arquivo, plano de acao de CX.
    ("me diz o NPS de setembro", False),
    ("le esse csv e me diz o total", False),
    ("monte um plano de acao para reduzir o churn", False),
])
def test_gatilhos_pegam_o_caso_certo(frase, esperado):
    """O gatilho e regex e o mais especifico ganha. Estas frases sao o contrato:
    as tres ultimas pertencem a outras skills, e ja foram roubadas uma vez."""
    import re
    import unicodedata

    entrada = [e for e in SkillLoader(RAIZ, com_setor=True).scan_skills()
               if e.name == "montar-workflow"][0]
    nua = unicodedata.normalize("NFKD", frase).encode("ascii", "ignore").decode().lower()
    casou = any(re.search(padrao, nua) for padrao in entrada.gatilhos)
    assert casou is esperado, f"'{frase}' deveria {'casar' if esperado else 'passar'}"
