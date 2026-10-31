"""Orientação longa no meio do turno: o corte aparece no texto."""
from sentury.harness import caixa_do_turno, turno_em_curso


def test_orientacao_longa_avisa_que_foi_cortada(monkeypatch):
    monkeypatch.setattr(turno_em_curso, "em_curso", lambda sessao: True)
    recebida = caixa_do_turno.receber("s-corte", "a" * (caixa_do_turno.TETO_DE_TEXTO + 50))
    assert recebida is not None
    assert recebida.texto.endswith("foi cortada aqui]")
    assert recebida.texto.startswith("a" * caixa_do_turno.TETO_DE_TEXTO)
