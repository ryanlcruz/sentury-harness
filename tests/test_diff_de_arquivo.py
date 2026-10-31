"""O diff de arquivo criado ou editado: vai para a tela, não para o modelo."""
import pytest

from sentury.harness.emissor import EMISSOR
from sentury.harness.processo_do_turno import criar_registrador
from sentury.harness.state import AnalysisState
from sentury.tools import diff_de_arquivo


def test_arquivo_novo_e_so_linha_adicionada():
    diff = diff_de_arquivo.montar("/p/a.py", "", "um\ndois\n", criado=True)
    assert (diff["criado"], diff["adicionadas"], diff["removidas"]) == (True, 2, 0)
    assert diff["trechos"][0]["linhas"] == [["+", "um", None, 1], ["+", "dois", None, 2]]


def test_edicao_mostra_o_trecho_com_as_duas_numeracoes():
    antes = "".join(f"linha {i}\n" for i in range(1, 21))
    depois = antes.replace("linha 10\n", "linha dez\nlinha dez e meia\n")
    diff = diff_de_arquivo.montar("/p/a.txt", antes, depois)
    assert (diff["adicionadas"], diff["removidas"]) == (2, 1)
    [trecho] = diff["trechos"]
    assert trecho["cabecalho"] == "@@ -7,7 +7,8 @@"
    mudadas = [linha for linha in trecho["linhas"] if linha[0] != " "]
    assert mudadas == [["-", "linha 10", 10, None], ["+", "linha dez", None, 10], ["+", "linha dez e meia", None, 11]]
    assert trecho["linhas"][0] == [" ", "linha 7", 7, 7]


def test_diff_grande_corta_mas_conta_tudo(monkeypatch):
    monkeypatch.setattr(diff_de_arquivo, "TETO_DE_LINHAS", 5)
    diff = diff_de_arquivo.montar("/p/a", "", "".join(f"{i}\n" for i in range(50)), criado=True)
    assert diff["cortado"] and diff["adicionadas"] == 50
    assert sum(len(t["linhas"]) for t in diff["trechos"]) == 5


def test_binario_nao_tem_diff():
    assert diff_de_arquivo.montar("/p/a.bin", "", "a\x00b") is None


@pytest.fixture
def trabalho(tmp_path, monkeypatch):
    from sentury.tools import arquivos, permissoes

    raiz = tmp_path / "trabalho"
    raiz.mkdir()
    monkeypatch.setenv("SENTURY_WORKSPACE", str(raiz))
    monkeypatch.setattr(arquivos, "_configuracao", lambda: {})
    permissoes.definir_permitir_tudo(True)
    yield raiz
    permissoes.definir_permitir_tudo(False)


async def test_pelo_execute_tool_a_tela_recebe_e_o_modelo_nao(trabalho):
    from sentury.tools.catalog import execute_tool

    eventos = []
    token = EMISSOR.set(eventos.append)
    try:
        state = AnalysisState.new("diff", "u")
        criado = await execute_tool(None, state, "escrever_arquivo", {"caminho": "a.py", "conteudo": "x = 1\n"})
        editado = await execute_tool(None, state, "editar_arquivo",
                                     {"caminho": "a.py", "antes": "x = 1", "depois": "x = 2"})
    finally:
        EMISSOR.reset(token)
    assert criado["ok"] and "diff_para_a_tela" not in criado and "diff_para_a_tela" not in editado
    diffs = [e for e in eventos if e.get("type") == "diff"]
    assert [(d["ferramenta"], d["criado"], d["adicionadas"], d["removidas"]) for d in diffs] == [
        ("escrever_arquivo", True, 1, 0), ("editar_arquivo", False, 1, 1)]
    assert diffs[1]["arquivo"] == str((trabalho / "a.py").resolve())


def test_o_processo_guarda_o_diff_no_passo_que_escreveu():
    processo = []
    registrar = criar_registrador(processo)
    registrar({"type": "tool_start", "id": "p1", "tool": "escrever_arquivo", "title": "Gravando a.py"})
    registrar({"type": "diff", "ferramenta": "escrever_arquivo", "arquivo": "/p/a.py", "criado": True,
               "adicionadas": 1, "removidas": 0, "trechos": [], "cortado": False})
    registrar({"type": "tool_complete", "id": "p1", "status": "ok"})
    assert processo[0]["diff"]["arquivo"] == "/p/a.py" and processo[0]["status"] == "ok"
