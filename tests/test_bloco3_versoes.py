"""`kind` completo, e como o arquivo estava duas edicoes atras.

O `kind` separa ler, escrever, editar e apagar, para a tela nao desenhar
escrita igual a leitura.

O historico guarda a ordem das versoes: o cofre por conteudo responde "qual era
este conteudo", e e a ordem que se precisa quando uma alteracao quebrou algo.
"""
from pathlib import Path

import pytest

from sentury.harness.orchestrator import SenturyOrchestrator as Orq
from sentury.memory import versoes
from sentury.tools.registry import TOOL_REGISTRY


# ------------------------------------------------------------------- kind

def test_o_vocabulario_tem_os_oito():
    assert set(Orq.TOOL_KINDS) == {
        "read", "execute", "edit", "delete", "move", "search", "fetch", "other",
    }


@pytest.mark.parametrize("ferramenta,esperado", [
    ("esquecer_memoria", "delete"),
    ("esquecer_skill", "delete"),
    ("cancel_schedule", "delete"),
    ("kill_command", "delete"),
    ("buscar_web", "fetch"),
    ("ler_pagina", "fetch"),
    ("usar_mcp", "fetch"),
    ("ler_arquivo", "read"),
    ("escrever_arquivo", "edit"),
    ("editar_arquivo", "edit"),
    ("restaurar_versao", "edit"),
    ("historico_do_arquivo", "read"),
    ("executar_comando", "execute"),
])
def test_cada_ferramenta_no_selo_certo(ferramenta, esperado):
    assert Orq._tool_kind(ferramenta) == esperado


def test_apagar_ganha_de_editar():
    """`esquecer_memoria` comeca com um prefixo de alteracao e nao e edicao. A
    ordem das regras e o que decide, entao ela tem teste."""
    assert Orq._tool_kind("esquecer_memoria") == "delete"


def test_buscar_na_web_ganha_de_buscar():
    """`buscar_web` casa com `buscar_` tambem; se a ordem inverter, ir na
    internet vira busca local na tela."""
    assert Orq._tool_kind("buscar_web") == "fetch"
    assert Orq._tool_kind("buscar_conhecimento") == "search"


def test_quase_nada_fica_sem_selo():
    """`other` e a saida de emergencia, nao o padrao. Quando metade do
    registro cai nela, a tela nao tem o que desenhar."""
    sem_selo = [t for t in TOOL_REGISTRY if Orq._tool_kind(t) == "other"]
    assert sem_selo == ["perguntar_usuario"], sem_selo


def test_todo_kind_esta_no_vocabulario():
    """O contrato do client valida contra esta lista: um valor fora dela chega
    na tela como um selo que ninguem sabe desenhar."""
    for t in TOOL_REGISTRY:
        assert Orq._tool_kind(t) in Orq.TOOL_KINDS, t


def test_o_contrato_do_client_tem_os_mesmos_oito():
    fonte = Path("sentury/client/src/contracts/events/session-events.ts").read_text(
        encoding="utf-8",
    )
    trecho = fonte.split("ToolKindSchema")[1].split(";")[0]
    for kind in Orq.TOOL_KINDS:
        assert f"'{kind}'" in trecho, kind


def test_bloco_distingue_erro_fatal_de_erro_contornado():
    """Falhar e recuperar no mesmo turno nao pode parecer turno quebrado."""
    contrato = Path(
        "sentury/client/src/contracts/events/session-events.ts",
    ).read_text(encoding="utf-8")
    store = Path("sentury/client/src/stores/chat-store.ts").read_text(
        encoding="utf-8",
    )
    bloco = Path("sentury/client/src/features/chat/CommandCard.tsx").read_text(
        encoding="utf-8",
    )

    assert "'handledError'" in contrato
    assert "entry.status === 'error'" in store
    assert "status: 'handledError' as const" in store
    assert "contornado" in bloco
    assert "falhou, mas o agente seguiu por outro caminho" in bloco
    assert 'aria-label="pendente"' in bloco
    assert 'aria-label="dispensado"' in bloco


