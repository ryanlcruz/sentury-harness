"""`memoria(acao=...)` no lugar de tres ferramentas.

As antigas saem da mesa do modelo e continuam despachando (traco gravado e
chamada antiga).
"""
import asyncio

from sentury.harness.state import AnalysisState
from sentury.tools.catalog import execute_tool
from sentury.tools.registry import TOOL_REGISTRY, ferramentas_do_setor_ativo


class _Memoria:
    def __init__(self):
        self.fatos = []

    async def remember(self, user_id, fato, sessao=None):
        self.fatos.append(fato)
        return True

    async def all(self, user_id):
        return list(self.fatos)

    async def forget(self, user_id, termo):
        antes = len(self.fatos)
        self.fatos = [f for f in self.fatos if termo and termo not in f]
        return antes - len(self.fatos)


def _rodar(memoria, argumentos, tool="memoria"):
    return asyncio.run(execute_tool(None, AnalysisState("s", "u"), tool, argumentos, memory=memoria))


def test_as_tres_acoes_chegam_na_memoria():
    m = _Memoria()
    assert _rodar(m, {"acao": "salvar", "fato": "prefiro respostas curtas"})["status"] == "salvo"
    assert _rodar(m, {"acao": "listar"}) == ["prefiro respostas curtas"]
    assert _rodar(m, {"acao": "esquecer", "termo": "curtas"})["removidos"] == 1
    assert "erro" in _rodar(m, {"acao": "apagar_tudo"})


def test_so_a_nova_vai_a_mesa_e_as_antigas_ainda_despacham():
    na_mesa = ferramentas_do_setor_ativo()
    assert "memoria" in na_mesa
    assert not {"salvar_memoria", "listar_memorias", "esquecer_memoria"} & set(na_mesa)
    assert "salvar_memoria" in TOOL_REGISTRY
    m = _Memoria()
    assert _rodar(m, {"fato": "x"}, tool="salvar_memoria")["status"] == "salvo"
