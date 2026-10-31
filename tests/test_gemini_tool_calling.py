"""O Gemini passa a falar tool calling nativo: que é o que sustenta tirar o planner.

O caminho nativo já existia no orquestrador (`SENTURY_NATIVE_TOOLS`): quando o
provedor devolve `last_tool_calls`, o plano vem deles e não do parse de texto. Só
que, dos provedores, apenas Groq e Codex aceitavam `tools=`: e o Gemini é quem
serve o Router. Na prática o caminho estava ligado e sem alimentação.

É isso que sustenta o planner com contrato de JSON: sem chamada estruturada, o
modelo precisa **escrever** um plano em JSON dentro do texto, e quando erra o
formato o turno gasta uma chamada de **reparo**. Medido nesta sessão: 221s num
planner que voltou `missing_json`.

Verificado contra a API real antes de escrever este arquivo: `gemini-3.1-flash-lite`
devolveu `texto=''` e
`tool_calls=[{"function": {"name": "listar_arquivos", "arguments": {"caminho": "C:/dados"}}}]`.
"""
from robinbandit.providers.gemini_provider import (
    GeminiProvider,
    _ferramentas_para_gemini,
    _schema_para_gemini,
)

FERRAMENTA = {
    "type": "function",
    "function": {
        "name": "listar_arquivos",
        "description": "lista o que existe numa pasta",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "$schema": "http://json-schema.org/draft-07/schema#",
            "properties": {
                "caminho": {"type": "string", "description": "a pasta", "default": "."},
            },
            "required": ["caminho"],
        },
    },
}


# ------------------------------------------------- a peneira de esquema

def test_tira_o_que_o_gemini_recusa():
    """Uma única chave estranha derruba a requisição inteira com 400: por isso a
    peneira é por lista do que PASSA, não do que sai."""
    limpo = _schema_para_gemini(FERRAMENTA["function"]["parameters"])
    assert "additionalProperties" not in limpo
    assert "$schema" not in limpo
    assert "default" not in limpo["properties"]["caminho"]


def test_mantem_o_que_descreve_o_argumento():
    limpo = _schema_para_gemini(FERRAMENTA["function"]["parameters"])
    assert limpo["type"] == "object"
    assert limpo["required"] == ["caminho"]
    assert limpo["properties"]["caminho"]["description"] == "a pasta"


def test_peneira_desce_em_lista_e_aninhado():
    esquema = {
        "type": "object",
        "title": "fora",
        "properties": {
            "itens": {
                "type": "array",
                "items": {"type": "string", "examples": ["a"]},
            },
        },
    }
    limpo = _schema_para_gemini(esquema)
    assert "title" not in limpo
    assert "examples" not in limpo["properties"]["itens"]["items"]
    assert limpo["properties"]["itens"]["items"]["type"] == "string"


# ------------------------------------------------- a conversão

def test_esquema_openai_vira_function_declarations():
    declaradas = _ferramentas_para_gemini([FERRAMENTA])
    assert declaradas[0]["function_declarations"][0]["name"] == "listar_arquivos"


def test_ferramenta_sem_parametro_vai_sem_a_chave():
    """`parameters: {}` vazio é recusado pela API."""
    sem = {"type": "function", "function": {"name": "agora", "parameters": {"type": "object"}}}
    d = _ferramentas_para_gemini([sem])[0]["function_declarations"][0]
    assert "parameters" not in d


def test_sem_ferramenta_nao_manda_a_chave():
    """Payload com `tools` vazio é diferente de payload sem `tools`."""
    assert _ferramentas_para_gemini([]) is None
    assert _ferramentas_para_gemini(None) is None


def test_entrada_malformada_e_ignorada_sem_quebrar():
    assert _ferramentas_para_gemini([{"nao": "e uma ferramenta"}, None]) is None


# ------------------------------------------------- o payload

def test_o_payload_leva_as_ferramentas():
    p = GeminiProvider(api_key="k", models=["gemini-2.5-flash"])
    payload = p._build_payload([{"role": "user", "content": "oi"}], 0.2, tools=[FERRAMENTA])
    assert payload["tools"][0]["function_declarations"][0]["name"] == "listar_arquivos"


def test_sem_ferramentas_o_payload_fica_como_era():
    p = GeminiProvider(api_key="k", models=["gemini-2.5-flash"])
    assert "tools" not in p._build_payload([{"role": "user", "content": "oi"}], 0.2)


# ------------------------------------------------- a resposta

def test_colhe_function_call_da_resposta():
    dados = {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "listar_arquivos", "args": {"caminho": "C:/dados"}}},
    ]}}]}
    chamadas = GeminiProvider._extract_tool_calls(dados)
    assert chamadas == [{"function": {"name": "listar_arquivos",
                                      "arguments": {"caminho": "C:/dados"}}}]


def test_resposta_so_com_texto_nao_inventa_chamada():
    dados = {"candidates": [{"content": {"parts": [{"text": "oi"}]}}]}
    assert GeminiProvider._extract_tool_calls(dados) == []


def test_a_chamada_vira_plano_do_harness():
    """A ponta final: o formato colhido tem que atravessar o conversor do harness."""
    from sentury.llm.tool_schemas import parse_native_tool_calls

    dados = {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "listar_arquivos", "args": {"caminho": "C:/dados"}}},
    ]}}]}
    calls = parse_native_tool_calls(GeminiProvider._extract_tool_calls(dados))
    assert calls == [{"action": "tool_call", "tool": "listar_arquivos",
                      "arguments": {"caminho": "C:/dados"}}]
