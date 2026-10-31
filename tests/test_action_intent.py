"""Action Intent: o que a acao significa, nao qual funcao rodou.

`kind` escolhe o visual, `title` e legivel para quem le, e `actionType` e
semantico, distinto da ferramenta que executou.

As duas perguntas sao mesmo diferentes, e o catalogo prova nos dois sentidos:
`export_pdf` e `export_xlsx` tem o mesmo kind E a mesma intencao, enquanto
`executar_python` (kind `run`) e `analyze_nps` (kind `read`) executam de formas
opostas com a mesma intencao de medir.
"""
import re
from pathlib import Path

from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.tools.registry import TOOL_REGISTRY

CONTRATO = (
    Path(__file__).resolve().parents[1]
    / "sentury" / "client" / "src" / "contracts" / "events" / "session-events.ts"
)


def test_backend_e_contrato_declaram_o_mesmo_vocabulario():
    texto = CONTRATO.read_text(encoding="utf-8")
    achado = re.search(r"ActionIntentSchema\s*=\s*z\.enum\(\[(.*?)\]\)", texto, re.DOTALL)
    assert achado, "ActionIntentSchema sumiu do contrato"
    no_contrato = set(re.findall(r"'([a-z]+)'", achado.group(1)))

    assert no_contrato == set(SenturyOrchestrator.ACTION_INTENTS), (
        f"contrato={sorted(no_contrato)} backend={sorted(SenturyOrchestrator.ACTION_INTENTS)}"
    )


def test_toda_ferramenta_tem_uma_intencao_conhecida():
    validos = set(SenturyOrchestrator.ACTION_INTENTS)
    for nome in TOOL_REGISTRY:
        assert SenturyOrchestrator._tool_intent(nome) in validos, nome


def test_nenhuma_ferramenta_do_catalogo_fica_sem_intencao():
    """`outro` existe para o que vem de fora (pacote de setor desconhecido).
    Uma ferramenta nativa caindo la significa que a tabela ficou para tras."""
    sem = [t for t in TOOL_REGISTRY if SenturyOrchestrator._tool_intent(t) == "outro"]
    assert not sem, f"sem intencao declarada: {sem}"


def test_a_intencao_nao_e_o_kind():
    """Se intent fosse derivavel do kind, ele nao acrescentaria nada."""
    # Mesmo kind, intencoes diferentes.
    assert SenturyOrchestrator._tool_kind("buscar_conhecimento") == "search"
    assert SenturyOrchestrator._tool_intent("buscar_conhecimento") == "consultar"

    # Kinds diferentes, mesma intencao.
    assert SenturyOrchestrator._tool_kind("buscar_conhecimento") != SenturyOrchestrator._tool_kind("buscar_web")
    assert SenturyOrchestrator._tool_intent("buscar_conhecimento") == SenturyOrchestrator._tool_intent("buscar_web")


def test_o_nome_exato_vence_o_prefixo():
    """O nome exato vence o prefixo. Os casos em que o nome mente
    sobre a intencao cabem numa tabela: e tabela e auditavel, heuristica nao."""
    assert SenturyOrchestrator._tool_intent("consultar_experiencia") == "consultar"


def test_ferramenta_de_setor_herda_pelo_sufixo():
    """`coder.analyze_build` e uma analise, mesmo vindo de um pacote."""
    assert SenturyOrchestrator._tool_intent("coder.analyze_build") == "medir"
    assert SenturyOrchestrator._tool_intent("coder.criar_branch") == "alterar"
    # O que o pacote inventou e que nao casa com nada continua sendo `outro`.
    assert SenturyOrchestrator._tool_intent("coder.build_status") == "outro"


def test_alterar_estado_e_uma_intencao_separada():
    """A pergunta "este turno mudou alguma coisa?" nao se responde com uma
    lista de nomes de funcao: e ela e que decide auditoria e permissao."""
    muda = {t for t in TOOL_REGISTRY if SenturyOrchestrator._tool_intent(t) == "alterar"}
    assert {"escrever_arquivo", "editar_arquivo"} <= muda
    assert "analyze_nps" not in muda
    assert "buscar_conhecimento" not in muda
