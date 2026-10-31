"""O sandbox não grava na pasta de código, e um script que só grava ENTREGA.

Três coisas que o benchmark encostou uma na outra.

**A raiz.** `_SANDBOX_ROOT` era `Path.cwd()`, que é a raiz do repositório quando o
servidor sobe de lá, e ela servia de duas coisas ao mesmo tempo: base para
resolver caminho relativo e base permitida. Então `open('relatorio.md', 'w')`
caía ao lado do código. `_PROTECTED_DIRS` protegia `sentury/`, `tests/`… e não a
raiz.

**O apagar.** O anexo tinha um segundo caminho para o mesmo lugar: quando a lista
rastreada vinha vazia, ele varria `os.getcwd()` por arquivo com menos de dez
segundos, lia os bytes, mandava em base64 e apagava. Era proteção contra sujeira
acumulando na pasta de código: e deixou de fazer sentido quando o sandbox parou
de gravar ali.

**O aviso que engolia a entrega.** Um script que só escrevia o arquivo pedido,
sem `resultado` e sem `print`, caía num ramo que devolvia *"o código rodou mas
não definiu `resultado`"*: e esse ramo não carregava `arquivos_gerados`. A
entrega virava reclamação. Era exatamente a forma da tarefa do benchmark: *"me
entrega isso num arquivo .md"*.
"""
import pathlib

import pytest

from sentury.exec.python_exec import _SANDBOX_ROOT, executar_python

REPO = pathlib.Path(__file__).resolve().parent.parent


# ------------------------------------------------------------ a raiz

def test_a_raiz_do_sandbox_nao_e_a_pasta_de_codigo():
    raiz = pathlib.Path(_SANDBOX_ROOT).resolve()
    assert raiz != REPO, "voltou a gravar na raiz do repositório"
    assert REPO not in raiz.parents or "rascunho" in raiz.parts, raiz


@pytest.mark.asyncio
async def test_caminho_relativo_cai_no_rascunho_e_nao_no_repo():
    nome = "prova_do_teste_de_raiz.md"
    r = await executar_python(None, f"open({nome!r}, 'w', encoding='utf-8').write('x')")
    assert not r.get("erro"), r
    try:
        assert not (REPO / nome).exists(), "gravou na pasta de código"
        assert (pathlib.Path(_SANDBOX_ROOT) / nome).exists(), "não gravou no rascunho"
    finally:
        (pathlib.Path(_SANDBOX_ROOT) / nome).unlink(missing_ok=True)


# ------------------------------------------------- a entrega sobrevive

@pytest.mark.asyncio
async def test_script_que_so_grava_arquivo_entrega_o_arquivo():
    nome = "prova_da_entrega.md"
    r = await executar_python(None, f"open({nome!r}, 'w', encoding='utf-8').write('# oi')")
    try:
        assert not r.get("aviso"), r
        gerados = r.get("arquivos_gerados") or []
        assert any(nome in g for g in gerados), gerados
    finally:
        (pathlib.Path(_SANDBOX_ROOT) / nome).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_script_que_nao_faz_nada_continua_avisando():
    """A regressão a evitar: engolir o aviso junto com o conserto."""
    r = await executar_python(None, "x = 1 + 1")
    assert r.get("aviso"), r


# --------------------------------------------- a varredura de fallback

def test_nao_existe_mais_varredura_de_fallback():
    """A retaguarda varria uma pasta por "modificado nos ultimos 10s". Mesmo
    olhando o rascunho, a janela e do servidor inteiro: duas requisicoes
    concorrentes disputam os mesmos 10 segundos e uma leva o arquivo da outra.
    O contrato e `arquivos_gerados`, que todo escritor registra ao passar pelo
    confinamento."""
    fonte = (pathlib.Path(__file__).resolve().parent.parent
             / "sentury" / "harness" / "anexo_do_resultado.py").read_text(encoding="utf-8")
    assert "now - mtime < 10" not in fonte
    assert "root = Path(os.getcwd())" not in fonte
    assert "_SANDBOX_ROOT" not in fonte


def test_o_artefato_nao_e_mais_apagado():
    fonte = (pathlib.Path(__file__).resolve().parent.parent
             / "sentury" / "harness" / "anexo_do_resultado.py").read_text(encoding="utf-8")
    assert "file_path.unlink()" not in fonte, "voltou a apagar o artefato depois de ler"
