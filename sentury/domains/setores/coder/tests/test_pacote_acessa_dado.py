"""O pacote de setor passa a consultar dado de verdade.

Ate aqui a `ApiDoPacote` entregava so `api.ferramenta(...)`, e a funcao recebia
`(argumentos)` e mais nada: sem store, sem sessao. Um pacote conseguia
publicar ferramenta, mas ela nao consultava coisa nenhuma, e por isso o
`coder/tools.py` de exemplo devolvia numero inventado com um aviso pedindo
desculpa.

Era o bloqueio de fundacao: mover `analyze_nps` para dentro do pacote e
impossivel enquanto o pacote nao alcanca o banco.
"""
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

PACOTE_DO_CODER = Path("sentury/domains/setores/coder")


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





# ------------------------------------------------------ o acesso a dado













# ------------------------------------------- o exemplo deixa de ser falso

def test_o_pacote_de_exemplo_consulta_de_verdade():
    """`coder/tools.py` devolvia `exemplo: True` com um aviso dizendo para nao
    confiar no numero. Era honesto, e era o sintoma."""
    publicadas_agora = carregar(PACOTE_DO_CODER, "coder")
    assert "coder.contar_tabela" in publicadas_agora

    ctx = ContextoDoPacote("coder", store=LojaFalsa(linhas=4))
    saida = asyncio.run(executar("coder.contar_tabela", {"tabela": "pedidos"}, ctx))
    assert saida == {"ok": True, "tabela": "pedidos", "linhas": 4, "setor": "coder"}

    fonte = (PACOTE_DO_CODER / "tools.py").read_text(encoding="utf-8")
    assert "exemplo" not in fonte.lower() or "ctx.sql()" in fonte


def test_tabela_que_nao_existe_devolve_erro_legivel():
    carregar(PACOTE_DO_CODER, "coder")
    ctx = ContextoDoPacote("coder", store=LojaFalsa())
    saida = asyncio.run(executar("coder.contar_tabela", {"tabela": "fantasma"}, ctx))
    assert saida["ok"] is False and saida["tabela"] == "fantasma"


def test_nome_de_tabela_do_pacote_nao_vira_injecao():
    """O nome vem de fora, e parametro SQL nao serve para identificador."""
    carregar(PACOTE_DO_CODER, "coder")
    ctx = ContextoDoPacote("coder", store=LojaFalsa())
    saida = asyncio.run(executar(
        "coder.contar_tabela", {"tabela": 'pedidos"; DROP TABLE pedidos --'}, ctx,
    ))
    assert saida["ok"] is False
    # A tabela continua de pe.
    depois = asyncio.run(executar("coder.contar_tabela", {"tabela": "pedidos"}, ctx))
    assert depois["ok"] is True


def test_o_prefixo_do_setor_continua_valendo():
    """Dois pacotes podem chamar a mesma coisa de `status`; sem o prefixo o
    segundo apagaria o primeiro em silencio."""
    carregar(PACOTE_DO_CODER, "coder")
    assert all(nome.startswith("coder.") for nome in publicadas("coder"))
