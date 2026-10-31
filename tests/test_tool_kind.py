"""O `kind` da acao, fechado dos dois lados.

A interface escolhe o visual pelo tipo da acao (`read`, `execute`, `edit`,
`search`, `other`), nao pelo nome da ferramenta, e assim toda ferramenta aparece
consistente sem tratamento caso a caso. O contrato do client tambem e fechado:
um `kind` novo sem desenho seria percebido so na tela.
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
    """Um enum no client e uma tupla no servidor sao a mesma decisao escrita
    duas vezes. Quando divergem, quem paga e a tela."""
    texto = CONTRATO.read_text(encoding="utf-8")
    achado = re.search(r"ToolKindSchema\s*=\s*z\.enum\(\[([^\]]+)\]\)", texto)
    assert achado, "ToolKindSchema sumiu do contrato"
    no_contrato = set(re.findall(r"'([a-z]+)'", achado.group(1)))

    assert no_contrato == set(SenturyOrchestrator.TOOL_KINDS), (
        f"contrato={sorted(no_contrato)} backend={sorted(SenturyOrchestrator.TOOL_KINDS)}"
    )


def test_contrato_nao_aceita_kind_livre():
    """`z.string().optional()` deixava passar qualquer coisa: era ter o campo
    sem ter o vocabulario."""
    texto = CONTRATO.read_text(encoding="utf-8")
    assert "kind: z.string()" not in texto


def test_toda_ferramenta_do_catalogo_cai_num_kind_conhecido():
    """`_tool_kind` deduz por prefixo do nome. Uma ferramenta nova com prefixo
    imprevisto vira `other` (aceitavel) mas nunca pode virar algo que a tela
    nao sabe desenhar."""
    validos = set(SenturyOrchestrator.TOOL_KINDS)
    for nome in TOOL_REGISTRY:
        assert SenturyOrchestrator._tool_kind(nome) in validos, nome


def test_kind_separa_ler_de_executar(setor_teste):
    """A distincao que da o efeito: leitura mostra so o nome, execucao mostra o
    comando literal. Se as duas caem no mesmo kind, a tela perde a diferenca."""
    assert SenturyOrchestrator._tool_kind("executar_comando") == "execute"
    assert SenturyOrchestrator._tool_kind("buscar_conhecimento") == "search"
    assert SenturyOrchestrator._tool_kind("ler_arquivo") == "read"
    assert SenturyOrchestrator._tool_kind("criar_acao") == "edit"
