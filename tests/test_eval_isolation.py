import pytest

from sentury.domains.escopo import setor_do_contexto, usar_setor
from sentury.domains.escolha import GENERALISTA
from sentury.domains.registry import get_active_domain
from sentury.evals import golden


async def _rodar(caso):
    with usar_setor("setor_teste"):
        return await caso()


def test_escopo_de_setor_restaura_a_escolha_da_instalacao(monkeypatch):
    monkeypatch.setattr("sentury.domains.escolha.ler", lambda: GENERALISTA)
    assert setor_do_contexto() is None
    assert get_active_domain().name == GENERALISTA
    with usar_setor("setor_teste"):
        assert get_active_domain().name == "setor_teste"
    assert setor_do_contexto() is None
    assert get_active_domain().name == GENERALISTA


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "caso",
    [
        golden._eval_root_cause_global,
        golden._eval_export_pdf_deterministico,
        golden._eval_grounding_sem_moeda,
        golden._eval_memoria_aprende_e_recupera,
    ],
)
async def test_cada_golden_passa_sozinha_no_seu_escopo(caso):
    resultado = await _rodar(caso)
    assert resultado.ok, resultado.detalhe


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ordem",
    [
        (golden._eval_root_cause_global, golden._eval_export_pdf_deterministico),
        (golden._eval_export_pdf_deterministico, golden._eval_root_cause_global),
    ],
)
async def test_goldens_passam_em_duas_ordens(ordem):
    for caso in ordem:
        resultado = await _rodar(caso)
        assert resultado.ok, resultado.detalhe
