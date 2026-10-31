"""O agente tem onde pensar por escrito.

Sem um rascunho, o trabalho intermediario (o script de uma tentativa, um
recorte de dado, uma saida longa demais para a conversa) ou ia para a pasta do
usuario (sujando o material dele, e pedindo autorizacao para algo que nem e
dele) ou nao acontecia: o agente tentava de cabeca o que cabia em duas etapas.
Foi assim que, num turno com LLM real, ele chutou o nome das colunas de um CSV,
errou e desistiu em vez de olhar o cabecalho primeiro.
"""
from pathlib import Path

import pytest

from sentury.tools.arquivos import (
    casa_do_sentury, e_rascunho, editar, escrever, ler, pasta_de_rascunho,
)


@pytest.fixture(autouse=True)
def casa(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    yield


def test_fica_fora_do_projeto():
    """Um rascunho dentro do repositorio apareceria no `git status` e viajaria
    no deploy. Ele e desta maquina, como o resto do que mora em `~/.sentury`."""
    alvo = pasta_de_rascunho("s1")
    assert casa_do_sentury() in alvo.parents
    assert "rascunho" in alvo.parts


def test_e_por_sessao():
    """Duas conversas compartilhando rascunho fariam uma ler o arquivo meio
    pronto da outra e concluir em cima dele."""
    assert pasta_de_rascunho("uma") != pasta_de_rascunho("outra")


def test_nome_de_sessao_estranho_nao_escapa():
    """O id vem de fora; sem limpar, `../../` viraria escrita em qualquer
    lugar: justamente no unico lugar onde nao se pede autorizacao."""
    alvo = pasta_de_rascunho("../../etc/passwd")
    base = (casa_do_sentury() / "rascunho").resolve()
    assert base in alvo.resolve().parents or base == alvo.resolve()


def test_escrever_no_rascunho_nao_pede_autorizacao():
    """Pedir permissao para o agente anotar no proprio bloco seria pedir
    permissao para ele pensar. O que exige permissao e tocar no material de
    alguem: e o rascunho nao e de ninguem."""
    alvo = pasta_de_rascunho("s2") / "tentativa.py"
    escrito = escrever(str(alvo), "resultado = 1")

    assert escrito.get("ok") is True
    assert not escrito.get("precisa_permissao")
    assert "resultado = 1" in (ler(str(alvo)).get("conteudo") or "")


def test_editar_no_rascunho_tambem_nao_pede():
    alvo = pasta_de_rascunho("s3") / "script.py"
    escrever(str(alvo), "a = 1")
    editado = editar(str(alvo), "a = 1", "a = 2")

    assert editado.get("ok") is True
    assert not editado.get("precisa_permissao")


def test_fora_do_rascunho_continua_gateado(tmp_path):
    """Abrir o rascunho nao pode afrouxar o resto: escrever no material do
    usuario continua exigindo pasta liberada e autorizacao."""
    fora = tmp_path / "pasta-alheia" / "arquivo.txt"
    resposta = escrever(str(fora), "x")

    assert resposta.get("ok") is not True


def test_e_rascunho_reconhece_so_o_que_e():
    dentro = pasta_de_rascunho("s4") / "sub" / "f.txt"
    assert e_rascunho(dentro.resolve())
    assert not e_rascunho(Path.home().resolve())


def test_o_agente_recebe_o_caminho_no_contexto():
    """Saber que existe um rascunho nao adianta sem o endereco: e o endereco
    muda por sessao, entao ele nao cabe no prompt fixo."""
    from sentury.harness.orchestrator import SenturyOrchestrator

    # Mudou de casa: o contexto do mundo saiu do orquestrador para
    # `harness/contexto_do_mundo.py`, junto com a cobertura do dado e o MCP.
    from sentury.harness.contexto_do_mundo import ambiente_do_turno

    contexto = ambiente_do_turno("sessao-teste") or ""
    assert "rascunho" in contexto
    assert str(pasta_de_rascunho("sessao-teste")) in contexto


def test_o_prompt_explica_para_que_serve():
    from sentury.llm.prompts import NUCLEO_DO_AGENTE

    assert "### Rascunho" in NUCLEO_DO_AGENTE
    # O risco de dar uma pasta livre e o agente entregar dali; a saida para o
    # usuario continua sendo `entregar_arquivo`.
    assert "entregar_arquivo" in NUCLEO_DO_AGENTE
