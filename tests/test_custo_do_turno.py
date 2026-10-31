"""O custo do turno é o que o provedor cobrou, quando ele informa."""
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.contabilidade_do_turno import custo_do_turno


def test_o_cobrado_vence_a_estimativa():
    uso = {"entrada": 1000, "saida": 500, "custo_usd": 0.0123}
    assert custo_do_turno("modelo-sem-preco", uso) == 0.0123


def test_sem_cobranca_e_sem_preco_nao_inventa_zero():
    assert custo_do_turno("modelo-sem-preco", {"entrada": 10, "saida": 5}) is None