def test_atlas_nomeia_estados_e_mostra_resultado_dos_subagentes():
    atlas = Path("sentury/client/src/dev/InterfaceAtlas.tsx").read_text(
        encoding="utf-8",
    )
    sinais = Path(
        "sentury/client/src/features/chat/ResponseSignals.tsx",
    ).read_text(encoding="utf-8")

    for status in (
        "pending", "running", "ok", "handledError", "error", "rejected",
        "canceled", "skipped",
    ):
        assert f"status: '{status}'" in atlas
    assert "Trabalho em paralelo" in sinais
    assert "result.summary" in sinais
    assert "trabalhando" in sinais


def test_a_tela_sabe_desenhar_cada_kind():
    """O contrato aceitar o valor nao basta: se `capabilityOfKind` nao tiver o
    `case`, o passo cai no `default` e aparece como Sentury generico: o selo
    novo passa a existir no backend e a nao significar nada na tela. Sem
    runner no client, o teste le o fonte; e feio, e pega a deriva."""
    fonte = Path("sentury/client/src/components/CapabilityMark.tsx").read_text(
        encoding="utf-8",
    )
    corpo = fonte.split("export function capabilityOfKind")[1].split("}")[0]
    for kind in Orq.TOOL_KINDS:
        if kind == "other":
            continue   # `other` E o default, e nao precisa de case proprio
        assert f"case '{kind}'" in corpo, kind


# -------------------------------------------------------------- historico

def _escrever(alvo: Path, texto: str) -> None:
    """Sem traducao de fim de linha: o historico guarda os bytes exatos do
    disco, e no Windows `write_text` transformaria LF em CRLF: o teste
    passaria a medir o Python em vez do modulo."""
    alvo.write_text(texto, encoding="utf-8", newline="")


def _texto(dados):
    return None if dados is None else dados.decode("utf-8").replace(chr(13), "")


@pytest.fixture
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    return tmp_path


def test_a_primeira_versao_e_como_o_arquivo_foi_encontrado(casa):
    alvo = casa / "x.py"
    _escrever(alvo, "original\n")
    versoes.anotar(alvo, session_id="s1", por="como estava")
    _escrever(alvo, "alterado\n")
    versoes.anotar(alvo, session_id="s1", por="editar_arquivo")

    linha = versoes.versoes(alvo, session_id="s1")
    assert [x["v"] for x in linha] == [1, 2]
    assert _texto(versoes.conteudo(alvo, 1, session_id="s1")) == "original\n"


def test_conteudo_igual_nao_vira_versao_nova(casa):
    """Salvar sem mudar nada nao e uma alteracao, e encher a linha do tempo de
    versoes identicas apaga a que interessa."""
    alvo = casa / "x.py"
    _escrever(alvo, "mesmo\n")
    versoes.anotar(alvo, session_id="s1")
    r = versoes.anotar(alvo, session_id="s1")
    assert r["nova"] is False
    assert len(versoes.versoes(alvo, session_id="s1")) == 1


def test_voltar_ao_conteudo_antigo_ainda_e_uma_versao_nova(casa):
    """O cofre por conteudo devolveria o mesmo hash e diria que nada mudou. Na
    linha do tempo, desfazer e um evento: v3, com o conteudo de v1."""
    alvo = casa / "x.py"
    for texto in ("a\n", "b\n", "a\n"):
        _escrever(alvo, texto)
        versoes.anotar(alvo, session_id="s1")
    linha = versoes.versoes(alvo, session_id="s1")
    assert [x["v"] for x in linha] == [1, 2, 3]
    assert linha[0]["hash"] == linha[2]["hash"]   # um conteudo so no disco


def test_o_diff_ate_agora_pega_alteracao_feita_por_fora(casa):
    """Editor do usuario e `git checkout` nao passam por `anotar`, e sao
    justamente o que o agente precisa ver antes de escrever por cima."""
    alvo = casa / "x.py"
    _escrever(alvo, "um\n")
    versoes.anotar(alvo, session_id="s1")
    _escrever(alvo, "dois\n")   # ninguem anotou

    r = versoes.diferenca(alvo, 1, session_id="s1")
    assert r["ok"] and not r["igual"]
    assert "-um" in r["diff"] and "+dois" in r["diff"]


