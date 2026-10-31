"""O que vai ao modelo no passo unico: so o essencial.

A orientacao de cada ferramenta vai na descricao dela, e so das oferecidas na
chamada. Orientacao de catalogo inteiro e contrato de JSON no texto fazem o
modelo escrever a chamada em vez de chamar.
"""
from sentury.harness import passo_unico
from sentury.harness.orchestrator import PLANNER_SYSTEM_PROMPT, _prompt_do_planejador
from sentury.llm.tool_schemas import build_tool_schemas
from sentury.tools.registry import TOOL_REGISTRY


def test_passo_unico_nao_recebe_o_contrato_de_json():
    base = passo_unico.base_do_passo(PLANNER_SYSTEM_PROMPT)
    assert "APENAS com um objeto JSON" not in base
    assert "Sentury Planner" not in base
    assert "Como agir neste turno" in base
    # As regras continuam.
    assert "### Preferências e memória" in base
    assert "### Quando perguntar" in base


def test_orientacao_vai_na_ferramenta_oferecida_e_nao_no_sistema():
    sistema = _prompt_do_planejador(com_ferramentas=False)
    assert "QUANDO USAR CADA FERRAMENTA" not in sistema
    assert "QUANDO USAR CADA FERRAMENTA" in _prompt_do_planejador()

    esquema = build_tool_schemas({"ler_arquivo"}, com_orientacao=True)
    ler = next(e for e in esquema if e["function"]["name"] == "ler_arquivo")
    assert TOOL_REGISTRY["ler_arquivo"]["orientacao"].strip()[:40] in ler["function"]["description"]
    sem = next(e for e in build_tool_schemas({"ler_arquivo"}) if e["function"]["name"] == "ler_arquivo")
    assert sem["function"]["description"] == TOOL_REGISTRY["ler_arquivo"]["descricao"]
