import pytest

from sentury.exec.python_exec import executar_python
from tests.fixtures.setor_teste.dados import StoreTeste


@pytest.fixture(scope="module")
def store() -> StoreTeste:
    return StoreTeste()


async def test_calculo_simples_define_resultado(store, setor_teste):
    r = await executar_python(store, "resultado = len(registros)")
    assert "erro" not in r
    assert r["resultado"] == 2


async def test_sandbox_nao_sobrescreve_codigo_do_projeto(store):
    # Segurança: a LLM pode CRIAR artefatos, mas nunca sobrescrever código nem
    # escapar da pasta do sandbox. Tentar gravar um .py de projeto é bloqueado.
    import os
    tamanho_antes = os.path.getsize("sentury/main.py")
    r = await executar_python(store, "open('sentury/main.py', 'w').write('BROKEN')")
    assert "erro" in r and "não é permitido" in r["erro"]
    assert os.path.getsize("sentury/main.py") == tamanho_antes  # intacto


async def test_sandbox_bloqueia_path_traversal(store):
    r = await executar_python(store, "open('../../evil.txt', 'w').write('x')")
    # A recusa continua; o que mudou foi a frase, que agora diz COMO liberar em
    # vez de so negar. Casar o texto inteiro prende o teste a redacao.
    assert "erro" in r and "fora do espaço liberado" in r["erro"]


async def test_while_legitimo_e_permitido(store):
    # `while` que termina roda.
    r = await executar_python(store, "i=0\nn=0\nwhile i<10:\n    n+=i\n    i+=1\nresultado=n")
    assert "erro" not in r
    assert r["resultado"] == 45


async def test_while_infinito_e_abortado_pelo_teto(store):
    # Loop infinito é cortado pelo guard de iterações (não trava até o timeout).
    r = await executar_python(store, "while True:\n    x = 1")
    assert "erro" in r and "iterações" in r["erro"]


async def test_dataframe_resultado_e_serializado(store, setor_teste):
    r = await executar_python(store, "resultado = registros.groupby('grupo').size().reset_index(name='n')")
    assert r["resultado"]["tipo"] == "tabela"
    assert r["resultado"]["dados"]


async def test_print_e_capturado(store, setor_teste):
    r = await executar_python(store, "print('oi', registros.shape[0])")
    assert r["saida"] and "oi" in r["saida"]


async def test_import_bloqueado(store):
    r = await executar_python(store, "import os\nresultado = 1")
    assert "erro" in r and "import" in r["erro"].lower()


async def test_open_permitido_mas_file_not_found(store):
    r = await executar_python(store, "resultado = open('arquivo_inexistente_x.txt')")
    assert "erro" in r and "FileNotFoundError" in r["erro"]


async def test_dunder_bloqueado(store):
    r = await executar_python(store, "resultado = ().__class__.__bases__")
    assert "erro" in r and "__" in r["erro"]


async def test_sem_resultado_avisa(store):
    r = await executar_python(store, "x = 1 + 1")
    assert "aviso" in r


async def test_erro_de_runtime_volta_como_erro_nao_crash(store):
    r = await executar_python(store, "resultado = registros['coluna_inexistente'].mean()")
    assert "erro" in r


async def test_ascii_table_helper_disponivel_no_sandbox(store):
    r = await executar_python(
        store,
        "resultado = ascii_table(['Grupo', 'Medida'], [['Alfa', -32.5], ['Beta', 12.0]])",
    )
    assert "erro" not in r
    assert "| Grupo " in r["resultado"]
    assert "| Alfa " in r["resultado"]


async def test_plt_is_available_and_callable(store):
    # O import do matplotlib entrega o plt do sandbox; fora da lista continua barrado.
    r_import = await executar_python(store, "import matplotlib.pyplot as plt\nresultado = 1")
    assert "erro" not in r_import
    r_os = await executar_python(store, "import os\nresultado = 1")
    assert "erro" in r_os and "import" in r_os["erro"]

    # Pre-exposed plt should be fully functional without import
    r_plt = await executar_python(
        store,
        "fig, ax = plt.subplots()\nax.plot([1, 2], [3, 4])\nplt.close(fig)\nresultado = 'plot_ok'"
    )
    assert "erro" not in r_plt
    assert r_plt["resultado"] == "plot_ok"


def test_coerce_html_codigo_embrulha_html_cru():
    from sentury.exec.python_exec import _coerce_html_codigo
    # bug real: modelo enfia HTML cru (com 'html' na frente) no `codigo`
    cru = 'html\n<!DOCTYPE html>\n<html><head><title>Medida — Painel</title></head><body><div>x</div></body></html>'
    out = _coerce_html_codigo(cru)
    assert out.startswith("save_html('artefato-sentury.html'")
    # Python legítimo e save_html já existente ficam intactos
    assert _coerce_html_codigo("resultado = registros.shape[0]") == "resultado = registros.shape[0]"
    assert _coerce_html_codigo("save_html('a.html', '<h1>oi</h1>')").startswith("save_html")


async def test_html_cru_no_codigo_nao_quebra_e_gera_artefato(store):
    # o caso do repro (em-dash U+2014 quebrava como "invalid character") agora
    # vira save_html e roda sem erro de sintaxe.
    cru = 'html\n<!DOCTYPE html>\n<html><head><title>Medida — Painel</title></head><body><div class="card"><h1>Medida</h1></div></body></html>'
    r = await executar_python(store, cru)
    assert "erro" not in r

