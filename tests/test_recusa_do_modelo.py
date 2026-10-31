"""Recusa por política de conteúdo: a resposta diz o que fazer e o turno avisa a troca."""
from robinbandit.chain import FalhaDaCadeia, iniciar_contagem

from sentury.harness.encerramento import (
    RECUSA_DE_CONTEUDO, falha_ao_responder, recusas_do_turno, recusou_por_conteudo,
)


def test_todos_recusaram_pede_para_reformular_e_nao_para_repetir():
    falha = FalhaDaCadeia("todos falharam", ["content_policy", "content_policy"])
    embrulhada = RuntimeError("planner")
    embrulhada.__cause__ = falha
    assert recusou_por_conteudo(embrulhada)
    assert falha_ao_responder(embrulhada) == RECUSA_DE_CONTEUDO


def test_falha_misturada_continua_sendo_falha_comum():
    falha = FalhaDaCadeia("todos falharam", ["content_policy", "rate_limit"])
    assert not recusou_por_conteudo(falha)
    assert "Pode tentar novamente" in falha_ao_responder(falha)


def test_turno_sem_recusa_nao_poe_nada_na_telemetria():
    iniciar_contagem()
    assert recusas_do_turno() is None
