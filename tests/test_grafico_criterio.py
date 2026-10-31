"""A orientação de gráfico explica quando a forma ajuda e quando o dado não sustenta."""
import unicodedata

from sentury.domains.escopo import usar_setor
from sentury.llm.secoes import bloco_de_ferramentas


def _n(t):
    return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode("ascii")


def _persona():
    """A orientação que o modelo recebe quando o gráfico está na mesa."""
    with usar_setor("generalista"):
        return bloco_de_ferramentas(["generate_chart"])


def test_diz_quando_o_grafico_se_paga():
    p = _n(_persona())
    assert "3 ou mais categorias ou periodos" in p


def test_um_ou_dois_numeros_viram_frase():
    """Gráfico de um valor só é enfeite, e enfeite atrapalha quem decide."""
    p = _n(_persona())
    assert "um ou dois numeros cabem numa frase" in p


def test_sai_do_preset_quando_ele_nao_cobre():
    p = _n(_persona())
    assert "o preset nao cobre" in p
    assert "export_html" in p and "executar_python" in p


def test_orienta_a_recusar_com_explicacao_em_vez_de_forcar():
    """Se o dado não sustenta, dizer o número e explicar, em vez de entregar um
    gráfico vazio só porque pediram."""
    p = _n(_persona())
    assert "nao sustenta" in p
    assert "diga o numero e explique" in p
