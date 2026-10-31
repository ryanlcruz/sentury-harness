"""Uma ferramenta que pendura não pode pendurar o turno.

Uma chamada pode não voltar: pasta de rede fora do ar, consulta que nunca
termina, HTTP sem resposta. Sem prazo, o turno para junto. Este arquivo fixa três
escolhas:

**Cooperativo.** Em Python, uma ferramenta síncrona no executor não é
interrompida de verdade: a espera é abandonada e a thread termina sozinha. O
módulo diz isso em voz alta, e não finge o contrário.

**O limite vem da própria ferramenta.** Não existe número global certo: uma busca
na web e uma leitura local não têm o mesmo tempo razoável.

**O estouro vira erro para o modelo**, não exceção para o harness: ele lê que a
chamada não voltou e escolhe outra rota.
"""
import asyncio

import pytest

from sentury.config import settings
from sentury.harness.loop_budget import LoopBudget
from sentury.tools import prazo


async def _pendura():
    await asyncio.sleep(30)


async def _rapida():
    return {"ok": True, "linhas": 3}


# ------------------------------------------------- o limite é da ferramenta

def test_sem_declaracao_vale_o_padrao():
    assert prazo.prazo_de("listar_arquivos") == prazo.PRAZO_PADRAO_S


def test_quem_demora_por_natureza_declara_mais():
    """Busca na web lê páginas; shell roda pytest. Cortar nos 45s do padrão
    transformaria uso legítimo em falha."""
    assert prazo.prazo_de("buscar_web") > prazo.PRAZO_PADRAO_S
    assert prazo.prazo_de("executar_comando") > prazo.PRAZO_PADRAO_S


def test_ferramenta_desconhecida_nao_fica_sem_prazo():
    assert prazo.prazo_de("ferramenta_que_nao_existe") == prazo.PRAZO_PADRAO_S


def test_declaracao_invalida_cai_no_padrao(monkeypatch):
    """`prazo_s: "muito"` num pacote de terceiro não pode virar exceção aqui."""
    from sentury.tools import registry

    monkeypatch.setitem(registry.TOOL_REGISTRY, "x", {"prazo_s": "muito"})
    assert prazo.prazo_de("x") == prazo.PRAZO_PADRAO_S
    monkeypatch.setitem(registry.TOOL_REGISTRY, "y", {"prazo_s": 0})
    assert prazo.prazo_de("y") == prazo.PRAZO_PADRAO_S


def test_o_prazo_padrao_cabe_no_turno():
    """Prazo que estoura depois do turno não protege nada: quando ele viesse, já
    não haveria turno."""
    orcamento_s = LoopBudget.from_settings(settings).max_elapsed_ms / 1000
    assert prazo.PRAZO_PADRAO_S < orcamento_s


# ------------------------------------------------- o que o modelo recebe

@pytest.mark.asyncio
async def test_chamada_rapida_passa_intacta():
    assert await prazo.com_prazo("listar_arquivos", _rapida()) == {"ok": True, "linhas": 3}


@pytest.mark.asyncio
async def test_estouro_vira_erro_e_nao_excecao(monkeypatch):
    monkeypatch.setattr(prazo, "PRAZO_PADRAO_S", 0.2)
    r = await prazo.com_prazo("listar_arquivos", _pendura())
    assert r.get("timeout") is True
    assert "listar_arquivos" in r["erro"]


@pytest.mark.asyncio
async def test_o_erro_diz_o_que_fazer_em_seguida():
    """Um erro que só descreve o problema deixa o modelo repetir a mesma coisa."""
    texto = prazo.estouro("buscar_web", 60)["erro"]
    assert "outro caminho" in texto or "responda com o que ja tem" in texto


# ------------------------------------------------- pela porta de verdade

@pytest.mark.asyncio
async def test_execute_tool_aplica_o_prazo(monkeypatch):
    """O prazo vive DENTRO do `execute_tool` de propósito: são oito pontos de
    chamada no orquestrador, e um deles esqueceria."""
    from sentury.tools import catalog

    async def _lenta(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(catalog, "_executar_ferramenta", _lenta)
    monkeypatch.setattr(prazo, "PRAZO_PADRAO_S", 0.2)
    r = await catalog.execute_tool(None, None, "listar_arquivos", {})
    assert r.get("timeout") is True