def test_diff_entre_duas_versoes(casa):
    alvo = casa / "x.py"
    for texto in ("um\n", "dois\n", "tres\n"):
        _escrever(alvo, texto)
        versoes.anotar(alvo, session_id="s1")
    r = versoes.diferenca(alvo, 1, 2, session_id="s1")
    assert "+dois" in r["diff"] and "tres" not in r["diff"]


def test_versao_que_nao_existe_falha_alto(casa):
    alvo = casa / "x.py"
    _escrever(alvo, "a\n")
    versoes.anotar(alvo, session_id="s1")
    assert versoes.diferenca(alvo, 9, session_id="s1")["ok"] is False
    assert versoes.conteudo(alvo, 9, session_id="s1") is None


def test_restaurar_e_desfazivel(casa):
    """Voltar nao pode ser porta de mao unica: se a restauracao foi engano, o
    que estava la tem que continuar existindo."""
    alvo = casa / "x.py"
    for texto in ("um\n", "dois\n"):
        _escrever(alvo, texto)
        versoes.anotar(alvo, session_id="s1")

    versoes.restaurar(alvo, 1, session_id="s1")
    assert alvo.read_text(encoding="utf-8").replace(chr(13), "") == "um\n"
    linha = versoes.versoes(alvo, session_id="s1")
    assert len(linha) >= 3
    assert _texto(versoes.conteudo(alvo, 2, session_id="s1")) == "dois\n"


def test_sessoes_separadas_e_a_linha_junta(casa):
    alvo = casa / "x.py"
    _escrever(alvo, "a\n")
    versoes.anotar(alvo, session_id="s1")
    _escrever(alvo, "b\n")
    versoes.anotar(alvo, session_id="s2")

    assert len(versoes.versoes(alvo, session_id="s1")) == 1
    assert len(versoes.versoes(alvo, session_id="s2")) == 1
    todas = versoes.versoes(alvo)
    assert len(todas) == 2
    assert [x["sessao"] for x in todas] == ["s1", "s2"]


def test_arquivo_grande_nao_entra(casa):
    """A chamada aqui e automatica a cada escrita: um dump de banco encheria o
    disco sem ninguem ter pedido."""
    alvo = casa / "grande.bin"
    alvo.write_bytes(b"x" * (versoes.MAX_BYTES + 1))
    r = versoes.anotar(alvo, session_id="s1")
    assert r["ok"] is False and r["ignorado"] is True


def test_a_poda_nao_reindexa(casa):
    """Se a versao 3 foi citada numa resposta, ela nao pode virar a 1 depois."""
    alvo = casa / "x.py"
    for i in range(versoes.MAX_VERSOES + 5):
        _escrever(alvo, f"v{i}\n")
        versoes.anotar(alvo, session_id="s1")
    linha = versoes.versoes(alvo, session_id="s1")
    assert len(linha) <= versoes.MAX_VERSOES
    assert linha[0]["v"] > 1, "reindexou: a versao antiga mudou de numero"


def test_tocados_lista_o_que_a_sessao_mexeu(casa):
    _escrever(casa / "a.py", "a\n")
    _escrever(casa / "b.py", "b\n")
    versoes.anotar(casa / "a.py", session_id="s1")
    versoes.anotar(casa / "b.py", session_id="s1")
    versoes.anotar(casa / "a.py", session_id="outra")

    nomes = [Path(x["caminho"]).name for x in versoes.tocados("s1")]
    assert sorted(nomes) == ["a.py", "b.py"]


# ------------------------------------------------- engate nas ferramentas

def test_escrever_e_editar_deixam_a_linha_do_tempo(casa, monkeypatch):
    from sentury.tools import arquivos

    trabalho = casa / "projeto"
    trabalho.mkdir()
    monkeypatch.setattr(arquivos, "raiz_de_trabalho", lambda: trabalho)
    monkeypatch.setattr(arquivos, "_pedir_autorizacao", lambda *a, **k: None)

    alvo = trabalho / "x.py"
    _escrever(alvo, "primeiro\n")
    arquivos.escrever(str(alvo), "segundo\n", session_id="s1")
    arquivos.editar(str(alvo), "segundo", "terceiro", session_id="s1")

    linha = versoes.versoes(alvo, session_id="s1")
    assert [x["v"] for x in linha] == [1, 2, 3]
    assert _texto(versoes.conteudo(alvo, 1, session_id="s1")) == "primeiro\n"
    assert alvo.read_text(encoding="utf-8").replace(chr(13), "") == "terceiro\n"


