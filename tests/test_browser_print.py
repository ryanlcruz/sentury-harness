"""O print da página vai ao modelo como imagem, pelo canal do computador.

Em base64 dentro do resultado, ele chegava como texto: um print do Pinterest
virou 379 mil tokens de letras e a chamada seguinte estourou o limite do modelo.
"""
import base64
import io

from PIL import Image

from sentury.harness.print_da_tela import anexar_print
from sentury.harness.state import AnalysisState
from sentury.tools.browser_registry import _print_como_imagem


def _png(largura=320, altura=200) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (largura, altura), "white").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _resultado(dados, screenshot=True):
    return {"ok": True, "executado": True,
            "observation": {"fonte": "chrome_tab_screenshot", "dados": dados, "epoch": 3,
                            "metadados": {"url": "https://www.pinterest.com", "screenshot": screenshot}}}


def test_o_print_sai_do_resultado_e_vai_para_a_imagem_da_proxima_chamada():
    state = AnalysisState.new("s-nav", "u")
    dados = _png()
    saida = _print_como_imagem(_resultado(dados), state)
    assert dados not in str(saida), "o base64 continua no texto que vai ao modelo"
    assert "anexado como imagem" in saida["observation"]["dados"]
    assert state.print_da_tela == {"data_url": "data:image/png;base64," + dados, "largura": 320, "altura": 200}
    mensagens = anexar_print(state, [{"role": "user", "content": "ache uma imagem"}])
    assert mensagens[-1]["imagens"][0]["data_url"].endswith(dados)


def test_o_ver_do_roteiro_tambem():
    """O roteiro devolve a última observação no mesmo formato."""
    state = AnalysisState.new("s-nav", "u")
    roteiro = {**_resultado(_png(10, 10)), "concluido": False, "feitos": [{"passo": 1, "acao": "navegar"}]}
    saida = _print_como_imagem(roteiro, state)
    assert saida["feitos"] == roteiro["feitos"] and state.print_da_tela["largura"] == 10


def test_leitura_em_texto_fica_como_esta():
    state = AnalysisState.new("s-nav", "u")
    resultado = _resultado({"arvore": []}, screenshot=False)
    assert _print_como_imagem(resultado, state) is resultado
    assert getattr(state, "print_da_tela", None) is None


def test_o_fim_do_turno_apaga_o_print():
    from sentury.tools.computador import encerrar_do_turno

    state = AnalysisState.new("s-nav", "u")
    _print_como_imagem(_resultado(_png()), state)
    encerrar_do_turno(state)
    assert state.print_da_tela is None


def test_o_print_nao_vai_para_a_sessao_salva():
    """Pesado e do turno: fica no estado, fora do que é salvo."""
    state = AnalysisState.new("s-nav", "u")
    assert state.print_da_tela is None
    _print_como_imagem(_resultado(_png()), state)
    assert "print_da_tela" not in state.to_dict()
