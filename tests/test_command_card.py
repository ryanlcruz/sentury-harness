from pathlib import Path


def test_o_selo_de_linguagem_usa_a_ferramenta_e_nao_o_kind():
    fonte = Path("sentury/client/src/features/chat/CommandCard.tsx").read_text(encoding="utf-8")

    assert "LINGUAGEM[run.tool || '']" in fonte
    assert "LINGUAGEM[run.kind || '']" not in fonte
