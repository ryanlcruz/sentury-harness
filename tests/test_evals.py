from sentury.evals.golden import run_golden_evals


async def test_all_golden_evals_pass():
    resultados = await run_golden_evals()
    falhas = [f"{r.nome}: {r.detalhe}" for r in resultados if not r.ok]
    assert not falhas, "evals golden falharam:\n" + "\n".join(falhas)
    assert len(resultados) >= 4
