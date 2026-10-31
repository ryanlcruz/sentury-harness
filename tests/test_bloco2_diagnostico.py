"""Ler o erro antes de rodar o teste, e ver a cadeia antes de alterar.

`diagnosticos` e leitura de primeira classe: a suite leva minutos e o teste que
falha raramente aponta a linha, enquanto sintaxe quebrada e import inexistente
aparecem em milissegundos.

`percorrer_chamadas` responde o que `onde_definido` e `quem_usa` nao
respondem: a cadeia, que e o que decide se mexer e seguro.
"""
from pathlib import Path

import pytest

from sentury.tools import codigo
from sentury.tools.diagnostico import de_muitos, do_arquivo


# ------------------------------------------------------------- diagnostico

def test_sintaxe_quebrada_e_erro(tmp_path):
    (tmp_path / "x.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    r = do_arquivo("x.py", str(tmp_path))
    assert r["erros"] == 1
    assert r["achados"][0]["origem"] == "sintaxe"
    assert r["achados"][0]["linha"] > 0


def test_com_a_arvore_quebrada_nada_mais_e_analisado(tmp_path):
    """Analisar nome e import numa arvore que nao parseia seria chute."""
    (tmp_path / "x.py").write_text("def f(:\n    return coisa_solta\n", encoding="utf-8")
    r = do_arquivo("x.py", str(tmp_path))
    assert len(r["achados"]) == 1


def test_import_relativo_inexistente_e_erro(tmp_path):
    (tmp_path / "x.py").write_text("from .naoexiste import coisa\n", encoding="utf-8")
    r = do_arquivo("x.py", str(tmp_path))
    assert r["erros"] == 1
    assert r["achados"][0]["origem"] == "import"


def test_import_absoluto_nao_e_acusado(tmp_path):
    """Ele depende do ambiente instalado; checar daria falso positivo a cada
    pacote que existe no venv e nao no repositorio."""
    (tmp_path / "x.py").write_text("import pandas\nimport nao_instalado_nenhum\n", encoding="utf-8")
    assert do_arquivo("x.py", str(tmp_path))["erros"] == 0


def test_nome_solto_e_aviso_nao_erro(tmp_path):
    """A analise de escopo aqui e rasa de proposito: falso positivo custaria
    mais que o achado, entao o nome solto avisa e nao acusa."""
    (tmp_path / "x.py").write_text("def f():\n    return nunca_definido\n", encoding="utf-8")
    r = do_arquivo("x.py", str(tmp_path))
    assert r["erros"] == 0 and r["avisos"] == 1
    assert r["achados"][0]["gravidade"] == "aviso"


@pytest.mark.parametrize("fonte", [
    "import json\n\ndef f(a, b=2):\n    return json.dumps({'x': a + b})\n",
    "def f(*args, **kw):\n    return [x for x in args if x]\n",
    "try:\n    pass\nexcept ValueError as exc:\n    print(exc)\n",
    "def f():\n    global contador\n    contador = 1\n    return contador\n",
    "class C:\n    def m(self):\n        return self\n",
])
def test_codigo_limpo_nao_gera_achado(tmp_path, fonte):
    (tmp_path / "x.py").write_text(fonte, encoding="utf-8")
    r = do_arquivo("x.py", str(tmp_path))
    assert r["achados"] == [], r["achados"]


def test_builtin_nao_e_nome_solto(tmp_path):
    """`dir(__builtins__)` num modulo importado devolve os metodos do dict, e
    `ValueError`, `str` e `tuple` viravam falso positivo. O modulo `builtins` e
    a lista de verdade."""
    (tmp_path / "x.py").write_text(
        "def f(v):\n"
        "    if not isinstance(v, (str, tuple)):\n"
        "        raise ValueError(str(len(v)))\n"
        "    return sorted(set(v))\n",
        encoding="utf-8",
    )
    assert do_arquivo("x.py", str(tmp_path))["achados"] == []


def test_o_proprio_projeto_esta_limpo():
    """Se a ferramenta acusa o codigo que ela mesma vive dentro, ela nao serve."""
    for alvo in (
        "sentury/harness/orchestrator.py",
        "sentury/memory/plano.py",
        "sentury/tools/diagnostico.py",
        "sentury/tools/codigo.py",
    ):
        r = do_arquivo(alvo, ".")
        assert r["achados"] == [], (alvo, r["achados"][:3])


def test_arquivo_que_nao_e_python_diz_o_que_fazer(tmp_path):
    (tmp_path / "x.ts").write_text("const a = 1;\n", encoding="utf-8")
    r = do_arquivo("x.ts", str(tmp_path))
    assert r["ok"] and r["achados"] == []
    assert "terminal" in r["nota"]


def test_muitos_arquivos_de_uma_vez(tmp_path):
    """O conjunto que uma alteracao tocou, numa chamada."""
    (tmp_path / "a.py").write_text("def f(:\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
    r = de_muitos(["a.py", "b.py", "nao-existe.py"], str(tmp_path))
    assert r["erros"] == 1
    assert "nao-existe.py" in r["nao_lidos"]


# ------------------------------------------------------- percorrer chamadas

def test_percorre_nos_dois_sentidos():
    subindo = codigo.percorrer("_tool_intent", ".", sentido="chamado_por")
    assert subindo["ok"]
    # Quem chama `_tool_intent` é o executor do passo do turno.
    assert "executar" in [x["nome"] for x in subindo["niveis"][0]]

    descendo = codigo.percorrer("_tool_intent", ".", sentido="chama")
    assert descendo["ok"]


def test_teste_nao_entra_na_cadeia():
    """Teste que exercita a funcao nao e quem depende dela: nao quebra o
    produto, e listado junto afoga o chamador que importa. "Quem chama
    `marcar`?" devolvia onze linhas, dez delas `test_*`."""
    r = codigo.percorrer("marcar", ".", sentido="chamado_por")
    nomes = [x["nome"] for nivel in r["niveis"] for x in nivel]
    assert nomes, "nao achou chamador nenhum"
    assert not [n for n in nomes if n.startswith("test_")]


def test_profundidade_tem_teto():
    """Tres niveis num projeto deste tamanho devolvem meio grafo: e meio
    grafo nao e navegacao, e outro monolito para o modelo ler."""
    r = codigo.percorrer("_tool_intent", ".", sentido="chamado_por", profundidade=99)
    assert len(r["niveis"]) <= 3


def test_nome_que_nao_e_funcao_do_projeto_falha_alto():
    r = codigo.percorrer("nao_existe_em_lugar_nenhum", ".")
    assert r["ok"] is False


def test_sentido_invalido_e_recusado():
    assert codigo.percorrer("marcar", ".", sentido="pra_cima")["ok"] is False


def test_pastas_de_terceiro_ficam_fora():
    """Codigo clonado para estudo nao e o projeto: eram 7.375 dos 7.771
    arquivos Python, e navegar sobre eles gasta o turno respondendo sobre o
    repositorio de outra pessoa."""
    arquivos = codigo._arquivos(Path(".").resolve(), (".py",))
    assert arquivos, "nao achou arquivo nenhum"
    assert len(arquivos) < 1500, f"{len(arquivos)} arquivos: a poda parou de funcionar"
    for proibida in ("referencia", ".venv", "node_modules", "__pycache__"):
        assert not [a for a in arquivos if proibida in a.parts], proibida


def test_o_grafo_fica_em_cache():
    """Sem cache, duas perguntas seguidas sobre o mesmo codigo pagam a
    varredura duas vezes: e aqui ela levava setenta segundos."""
    codigo._CACHE_DO_GRAFO.update(chave=None, grafo=None)
    codigo.percorrer("marcar", ".")
    primeira = codigo._CACHE_DO_GRAFO["grafo"]
    codigo.percorrer("resolver", ".")
    assert codigo._CACHE_DO_GRAFO["grafo"] is primeira
