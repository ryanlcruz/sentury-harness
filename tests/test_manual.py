"""O manual do Sentury: o `buscar_conhecimento` tem o que o modelo procura."""
import asyncio

from sentury.harness.state import AnalysisState
from sentury.knowledge.manual import Manual, entradas
from sentury.tools.catalog import execute_tool


def test_detalhe_que_nao_vai_no_prompt_fica_no_manual():
    """A orientação do prompt é curta; o campo `manual` guarda formatos e exemplos."""
    from sentury.llm.secoes import bloco_de_ferramentas
    from sentury.tools.registry import TOOL_REGISTRY

    detalhe = TOOL_REGISTRY["browser"]["manual"]
    navegador = next(e for e in entradas() if e["id"] == "ferramenta:browser")
    assert detalhe.strip() in navegador["texto"]
    assert detalhe.strip() not in bloco_de_ferramentas(["browser"])


def test_uma_entrada_por_ferramenta_e_por_skill_com_o_procedimento():
    todas = entradas()
    ids = {e["id"] for e in todas}
    assert {"ferramenta:executar_comando", "ferramenta:memoria"} <= ids
    skills = [e for e in todas if e["id"].startswith("skill:")]
    # O path do SkillEntry e a pasta: sem ler o SKILL.md a skill entrava so
    # com a descricao de uma linha.
    assert sum(1 for s in skills if len(s["texto"]) > 200) >= len(skills) - 3


def test_acha_o_que_o_modelo_procurou_quando_travou():
    m = Manual()
    achados = [r["id"] for r in m.buscar("como executar comandos git no terminal do sentury")]
    assert "ferramenta:executar_comando" in achados
    diagrama = m.buscar("fazer um diagrama")
    assert diagrama[0]["id"].startswith("skill:") and "diagram" in diagrama[0]["id"]
    assert diagrama[0]["relacionados"], "a skill aponta a ferramenta que a roda"


def test_buscar_conhecimento_traz_o_manual_mesmo_sem_base():
    saida = asyncio.run(execute_tool(None, AnalysisState("s", "u"), "buscar_conhecimento",
                                     {"consulta": "como salvar uma preferencia do usuario"}))
    assert saida and saida[0]["id"] == "ferramenta:memoria"


def test_falha_de_ferramenta_aponta_o_manual():
    from sentury.llm.prompts import build_tool_result_instruction

    texto = build_tool_result_instruction("executar_comando", {"ok": False, "erro": "comando nao encontrado"})
    assert "FALHOU" in texto and "`buscar_conhecimento`" in texto and '"executar_comando"' in texto
    proprio = build_tool_result_instruction("buscar_conhecimento", {"ok": False, "erro": "x"})
    assert "`buscar_conhecimento` com" not in proprio
