from pathlib import Path

CLIENT = Path("sentury/client/src")
NORMALIZADOR = (CLIENT / "domain/artifact-normalizer.ts").read_text(encoding="utf-8")
CHAT_STORE = (CLIENT / "stores/chat-store.ts").read_text(encoding="utf-8")
MARKDOWN = (CLIENT / "domain/markdown.ts").read_text(encoding="utf-8")
BOLHA = (CLIENT / "features/chat/MessageBubble.tsx").read_text(encoding="utf-8")


def test_nenhuma_tabela_vai_sozinha_ao_workbench():
    """A tabela não é promovida no fim do turno: quem decide é a pessoa."""
    assert "tabelaParaArtefato" not in CHAT_STORE
    assert "extractTableArtifacts" not in CHAT_STORE


def test_a_decisao_nao_sai_de_palavras_do_pedido():
    """Ler o pedido atrás de "tabela" ou "relatório" só reconhece português
    escrito certinho; o normalizador nem recebe o pedido."""
    codigo = NORMALIZADOR.split("*/", 1)[1]
    assert "pedido" not in codigo
    for palavra in ("planilha", "relatorio", "exportar"):
        assert palavra not in codigo


def test_cada_tabela_tem_o_botao_de_levar_ao_painel():
    assert "data-tabela-painel" in MARKDOWN
    assert "Abrir no painel" in MARKDOWN
    assert "tabelaParaArtefato" in BOLHA


def test_regra_escrita_acompanha_o_codigo():
    regra = Path("docs/interface/regra-de-artefatos.md").read_text(encoding="utf-8")
    assert "Fica somente na conversa" in regra
    assert "tabela ilustrativa" in regra
    assert "bloco de código" in regra
    assert "Abrir no painel" in regra
