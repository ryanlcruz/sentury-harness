"""Testa a fundação de function-calling nativo."""
from sentury.llm.tool_schemas import build_tool_schemas, parse_native_tool_calls
from sentury.tools.registry import TOOL_REGISTRY, sempre_exposta, ferramentas_do_setor_ativo


def test_build_gera_todas_no_formato_openai(setor_teste):
    # Só o catálogo público: nenhuma ferramenta mora fora do registro.
    schemas = build_tool_schemas()
    publicas = sum(1 for meta in ferramentas_do_setor_ativo().values() if sempre_exposta(meta))
    assert len(schemas) == publicas
    s = schemas[0]
    assert s["type"] == "function"
    assert s["function"]["name"] in TOOL_REGISTRY
    assert s["function"]["parameters"]["type"] == "object"


def test_tools_legadas_nao_sao_oferecidas_ao_modelo():
    nomes = {s["function"]["name"] for s in build_tool_schemas()}
    assert {"save_analysis", "pesquisar_web"}.isdisjoint(nomes)


def test_buscar_web_declara_profundidade_sem_outra_tool():
    schema = next(
        s["function"] for s in build_tool_schemas()
        if s["function"]["name"] == "buscar_web"
    )
    paginas = schema["parameters"]["properties"]["paginas"]
    profundidade = schema["parameters"]["properties"]["profundidade"]
    limite = schema["parameters"]["properties"]["limite"]
    assert profundidade["enum"] == ["rapida", "profunda"]
    assert limite["maximum"] == 20
    assert paginas["minimum"] == 0 and paginas["maximum"] == 10


def test_build_filtra_por_names(setor_teste):
    """`names` restringe: mas o nucleo vem junto, sempre.

    Cortar para as candidatas do retrieval e um chute informado. Quando ele
    erra, `search_tools` e o caminho de volta; sem ela na mesa, o corte vira
    beco sem saida em vez de uma busca a mais.
    """
    from sentury.tools.registry import do_nucleo

    schemas = build_tool_schemas(names={"consultar_medida"})
    nomes = {s["function"]["name"] for s in schemas}

    assert "consultar_medida" in nomes
    assert do_nucleo() <= nomes
    assert nomes == {"consultar_medida"} | do_nucleo(), "entrou tool que ninguem pediu"


def test_parse_tool_calls_args_json_string():
    tcs = [{"function": {"name": "consultar_medida", "arguments": '{"grupo": "Alfa"}'}}]
    out = parse_native_tool_calls(tcs)
    assert out == [{"action": "tool_call", "tool": "consultar_medida", "arguments": {"grupo": "Alfa"}}]


def test_parse_tool_calls_args_dict_e_vazio():
    tcs = [
        {"function": {"name": "consultar_medida", "arguments": {}}},
        {"function": {"name": "consultar_medida", "arguments": "nao-e-json"}},
    ]
    out = parse_native_tool_calls(tcs)
    assert out[0]["tool"] == "consultar_medida" and out[0]["arguments"] == {}
    assert out[1]["tool"] == "consultar_medida" and out[1]["arguments"] == {}


def test_parse_ignora_sem_nome():
    assert parse_native_tool_calls([{"function": {"arguments": "{}"}}]) == []
    assert parse_native_tool_calls(None) == []
