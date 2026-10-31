"""Extensões recebem dados e sessão pelo contexto do pacote."""
import asyncio
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from sentury.domains.extensao import (
    ContextoDoPacote,
    _aceita_contexto,
    carregar,
    esquecer,
    executar,
    publicadas,
)

@pytest.fixture(autouse=True)
def limpo():
    """Cada teste comeca sem ferramenta publicada.

    O registro e global por desenho (o host carrega o setor ativo uma vez), e
    sem isso um teste herda o que o anterior publicou.
    """
    esquecer()
    yield
    esquecer()


class LojaFalsa:
    """Um store minimo: so o que `ctx.sql()` precisa."""

    def __init__(self, linhas=3):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        pd.DataFrame([{"id": i, "valor": i * 10} for i in range(linhas)]).to_sql(
            "pedidos", self._conn, index=False,
        )

    def get_sqlite_conn(self):
        return self._conn


# ------------------------------------------------- deteccao de assinatura

@pytest.mark.parametrize("funcao,espera", [
    (lambda a: a, False),
    (lambda a, ctx: a, True),
    (lambda a, ctx=None: a, True),
    (lambda *a: a, True),
    (lambda: None, False),
])
def test_a_ferramenta_escolhe_a_assinatura(funcao, espera):
    """Quem so precisa dos argumentos nao e obrigado a declarar um parametro
    que ignora: e pacote escrito antes do contexto continua funcionando."""
    assert _aceita_contexto(funcao) is espera


def test_assinatura_e_lida_por_inspecao_nao_por_erro():
    """Descobrir a assinatura pelo `TypeError` seria indistinguivel de um
    `TypeError` vindo de DENTRO da ferramenta: e o pacote acabaria chamado
    duas vezes por causa de um erro que e dele."""
    import inspect

    from sentury.domains import extensao

    fonte = inspect.getsource(extensao._aceita_contexto)
    assert "signature" in fonte


# ------------------------------------------------------ o acesso a dado

def test_ferramenta_de_pacote_le_do_store():
    """O teste que sustenta o resto: sem isto, pacote nao publica ferramenta de
    verdade, publica placeholder."""
    def registrar(api):
        async def contar(argumentos, ctx):
            conexao = ctx.sql()
            total = conexao.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
            return {"ok": True, "linhas": int(total), "setor": ctx.setor}

        api.ferramenta("contar", contar, descricao="conta pedidos")

    from sentury.domains.extensao import ApiDoPacote

    api = ApiDoPacote("vendas")
    registrar(api)

    ctx = ContextoDoPacote("vendas", store=LojaFalsa(linhas=7))
    saida = asyncio.run(executar("vendas.contar", {}, ctx))
    assert saida == {"ok": True, "linhas": 7, "setor": "vendas"}


def test_sem_fonte_sql_a_ferramenta_sabe():
    """Instalacao sem fonte SQL e cenario legitimo. `ctx.sql()` devolve None e
    o pacote decide o que dizer, em vez de estourar."""
    ctx = ContextoDoPacote("vendas", store=None)
    assert ctx.sql() is None

    class SemSql:
        pass

    assert ContextoDoPacote("vendas", store=SemSql()).sql() is None


def test_store_que_explode_nao_derruba_o_turno():
    class Quebrado:
        def get_sqlite_conn(self):
            raise RuntimeError("banco fora do ar")

    assert ContextoDoPacote("vendas", store=Quebrado()).sql() is None


def test_ferramenta_antiga_continua_funcionando():
    """Compatibilidade: pacote escrito antes do contexto recebe so os
    argumentos e nao percebe a mudanca."""
    from sentury.domains.extensao import ApiDoPacote

    api = ApiDoPacote("antigo")
    api.ferramenta("eco", lambda argumentos: {"ok": True, **argumentos},
                   descricao="devolve o que recebeu")

    ctx = ContextoDoPacote("antigo", store=LojaFalsa())
    assert asyncio.run(executar("antigo.eco", {"x": 1}, ctx)) == {"ok": True, "x": 1}


def test_contexto_faltando_diz_o_que_falta():
    """Sem isto, o autor do pacote recebia um `TypeError` cru sobre um
    parametro que ele declarou certo."""
    from sentury.domains.extensao import ApiDoPacote

    api = ApiDoPacote("vendas")
    api.ferramenta("precisa", lambda a, ctx: None, descricao="precisa de contexto")

    saida = asyncio.run(executar("vendas.precisa", {}))
    assert saida["ok"] is False
    assert "contexto" in saida["erro"]


def test_erro_dentro_da_ferramenta_vira_resposta():
    """O turno continua e o agente le o que aconteceu."""
    from sentury.domains.extensao import ApiDoPacote

    def explode(argumentos, ctx):
        raise ValueError("faltou coluna")

    api = ApiDoPacote("vendas")
    api.ferramenta("quebra", explode, descricao="quebra de proposito")

    saida = asyncio.run(executar("vendas.quebra", {}, ContextoDoPacote("vendas")))
    assert saida["ok"] is False
    assert "faltou coluna" in saida["erro"]
    assert saida["ferramenta"] == "vendas.quebra"


# ------------------------------------------- o exemplo deixa de ser falso
