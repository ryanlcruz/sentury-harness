"""O que é de um setor só (o rótulo de um ponto, a região de uma ação, o tamanho da
base de exemplo) não mora no motor: ele lê do pacote ou não sabe."""
import importlib
from types import SimpleNamespace


def _modulo_da_base():
    return importlib.import_module("sentury.domains.setores.setor_teste.dados.store")


def test_o_pacote_abre_a_propria_base(setor_teste, monkeypatch):
    from sentury.data import store

    aberta = object()
    monkeypatch.setattr(_modulo_da_base(), "abrir", lambda st: aberta, raising=False)
    assert store._base_do_setor(SimpleNamespace()) is aberta


def test_sem_abrir_a_base_sobe_sem_configuracao_do_motor(setor_teste):
    from sentury.data import store

    assert isinstance(store._base_do_setor(SimpleNamespace()), _modulo_da_base().StoreTeste)


def test_o_rotulo_do_ponto_vem_dos_campos_do_ponto():
    from sentury.renderers.chart import _pontos_correlate

    rotulos, x, y = _pontos_correlate([{"grupo": "Alfa", "semana": "S1", "metric_a_valor": 1, "metric_b_valor": 2.5}])
    assert (rotulos, x, y) == (["Alfa/S1"], [1.0], [2.5])


def test_plano_enviado_para_tarefas_nao_tem_campo_de_setor():
    from sentury.main import AcaoFromPlanRequest

    assert set(AcaoFromPlanRequest.model_fields) == {"markdown", "title"}
