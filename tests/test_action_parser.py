import json

from sentury.llm.action_parser import extract_plain_text


def test_extract_plain_text_strips_json_action_block():
    raw = "Aqui está sua resposta: " + json.dumps({"action": "tool_call", "tool": "consultar_medida", "arguments": {}})
    texto = extract_plain_text(raw)
    assert "tool_call" not in texto
    assert "consultar_medida" not in texto


def test_extract_plain_text_never_restores_a_bare_tool_action():
    raw = json.dumps({
        "action": "executar_skill",
        "skill": "frontend-design",
        "args": {"contexto": "dashboard"},
    })

    assert extract_plain_text(raw) == ""


def test_extract_plain_text_never_restores_an_empty_respond_envelope():
    assert extract_plain_text(json.dumps({"action": "respond", "message": ""})) == ""


def test_extract_plain_text_keeps_message_from_respond_json():
    raw = json.dumps({"action": "respond", "message": "O Medida geral é 42."})
    texto = extract_plain_text(raw)
    assert texto == "O Medida geral é 42."


def test_extract_plain_text_strips_think_block():
    raw = "<think>pensando...</think>Resposta final ao usuário."
    texto = extract_plain_text(raw)
    assert texto == "Resposta final ao usuário."


def test_resposta_em_ingles_com_passos_chega_inteira():
    """Linha que começa com "Step 1" ou "Plan:" é conteúdo em qualquer língua, não
    rubrica vazada; só as marcas internas do Sentury saem."""
    raw = "Plan:\nStep 1: install the package\nStep 2: run the tests\n[System Notice: interno]"
    texto = extract_plain_text(raw)
    assert "Step 1: install the package" in texto and "Plan:" in texto
    assert "System Notice" not in texto