def test_o_rascunho_nao_vira_historico(casa, monkeypatch):
    """Anotacao do agente nao e material de ninguem: versionar o bloco de
    rascunho so gastaria disco."""
    from sentury.tools import arquivos

    rascunho = arquivos.pasta_de_rascunho("s1")
    alvo = rascunho / "nota.md"
    monkeypatch.setattr(arquivos, "_pedir_autorizacao", lambda *a, **k: None)
    arquivos.escrever(str(alvo), "um\n", session_id="s1")
    arquivos.escrever(str(alvo), "dois\n", session_id="s1")
    assert versoes.versoes(alvo, session_id="s1") == []


def test_historico_quebrado_nao_derruba_a_escrita(casa, monkeypatch):
    """O historico e o registro do trabalho, nao o trabalho: se ele falhar, o
    agente nao pode ficar sem conseguir editar."""
    from sentury.tools import arquivos

    trabalho = casa / "projeto"
    trabalho.mkdir()
    monkeypatch.setattr(arquivos, "raiz_de_trabalho", lambda: trabalho)
    monkeypatch.setattr(arquivos, "_pedir_autorizacao", lambda *a, **k: None)

    def explode(*a, **k):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(versoes, "anotar", explode)
    r = arquivos.escrever(str(trabalho / "x.py"), "conteudo\n", session_id="s1")
    assert r["ok"] is True


# ------------------------------------------------ o caminho que o agente usa

async def test_as_duas_ferramentas_pelo_catalog(casa, monkeypatch):
    """O modulo passar nao basta: o agente chega por `execute_tool`, e e la
    que a sessao, a resolucao de caminho e o portao de escrita se encontram."""
    from sentury.harness.state import AnalysisState
    from sentury.tools import arquivos
    from sentury.tools.catalog import execute_tool

    trabalho = casa / "projeto"
    trabalho.mkdir()
    monkeypatch.setattr(arquivos, "raiz_de_trabalho", lambda: trabalho)
    monkeypatch.setattr(arquivos, "_pedir_autorizacao", lambda *a, **k: None)

    state = AnalysisState.new("s-cat", "u1")
    alvo = trabalho / "x.py"
    _escrever(alvo, "primeiro" + chr(10))
    await execute_tool(None, state, "escrever_arquivo",
                       {"caminho": "x.py", "conteudo": "segundo" + chr(10)})

    listado = await execute_tool(None, state, "historico_do_arquivo", {"caminho": "x.py"})
    assert listado["ok"] and [v["v"] for v in listado["versoes"]] == [1, 2]

    diff = await execute_tool(None, state, "historico_do_arquivo",
                              {"caminho": "x.py", "versao": 1})
    assert "-primeiro" in diff["diff"] and "+segundo" in diff["diff"]

    voltou = await execute_tool(None, state, "restaurar_versao",
                                {"caminho": "x.py", "versao": 1})
    assert voltou["ok"] and voltou["restaurado_de"] == 1
    assert alvo.read_text(encoding="utf-8").replace(chr(13), "") == "primeiro" + chr(10)


async def test_arquivo_sem_historico_explica_em_vez_de_falhar(casa, monkeypatch):
    from sentury.harness.state import AnalysisState
    from sentury.tools import arquivos
    from sentury.tools.catalog import execute_tool

    trabalho = casa / "projeto"
    trabalho.mkdir()
    monkeypatch.setattr(arquivos, "raiz_de_trabalho", lambda: trabalho)
    _escrever(trabalho / "intocado.py", "nada" + chr(10))

    r = await execute_tool(None, AnalysisState.new("s-cat", "u1"),
                           "historico_do_arquivo", {"caminho": "intocado.py"})
    assert r["ok"] and r["versoes"] == []
    assert "nao foi alterado" in r["nota"]
