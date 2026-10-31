"""A régua: sem DomainPack, o Sentury é um generalista, não um CX quebrado.

Nas palavras do usuário: *"se removemos os DomainPacks, quero zero,
completamente zero, coisas relacionadas a CX ou qualquer área"*.

Isto é o teste dessa frase. Sem ele, a régua depende de alguém lembrar de
conferir: e hoje mesmo eu "provei" rodando à mão, que é exatamente o tipo de
verificação que some na semana seguinte.

Três coisas impediam a régua de ser verdade, e as três já caíram:

1. `domains/cx.py`: um pacote em Python que o YAML já sobrescrevia na subida.
   Apagar `setores/` deixava o CX registrado assim mesmo.
2. `get_active_domain()` caía em `"cx"` e estourava `KeyError` se o cx também
   não existisse: uma pasta renomeada derrubava o Sentury.
3. `build_system_persona()` caía em `IDENTIDADE_CX`: um pacote de vendas se
   apresentando como analista de experiência do cliente.
"""
import re

import pytest

VOCABULARIO_DE_DOMINIO = (
    r"\bnps\b", r"\bcsat\b",
    r"equipamento", r"\bdetratore?s?\b", r"\bpromotore?s?\b",
    r"analyze_", r"root_cause", r"executive_summary",
    r"unidade de neg", r"\bfilial\b",
)


@pytest.fixture
def sem_pacote(monkeypatch):
    """O mundo depois de `rm -rf domains/setores/`."""
    from sentury.domains import carregador, escolha, registry

    monkeypatch.setattr(carregador, "descobrir", lambda *a, **k: [])
    # Alguém tinha escolhido o CX antes de a pasta sumir: é o caso que quebrava.
    monkeypatch.setattr(escolha, "ler", lambda *a, **k: "cx")

    # Esvazia o registro em vez de recarregar o módulo: `importlib.reload` com
    # `descobrir` mockado deixava o registro vazio para os testes SEGUINTES,
    # porque o estado do módulo é global e o `monkeypatch` só desfaz o mock.
    monkeypatch.setattr(registry, "DOMAIN_REGISTRY", {})
    yield registry


# --------------------------------------------------- o motor sobrevive

def test_sem_pacote_o_sentury_sobe(sem_pacote):
    """Antes isto era `KeyError: 'cx'`: a pasta sumia e o agente ia junto."""
    pack = sem_pacote.get_active_domain()
    assert pack.name == "generalista"


def test_o_generalista_nao_herda_nada_do_setor(sem_pacote):
    pack = sem_pacote.get_active_domain()
    assert not pack.metric_names
    assert not pack.persona
    assert not getattr(pack, "responder", None)
    assert not getattr(pack, "planner", None)


def test_nenhum_setor_nasce_de_codigo(sem_pacote):
    """Se um voltar a ser importado direto, a régua para de valer em silêncio."""
    assert sem_pacote.DOMAIN_REGISTRY == {}


# ------------------------------------------- o que chega ao modelo

def test_a_persona_do_generalista_nao_fala_de_dominio():
    """O `NUCLEO_DO_AGENTE` tinha 45 de 188 linhas de CX, e como
    `build_system_persona()` faz `identidade + nucleo`, o generalista herdava
    tudo: 34 mil caracteres de NPS, CSAT e equipamento."""
    from sentury.domains import escolha
    from sentury.llm import prompts

    original = escolha.ler
    try:
        escolha.ler = lambda *a, **k: "generalista"
        persona = prompts.system_persona_do_dominio()
    finally:
        escolha.ler = original

    achados = [p for p in VOCABULARIO_DE_DOMINIO if re.search(p, persona, re.I)]
    assert achados == [], achados


def test_o_prompt_do_planejador_tambem_nao():
    from sentury.harness.orchestrator import PLANNER_SYSTEM_PROMPT

    achados = [p for p in VOCABULARIO_DE_DOMINIO if re.search(p, PLANNER_SYSTEM_PROMPT, re.I)]
    assert achados == [], achados


def test_a_mesa_do_generalista_nao_tem_ferramenta_de_setor():
    from sentury.domains import escolha
    from sentury.llm.tool_schemas import build_tool_schemas
    from sentury.tools.registry import TOOL_REGISTRY

    original = escolha.ler
    try:
        escolha.ler = lambda *a, **k: "generalista"
        nomes = [s["function"]["name"] for s in build_tool_schemas() if "function" in s]
    finally:
        escolha.ler = original

    de_setor = [n for n in nomes if (TOOL_REGISTRY.get(n) or {}).get("setor")]
    assert de_setor == [], de_setor


# ----------------------------------------------- e o setor volta inteiro


# ------------------------------------ TODO texto que vai ao modelo, sem escolher

def test_nenhum_texto_base_do_motor_fala_de_dominio():
    """A régua media a persona e o prompt do planejador, e dizia ZERO. Mas o
    redator da resposta final usa OUTRO prompt (`RESPONDER_PERSONA`), e ele abria
    apresentando o agente como especialista de um setor: dezenas de ocorrências
    num texto que a régua nunca olhou. O cartão de KPI de exemplo dizia "NPS
    consolidado".

    O erro foi o recorte: medir os prompts que eu lembrei, não todos. Agora a
    régua varre a pasta inteira: prompt novo entra na varredura sem ninguém
    precisar lembrar dele."""
    from pathlib import Path

    base = Path("sentury/context/base")
    achados = {}
    for arquivo in sorted(base.glob("*.md")):
        texto = arquivo.read_text(encoding="utf-8")
        hits = sorted({p for p in VOCABULARIO_DE_DOMINIO if re.search(p, texto, re.I)})
        if hits:
            achados[arquivo.name] = hits
    assert achados == {}, achados


def test_a_mensagem_de_bloqueio_nao_manda_chamar_o_que_nao_existe(monkeypatch):
    """Ela citava 16 ferramentas de CX para o generalista, que não tem nenhuma."""
    from sentury.domains import escolha
    from sentury.llm.prompts import build_block_instruction
    from sentury.harness.state import AnalysisState

    monkeypatch.setattr(escolha, "ler", lambda *a, **k: "generalista")
    texto = build_block_instruction("export_csv", [], AnalysisState.new("s", "u"))
    assert "analyze_" not in texto, texto


def test_render_ascii_nao_volta():
    """Ferramenta para algo que o modelo faz sozinho, uma tabela markdown, é mais
    uma opção para escolher sem ganho nenhum."""
    from sentury.tools.registry import TOOL_REGISTRY

    assert "render_ascii" not in TOOL_REGISTRY
