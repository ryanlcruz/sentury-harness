"""`codigo(acao=...)` no lugar de quatro ferramentas de leitura de código.

As antigas saem da mesa do modelo e continuam despachando (traço gravado e
chamada antiga), com a mesma resposta.
"""
import asyncio

import pytest

from sentury.harness.state import AnalysisState
from sentury.tools.catalog import execute_tool
from sentury.tools.registry import ferramentas_do_setor_ativo

FONTE = '''
def montar(x):
    return validar(x)


def validar(x):
    return bool(x)


class Pedido:
    def total(self):
        return montar(1)
'''


@pytest.fixture
def projeto(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    (tmp_path / "pedidos.py").write_text(FONTE, encoding="utf-8")
    return tmp_path


def _rodar(tool, argumentos):
    return asyncio.run(execute_tool(None, AnalysisState("s", "u"), tool, argumentos))


@pytest.mark.parametrize("acao,antiga,argumentos", [
    ("definicao", "onde_definido", {"nome": "validar"}),
    ("referencias", "quem_usa", {"nome": "validar"}),
    ("chamadas", "percorrer_chamadas", {"nome": "validar"}),
])
def test_cada_acao_responde_igual_a_ferramenta_antiga(projeto, acao, antiga, argumentos):
    nova = _rodar("codigo", {"acao": acao, **argumentos})
    assert nova.get("ok") and nova.get("total", 1) >= 1, nova
    assert nova == _rodar(antiga, argumentos)


def test_mapa_le_o_arquivo_como_a_antiga(projeto):
    caminho = str(projeto / "pedidos.py")
    nova = _rodar("codigo", {"acao": "mapa", "caminho": caminho})
    assert "erro" not in nova and "validar" in str(nova), nova
    assert nova == _rodar("mapa_do_arquivo", {"caminho": caminho})


def test_acao_desconhecida_diz_as_validas(projeto):
    resposta = _rodar("codigo", {"acao": "apagar"})
    assert "mapa, definicao, referencias ou chamadas" in resposta["erro"]


def test_so_a_nova_vai_a_mesa():
    na_mesa = set(ferramentas_do_setor_ativo())
    assert "codigo" in na_mesa
    assert not {"mapa_do_arquivo", "onde_definido", "quem_usa", "percorrer_chamadas"} & na_mesa
