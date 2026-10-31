"""Os escritores do pandas e do matplotlib obedecem ao mesmo confinamento do `open`.

Eles abrem o arquivo por conta própria. Sem o embrulho, o arquivo cairia na raiz
do repositório ou em qualquer caminho absoluto, e ficaria fora da lista de
gerados que a pessoa recebe.
"""
import pathlib

import pandas as pd
import pytest

from sentury.config import settings
from sentury.exec import python_exec as px

REPO = pathlib.Path(__file__).resolve().parent.parent


def _limpar(*nomes):
    for nome in nomes:
        (pathlib.Path(px._SANDBOX_ROOT) / nome).unlink(missing_ok=True)
        (REPO / nome).unlink(missing_ok=True)


# --------------------------------------- o arquivo cai no rascunho e é entregue

@pytest.mark.asyncio
@pytest.mark.parametrize("codigo,nome", [
    ("pd.DataFrame({'a':[1,2]}).to_csv('t_pd.csv', index=False)", "t_pd.csv"),
    ("pd.DataFrame({'a':[1,2]}).to_excel('t_pd.xlsx', index=False)", "t_pd.xlsx"),
    ("pd.DataFrame({'a':[1]}).to_csv(path_or_buf='t_kw.csv')", "t_kw.csv"),
    ("pd.Series([1,2]).to_csv('t_serie.csv')", "t_serie.csv"),
])
async def test_escritor_do_pandas_cai_no_rascunho(codigo, nome):
    try:
        r = await px.executar_python(None, codigo)
        assert not r.get("erro"), r
        assert not (REPO / nome).exists(), "gravou na raiz do repositório"
        gerados = [pathlib.Path(g).name for g in (r.get("arquivos_gerados") or [])]
        assert nome in gerados, f"não entrou na lista de gerados: {gerados}"
    finally:
        _limpar(nome)


# --------------------------------------- a mesma regra das duas portas

@pytest.mark.asyncio
async def test_pandas_e_open_recusam_o_mesmo_caminho(monkeypatch, tmp_path):
    """O que importa não é o pandas recusar: é recusar EXATAMENTE o que o `open`
    recusa. Duas portas com regras diferentes é um confinamento só pela metade."""
    monkeypatch.setattr(px, "_tudo_liberado", lambda: False)
    alvo = str(tmp_path / "fora_da_area.csv")

    via_open = await px.executar_python(None, f"open({alvo!r}, 'w').write('a')")
    via_pandas = await px.executar_python(None, f"pd.DataFrame({{'a':[1]}}).to_csv({alvo!r})")

    assert via_open.get("erro") and via_pandas.get("erro")
    assert "PermissionError" in via_open["erro"] and "PermissionError" in via_pandas["erro"]
    assert not pathlib.Path(alvo).exists()


@pytest.mark.asyncio
async def test_extensao_perigosa_e_recusada():
    """`to_pickle` grava um formato que executa código ao ser lido de volta e não
    está entre as extensões de artefato."""
    r = await px.executar_python(None, "pd.DataFrame({'a':[1]}).to_pickle('t.pkl')")
    assert r.get("erro"), r
    _limpar("t.pkl")


# --------------------------------------- fora do sandbox, pandas de sempre

def test_fora_do_sandbox_o_pandas_e_o_de_sempre(tmp_path):
    """As ferramentas de export do motor usam pandas legitimamente e não são
    código do modelo: o embrulho só pode agir dentro de uma execução."""
    alvo = tmp_path / "livre.csv"
    pd.DataFrame({"a": [1]}).to_csv(alvo)
    assert alvo.exists()


def test_o_embrulho_nao_se_aplica_duas_vezes():
    """Reimportar o módulo não pode embrulhar o embrulho."""
    px._confinar_escritores_do_pandas()
    px._confinar_escritores_do_pandas()
    assert getattr(pd.DataFrame.to_csv, "_sentury_confinado", False)
    assert pd.DataFrame.to_csv.__name__ == "to_csv"


# --------------------------------------- matplotlib

@pytest.mark.asyncio
@pytest.mark.parametrize("codigo", [
    "import matplotlib.pyplot as plt\nplt.bar(['a', 'b', 'c'], [1, 2, 3])\nplt.savefig('t_mpl.png')",
    "from matplotlib import pyplot as p\nfig, ax = p.subplots()\nax.plot([1, 2])\nfig.savefig('t_mpl.png')",
])
async def test_grafico_com_import_cai_no_rascunho_uma_vez(monkeypatch, codigo):
    """O import do matplotlib entrega o `plt` do sandbox, e a imagem entra uma vez na lista."""
    monkeypatch.setattr(settings, "SENTURY_PY_CHILD", False)
    try:
        r = await px.executar_python(None, codigo)
        assert not r.get("erro"), r
        gerados = [pathlib.Path(g).name for g in (r.get("arquivos_gerados") or [])]
        assert gerados == ["t_mpl.png"]
        assert not (REPO / "t_mpl.png").exists()
    finally:
        _limpar("t_mpl.png")


@pytest.mark.asyncio
@pytest.mark.parametrize("gravar", [
    "plt.gcf().savefig({alvo!r})",
    "plt.gcf().canvas.print_png({alvo!r})",
    "plt.imsave({alvo!r}, np.zeros((2, 2)))",
])
async def test_matplotlib_recusa_o_que_o_open_recusa(monkeypatch, tmp_path, gravar):
    """Toda porta de gravação do matplotlib passa pelo mesmo confinamento."""
    monkeypatch.setattr(settings, "SENTURY_PY_CHILD", False)
    monkeypatch.setattr(px, "_tudo_liberado", lambda: False)
    alvo = str(tmp_path / "fora.png")
    r = await px.executar_python(None, "plt.plot([1, 2])\n" + gravar.format(alvo=alvo))
    assert "PermissionError" in str(r.get("erro")), r
    assert not pathlib.Path(alvo).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("codigo", ["from matplotlib import animation", "import matplotlib.animation"])
async def test_animacao_do_matplotlib_fica_fora(monkeypatch, codigo):
    """O gravador de vídeo do matplotlib roda processo."""
    monkeypatch.setattr(settings, "SENTURY_PY_CHILD", False)
    r = await px.executar_python(None, codigo)
    assert r.get("erro"), r


def test_fora_do_sandbox_o_matplotlib_e_o_de_sempre(tmp_path):
    """O motor também desenha gráfico; o embrulho só age dentro de uma execução."""
    import matplotlib.pyplot as plt

    alvo = tmp_path / "livre.png"
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    fig.savefig(alvo)
    plt.close(fig)
    assert alvo.exists()
