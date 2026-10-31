"""Navegar codigo: onde algo e definido e quem usa."""
import pytest

from sentury.tools import codigo


@pytest.fixture
def projeto(tmp_path):
    (tmp_path / "core.py").write_text(
        "class Motor:\n"
        "    def ligar(self):\n"
        "        return True\n"
        "\n"
        "def analisar(dados, limite=10):\n"
        '    """Faz a analise."""\n'
        "    return dados\n",
        encoding="utf-8")
    (tmp_path / "uso.py").write_text(
        "from core import analisar\n"
        "resultado = analisar([1])\n"
        "# preencher nao deve casar com 'analisar'\n",
        encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "lixo.py").write_text("def analisar(): pass\n", encoding="utf-8")
    return tmp_path


def test_definicao_distingue_do_uso(projeto):
    """`def analisar` e definicao; `analisar()` numa linha qualquer nao: busca
    textual confundiria as duas."""
    saida = codigo.definicoes("analisar", str(projeto))
    assert saida["total"] == 1
    achado = saida["definicoes"][0]
    assert achado["arquivo"] == "core.py" and achado["tipo"] == "funcao"
    assert achado["assinatura"] == "def analisar(dados, limite)"
    assert achado["doc"] == "Faz a analise."


def test_classe_e_encontrada(projeto):
    saida = codigo.definicoes("Motor", str(projeto))
    assert saida["total"] == 1 and saida["definicoes"][0]["tipo"] == "classe"


def test_referencia_respeita_fronteira_de_palavra(projeto):
    """`analisar` nao pode casar com `reanalisar` nem `analisarei`."""
    saida = codigo.referencias("analisar", str(projeto))
    arquivos = {r["arquivo"] for r in saida["referencias"]}
    assert "uso.py" in arquivos and "core.py" in arquivos
    textos = [r["texto"] for r in saida["referencias"]]
    assert not any("reanalisar" in t or "analisarei" in t for t in textos)


def test_pasta_de_build_e_ignorada(projeto):
    saida = codigo.definicoes("analisar", str(projeto))
    assert not any("__pycache__" in d["arquivo"] for d in saida["definicoes"])


def test_mapa_evita_ler_o_arquivo_inteiro(projeto):
    """Um arquivo de cinco mil linhas nao cabe na conversa; o mapa cabe."""
    saida = codigo.mapa("core.py", str(projeto))
    assert saida["ok"] and saida["linhas"] == 7
    nomes = {i["nome"] for i in saida["itens"]}
    assert nomes == {"Motor", "analisar"}
    motor = next(i for i in saida["itens"] if i["nome"] == "Motor")
    assert [m["nome"] for m in motor["metodos"]] == ["ligar"]


def test_arquivo_quebrado_nao_derruba(projeto):
    (projeto / "quebrado.py").write_text("def (((\n", encoding="utf-8")
    assert codigo.definicoes("analisar", str(projeto))["total"] == 1
    assert not codigo.mapa("quebrado.py", str(projeto))["ok"]


def test_nome_vazio_e_recusado():
    assert not codigo.definicoes("  ")["ok"]
    assert not codigo.referencias("")["ok"]


def test_mapa_passa_pela_mesma_porta_do_ler_arquivo(tmp_path, monkeypatch):
    """Caminho absoluto dentro da pasta de trabalho funciona; fora dela vira o
    pedido de liberar a pasta, e nao um erro cru do Python."""
    from sentury.tools import arquivos

    trabalho = tmp_path / "trabalho"
    fora = tmp_path / "fora"
    trabalho.mkdir()
    fora.mkdir()
    (trabalho / "core.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (fora / "outro.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    monkeypatch.setattr(arquivos, "raiz_de_trabalho", lambda: trabalho)
    monkeypatch.setattr(arquivos, "tudo_liberado", lambda: False)
    monkeypatch.setattr(arquivos, "pastas_extras", lambda: [])

    dentro = codigo.mapa(str(trabalho / "core.py"))
    assert dentro["ok"] and dentro["arquivo"] == "core.py"
    recusado = codigo.mapa(str(fora / "outro.py"))
    assert not recusado["ok"] and recusado.get("precisa_permissao")
