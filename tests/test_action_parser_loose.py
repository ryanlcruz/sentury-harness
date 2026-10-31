"""Embrulho de chamada que o modelo vaza no texto (<serpent_tool>, <tool_call>,
<function_call>) não aparece como prosa no chat."""
from sentury.llm.action_parser import extract_plain_text


def test_extract_plain_text_remove_wrapper():
    raw = "Vou puxar os dados.\n<serpent_tool>Tool: consultar_medida</serpent_tool>"
    out = extract_plain_text(raw)
    assert "serpent_tool" not in out and "Tool:" not in out
    assert "Vou puxar os dados" in out
