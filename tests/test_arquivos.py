"""Guardas de leitura e escrita de arquivo."""
import pytest

from sentury.tools import arquivos, permissoes


@pytest.fixture
def espaco(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    (tmp_path / "core.py").write_text("VALOR = 1\nOUTRO = 2\n", encoding="utf-8")
    (tmp_path / ".env").write_text("GROQ_API_KEY=sk-segredo\n", encoding="utf-8")
    yield tmp_path


@pytest.fixture(autouse=True)
def _liberado(monkeypatch):
    """Escrita autorizada: a permissao tem os proprios testes."""
    monkeypatch.setattr(permissoes, "avaliar",
                        lambda *a, **k: {"permitido": True, "precisa_perguntar": False,
                                         "chave": "x", "motivo": "teste"})
    yield


def test_le_arquivo_e_avisa_quando_truncou(espaco):
    (espaco / "grande.txt").write_text("\n".join(f"linha {i}" for i in range(5000)), encoding="utf-8")
    saida = arquivos.ler("grande.txt")
    assert saida["ok"] and saida["truncado"], "leu tudo sem avisar que sobrou"
    assert saida["linhas_totais"] == 5000 and saida["ultima_linha"] < 5000

    trecho = arquivos.ler("grande.txt", inicio=10, linhas=3)
    assert trecho["primeira_linha"] == 10 and trecho["conteudo"].startswith("linha 9")


def test_ler_segredo_e_tao_grave_quanto_escrever(espaco):
    """Ler .env despeja as chaves na conversa."""
    saida = arquivos.ler(".env")
    assert not saida["ok"]
    assert "sk-segredo" not in str(saida)


def test_caminho_que_sobe_e_recusado(espaco):
    for fora in ("../fora.txt", "a/../../etc/passwd"):
        assert not arquivos.ler(fora)["ok"]
        assert not arquivos.escrever(fora, "x")["ok"]


def test_escrever_cria_e_substitui(espaco):
    novo = arquivos.escrever("sub/novo.py", "print(1)\n")
    assert novo["ok"] and novo["criado"]
    assert (espaco / "sub" / "novo.py").read_text(encoding="utf-8") == "print(1)\n"

    de_novo = arquivos.escrever("sub/novo.py", "print(2)\n")
    assert de_novo["ok"] and not de_novo["criado"] and de_novo["linhas_antes"] == 1


def test_editar_exige_o_texto_exato_de_antes(espaco):
    """Garante que ele viu o arquivo como esta agora."""
    errado = arquivos.editar("core.py", "VALOR = 99", "VALOR = 3")
    assert not errado["ok"] and "nao encontrei" in errado["erro"]

    certo = arquivos.editar("core.py", "VALOR = 1", "VALOR = 3")
    assert certo["ok"]
    assert (espaco / "core.py").read_text(encoding="utf-8") == "VALOR = 3\nOUTRO = 2\n"


def test_trecho_ambiguo_para_em_vez_de_chutar(espaco):

    (espaco / "rep.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    ambiguo = arquivos.editar("rep.py", "x = 1", "x = 2")
    assert not ambiguo["ok"] and "2 vezes" in ambiguo["erro"]

    todas = arquivos.editar("rep.py", "x = 1", "x = 2", todas=True)
    assert todas["ok"] and todas["substituicoes"] == 2


def test_editar_recusa_troca_vazia_ou_igual(espaco):
    assert not arquivos.editar("core.py", "", "algo")["ok"]
    assert not arquivos.editar("core.py", "VALOR = 1", "VALOR = 1")["ok"]


def test_listar_ignora_ruido_de_build(espaco):
    (espaco / "__pycache__").mkdir()
    (espaco / "node_modules").mkdir()
    nomes = {i["nome"] for i in arquivos.listar(".")["itens"]}
    assert "core.py" in nomes
    assert "__pycache__" not in nomes and "node_modules" not in nomes


def test_padrao_sem_resultado_diz_que_a_pasta_tem_itens(espaco):
    """Zero com filtro não é pasta vazia: a nota diz o que existe sem filtro."""
    saida = arquivos.listar(".", padrao="*relatorio*")
    assert saida["ok"] and saida["total"] == 0
    assert "*relatorio*" in saida["nota"] and "core.py" in saida["nota"]

    assert "nota" not in arquivos.listar(".", padrao="*.py")


def test_escrita_pede_autorizacao_de_verdade(espaco, monkeypatch):
    """A permissao real vale aqui."""
    monkeypatch.undo()
    monkeypatch.setenv("SENTURY_WORKSPACE", str(espaco))
    sessao = "sess-arquivo"
    permissoes.limpar_sessao(sessao)
    permissoes.esquecer("escrever_arquivo")
    try:
        saida = arquivos.escrever("novo.txt", "conteudo", session_id=sessao)
        assert saida.get("precisa_permissao") and not saida["ok"]
        assert not (espaco / "novo.txt").exists(), "escreveu antes de perguntar"
    finally:
        permissoes.limpar_sessao(sessao)
        permissoes.esquecer("escrever_arquivo")


def test_planilha_vira_tabela_legivel(espaco, monkeypatch):
    """Um agente de analise que nao le planilha nem PDF fica de fora de onde o
    dado costuma estar."""
    from openpyxl import Workbook

    from sentury.tools import arquivos

    wb = Workbook()
    ws = wb.active
    ws.append(["regiao", "nps"])
    ws.append(["Sudeste", -49.3])
    wb.save(espaco / "dados.xlsx")

    saida = arquivos.ler("dados.xlsx")
    assert saida["ok"] and saida["convertido"]
    assert "Sudeste" in saida["conteudo"] and "-49.3" in saida["conteudo"]


def test_texto_comum_nao_e_marcado_como_convertido(espaco):
    from sentury.tools import arquivos

    saida = arquivos.ler("core.py")
    assert saida["ok"] and saida["convertido"] is False


def test_documento_ilegivel_diz_que_nao_conseguiu(espaco):
    """Melhor recusar que devolver lixo binario como se fosse texto."""
    from sentury.tools import arquivos

    (espaco / "falso.pdf").write_bytes(bytes(range(256)) * 40)
    saida = arquivos.ler("falso.pdf")
    assert not saida["ok"] and "extrair texto" in saida["erro"]
