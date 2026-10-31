"""A tela Tasks funciona sem pacote de setor.

Virar o padrao para `generalista` trocou o store por `SemDados`, que so
respondia `get_*`. A fila da tela Tasks morava no store de CX: a tela passou a
aparecer sempre vazia (o endpoint engole o erro) e o "enviar pro Tasks" do
card de plano dava 500. A fila nao e de setor: e onde o plano vira tarefa.
"""
import asyncio

from sentury.data.store import SemDados


def test_enviar_plano_listar_e_concluir():
    store = SemDados()

    async def fluxo():
        criada = await store.criar_acao({
            "titulo": "Plano X", "descricao": "- [ ] 1. fazer", "origem": "plano-de-acao",
        })
        abertas = await store.listar_acoes(status="Aberta")
        feita = await store.atualizar_acao(criada["id"], {"status": "Concluída"})
        return criada, abertas, feita

    criada, abertas, feita = asyncio.run(fluxo())
    assert criada["id"] and criada["status"] == "Aberta"
    assert [a["id"] for a in abertas] == [criada["id"]]
    assert feita["status"] == "Concluída"


def test_nao_exige_campo_de_setor():
    """`regiao` e `filial` eram obrigatorios de fato no store de CX."""
    acao = asyncio.run(SemDados().criar_acao({"titulo": "sem regiao"}))
    assert "regiao" not in acao and "filial" not in acao


def test_atualizar_o_que_nao_existe_devolve_none():
    assert asyncio.run(SemDados().atualizar_acao("AC-999", {"status": "x"})) is None
