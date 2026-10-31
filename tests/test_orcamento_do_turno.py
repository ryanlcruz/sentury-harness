"""Computador e navegador alargam o orçamento do turno; o resto fica como está."""
from types import SimpleNamespace

from sentury.harness.loop_budget import LoopBudget, orcamento_do_turno

SETTINGS = SimpleNamespace(SENTURY_MAX_LOOPS=6)


def test_sem_funcao_o_orcamento_e_o_de_sempre():
    assert orcamento_do_turno(SETTINGS, []) == LoopBudget.from_settings(SETTINGS)


def test_o_computador_vai_longe_e_segue_parando_sem_progresso():
    orcamento = orcamento_do_turno(SETTINGS, ["computador"])
    assert orcamento.max_loops == 40 and orcamento.max_tool_calls == 80
    assert orcamento.max_elapsed_ms == 900_000 and isinstance(orcamento.max_loops, int)
    assert orcamento.max_consecutive_no_progress == 4 and orcamento.max_failures == 3


def test_com_duas_funcoes_vale_o_maior_de_cada_limite():
    ambos = orcamento_do_turno(SETTINGS, ["navegador", "computador"])
    assert ambos.max_loops == 40 and ambos.max_elapsed_ms == 900_000
    assert orcamento_do_turno(SETTINGS, ["navegador"]).max_loops == 20


def test_orcamento_nunca_encolhe_o_das_settings():
    grande = SimpleNamespace(SENTURY_MAX_LOOPS=100)
    assert orcamento_do_turno(grande, ["navegador"]).max_loops == 100
