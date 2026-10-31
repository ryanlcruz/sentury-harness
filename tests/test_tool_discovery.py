"""Progressive disclosure: o modelo recebe as candidatas, nao o catalogo.

Mandar todos os schemas na chamada gasta contexto e dilui a escolha: o modelo
recebe so as candidatas que a busca local escolheu.
"""
import pytest

from sentury.llm.tool_schemas import build_tool_schemas
from sentury.tools.capability_catalog import build_catalog, search_catalog
from sentury.tools.registry import TOOL_REGISTRY, do_nucleo, sempre_exposta, ferramentas_do_setor_ativo


def _nomes(schemas):
    return {s["function"]["name"] for s in schemas}


def test_sem_candidatas_vai_o_catalogo_inteiro(setor_teste):
    """Cortar as cegas e pior que nao cortar: sem retrieval que se sustente, o
    modelo precisa do catalogo para nao ficar sem a ferramenta certa."""
    publicas = sum(1 for meta in ferramentas_do_setor_ativo().values() if sempre_exposta(meta))
    assert len(build_tool_schemas(None)) == publicas


def test_candidatas_cortam_o_catalogo(setor_teste):
    schemas = build_tool_schemas({"consultar_medida", "consultar_medida"})
    assert "consultar_medida" in _nomes(schemas)
    assert "consultar_medida" in _nomes(schemas)
    # o resto do catalogo fica de fora
    assert "export_pdf" not in _nomes(schemas)
    assert len(schemas) < len(TOOL_REGISTRY)


def test_nucleo_nunca_sai_da_mesa():
    """O corte por relevancia e um chute informado. Quando ele erra, o modelo
    precisa de caminho de volta: e o caminho de volta e `search_tools`."""
    nomes = _nomes(build_tool_schemas({"consultar_medida"}))
    assert do_nucleo() <= nomes, "tool de nucleo foi cortada"
    assert "search_tools" in nomes
    assert "perguntar_usuario" in nomes


def test_perguntar_usuario_existe_pelos_dois_caminhos():
    """Ela era passo de plano e nao tool declarada: o planner emitia, o
    orquestrador tratava, e em function-calling nativo o modelo nao conseguia
    chama-la. Existia por um caminho e nao pelo outro."""
    assert "perguntar_usuario" in TOOL_REGISTRY
    assert "perguntar_usuario" in _nomes(build_tool_schemas(None))


def test_search_tools_e_a_rede_de_seguranca():
    """Sem ela, cortar para as melhores deixa de ser progressivo e vira parede
    quando a ferramenta certa fica de fora."""
    assert "search_tools" in TOOL_REGISTRY
    assert TOOL_REGISTRY["search_tools"].get("nucleo") is True


def test_pedido_real_corta_de_verdade(setor_teste):
    """O numero e o ponto: se o corte nao economiza, nao vale a complexidade."""
    matches = search_catalog(
        build_catalog(TOOL_REGISTRY, []), "por que o Medida caiu no sudeste?", limit=6
    )
    candidatas = {entry.name for entry, _ in matches if entry.kind == "tool"}
    assert candidatas, "retrieval nao achou nada para um pedido claro"

    enviados = build_tool_schemas(candidatas)
    assert len(enviados) < len(TOOL_REGISTRY) / 2, (
        f"corte fraco: {len(enviados)} de {len(TOOL_REGISTRY) + 1}"
    )


@pytest.mark.parametrize("tool", sorted(do_nucleo()))
def test_tool_de_nucleo_tem_descricao_e_quando_usar(tool):
    """Tool de nucleo entra em toda chamada. Se a descricao nao disser QUANDO
    usar, ela vira ruido em 100% dos turnos."""
    meta = TOOL_REGISTRY[tool]
    assert meta.get("descricao"), tool
    assert meta.get("quando_usar"), tool
