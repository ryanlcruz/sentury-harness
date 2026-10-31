"""As evals de regressao entram na suite: eval que ninguem roda nao protege.

Uma bateria que so roda quando alguem lembra de rodar `python -m sentury.evals`
nao pega regressao: pega depois. Aqui ela roda em todo pytest.
"""
import pytest

from sentury.evals.regressoes import CASOS_DE_REGRESSAO, run_regressoes


async def test_todas_as_regressoes_conhecidas_continuam_corrigidas():
    resultados = await run_regressoes()
    falhas = [f"{r.nome}: {r.detalhe}" for r in resultados if not r.ok]
    assert not falhas, "regressao voltou:\n" + "\n".join(falhas)


def test_cada_caso_de_regressao_explica_o_defeito_que_aconteceu():
    """A regra de entrada: o defeito TEM que ter acontecido.

    Sem o porque escrito, daqui a seis meses ninguem sabe se o caso ainda faz
    sentido: e um eval que ninguem entende e o primeiro a ser apagado quando
    incomoda.
    """
    sem_explicacao = [
        caso.__name__ for caso in CASOS_DE_REGRESSAO
        if not (caso.__doc__ or "").strip() or len((caso.__doc__ or "").strip()) < 60
    ]
    assert not sem_explicacao, f"casos sem o defeito explicado: {sem_explicacao}"
