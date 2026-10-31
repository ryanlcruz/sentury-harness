"""O contrato de fonte de dados é o que o motor usa, e nada de setor.

Ele declarava sete consultas de CX (`get_feedbacks`, `get_tickets`...), e o
teste antigo cobrava que todo método do store de CX estivesse no contrato: o
contrato crescia junto com o setor. Agora é o contrário: o motor usa a conexão
SQL de leitura e a fila do Tasks, e o que o pacote tem a mais é dele.
"""
import inspect

from sentury.data.store import DATA_BACKENDS, DataSource, SemDados
from tests.fixtures.setor_teste.dados import StoreTeste


def _metodos_do_contrato() -> set:
    attrs = getattr(DataSource, "__protocol_attrs__", None)
    if attrs:
        return {n for n in attrs if not n.startswith("_")}
    return {n for n, _ in inspect.getmembers(DataSource, inspect.isfunction) if not n.startswith("_")}


def test_as_duas_fontes_de_fabrica_cumprem_o_contrato():
    assert isinstance(SemDados(), DataSource)
    assert issubclass(StoreTeste, DataSource)


def test_o_contrato_nao_tem_consulta_de_setor():
    """Consulta de setor no contrato obriga toda fonte nova a fingir ser o setor."""
    assert not {n for n in _metodos_do_contrato() if n.startswith("get_") and n != "get_sqlite_conn"}


def test_o_registro_de_backend_continua_sendo_a_porta():
    assert "memory" in DATA_BACKENDS
