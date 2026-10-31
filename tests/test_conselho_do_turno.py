"""O conselho só roda sobre dado de verdade, e quem diz isso é a estrutura do
resultado, não frases como "nenhum dado", que mudam de língua e de redação."""
import pytest

from sentury.harness.conselho_do_turno import tem_dado_para_o_conselho


def _de(resultado):
    return [{"tool": "analise", "result": resultado}]


@pytest.mark.parametrize("vazio", [
    [], {}, None, "", "   ", {"itens": [], "total": None}, {"grupos": {"a": [], "b": None}}, [[], {}],
])
def test_casca_vazia_nao_chama_o_conselho(vazio):
    assert tem_dado_para_o_conselho(_de(vazio)) is False


@pytest.mark.parametrize("cheio", [
    [{"segmento": "a", "valor": 3}], {"total": 0}, {"itens": [], "media": 7.5}, "uma linha de achado",
])
def test_dado_de_verdade_chama_o_conselho(cheio):
    assert tem_dado_para_o_conselho(_de(cheio)) is True


def test_resultado_que_falhou_nao_conta_mesmo_com_conteudo():
    assert tem_dado_para_o_conselho(_de({"erro": "a consulta estourou o tempo"})) is False
