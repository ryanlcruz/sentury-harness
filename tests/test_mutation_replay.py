"""Replay: repetir turnos que aconteceram, contra baseline e candidata."""
import json

import pytest

from tests.fixtures.setor_teste.dados import StoreTeste
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.mutation import replay


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_TRACOS_DIR", str(tmp_path / "tracos"))
    yield


def _orquestrador(planner, responder):
    return SenturyOrchestrator(
        planner=planner, responder=responder,
        store=StoreTeste(),
    )


def _acao(tool=None, mensagem="pronto"):
    if tool:
        return json.dumps({"action": "tool_call", "tool": tool, "arguments": {}})
    return json.dumps({"action": "respond", "message": mensagem})


def test_traco_exige_a_mensagem_e_um_conjunto_valido():
    with pytest.raises(ValueError, match="mensagem"):
        replay.gravar(mensagem="  ")
    with pytest.raises(ValueError, match="conjunto"):
        replay.gravar(mensagem="oi", conjunto="qualquer")


def test_traco_sobrevive_e_e_listavel():
    t = replay.gravar(mensagem="como esta o medida?", respostas_llm=[_acao("consultar_medida")],
                      origem="sess-123", conjunto="avaliacao")
    assert replay.carregar(t.id).mensagem == "como esta o medida?"
    assert [x.id for x in replay.listar("avaliacao")] == [t.id]
    assert replay.listar("holdout") == []


async def test_repetir_usa_as_respostas_gravadas():
    """Sem reproduzir o que o modelo respondeu, a diferenca observada poderia
    vir do modelo variando, nao do codigo alterado."""
    t = replay.gravar(mensagem="me traz a causa raiz",
                      respostas_llm=[_acao("consultar_medida"), _acao(mensagem="a causa e o backlog")])
    saida = await replay.repetir(t, _orquestrador)
    assert saida["ok"], saida.get("erro")
    assert saida["respostas_consumidas"] >= 1


async def test_replay_que_pede_mais_do_que_gravou_falha_em_vez_de_inventar():
    """Um replay que continua com resposta improvisada mede outra coisa e nao
    avisa.

    Nem todo turno consulta o modelo: alguns terminam por caminho curto. A
    garantia nao e "sem respostas falha", e sim: PEDIU mais do que existe,
    para.
    """
    gravado = replay.LlmGravado([_acao("consultar_medida")])
    primeira = await gravado.complete([])
    assert primeira and gravado.consumidas == 1

    with pytest.raises(RuntimeError, match="mais respostas"):
        await gravado.complete([])
    assert gravado.faltou

    # E dentro do replay isso vira falha registrada, nao excecao solta.
    t = replay.gravar(mensagem="cruza tudo e me da o plano",
                      respostas_llm=[_acao("consultar_medida")])
    saida = await replay.repetir(t, _orquestrador)
    if not saida["ok"]:
        assert saida["respostas_faltaram"] or saida["erro"]


async def test_comparar_diz_o_que_mudou_sem_julgar(setor_teste):
    t = replay.gravar(mensagem="qual a causa raiz?",
                      respostas_llm=[_acao("consultar_medida"), json.dumps({"plan": []}), _acao(mensagem="resposta")])
    base = await replay.repetir(t, _orquestrador)
    cand = await replay.repetir(t, _orquestrador)

    igual = replay.comparar(base, cand)
    assert not base["respostas_faltaram"] and not cand["respostas_faltaram"]
    assert igual["comparavel"] and not igual["mudou"]

    diferente = replay.comparar(base, {**cand, "mensagem": "outra coisa"})
    assert diferente["mudou"] and not diferente["mensagem_igual"]
    # Nao ha veredito aqui: julgar e do fitness.
    assert "melhor" not in json.dumps(diferente)


def test_execucao_que_falhou_nao_e_comparavel():
    ruim = {"ok": False, "erro": "estourou"}
    bom = {"ok": True, "mensagem": "x", "ferramentas": [], "anexo": "", "ms": 10}
    saida = replay.comparar(bom, ruim)
    assert not saida["comparavel"] and saida["erro_candidata"] == "estourou"


@pytest.mark.parametrize("lado", ["baseline", "candidata", "ambas"])
def test_mesmo_erro_com_chamada_ausente_nao_passa_como_igual(lado):
    base = {"ok": True, "mensagem": "O modelo falhou.", "ferramentas": [], "anexo": ""}
    cand = dict(base)
    if lado in ("baseline", "ambas"):
        base["respostas_faltaram"] = True
    if lado in ("candidata", "ambas"):
        cand["respostas_faltaram"] = True
    resultado = replay.comparar(base, cand)
    assert resultado["mensagem_igual"] is True
    assert resultado["mudou"] is True


def test_holdout_sai_do_conjunto_de_avaliacao():
    """Sem um conjunto que a mutacao nunca viu, ela pode ser ajustada ate
    passar exatamente nos casos que a motivaram."""
    for i in range(10):
        replay.gravar(mensagem=f"pergunta {i}", conjunto="avaliacao")
    saida = replay.separar_holdout(0.3)
    assert saida["movidos"] == 3 and saida["avaliacao"] == 7
    assert len(replay.listar("holdout")) == 3
    assert len(replay.listar("avaliacao")) == 7


def test_separacao_e_deterministica():
    """Sorteio faria a mesma bateria mudar de composicao entre execucoes, e ai
    duas medicoes nao se comparam."""
    for i in range(6):
        replay.gravar(mensagem=f"p{i}", conjunto="avaliacao", traco_id=f"T-{i:04d}")
    replay.separar_holdout(0.5)
    primeiro = sorted(t.id for t in replay.listar("holdout"))
    assert primeiro == ["T-0000", "T-0001", "T-0002"]


async def test_replay_repoe_a_pasta_de_trabalho_da_producao(tmp_path, monkeypatch):
    """A pasta decide o que é liberado e o que pede cartão. Repetido com a pasta
    desta máquina, um caminho que era da pasta de trabalho caía fora das
    liberadas e o turno tomava outro caminho."""
    from sentury.tools import arquivos

    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path / "outra"))
    producao = tmp_path / "producao"
    vista = []

    class _Orquestrador:
        async def handle_message(self, estado, mensagem):
            vista.append(arquivos.raiz_de_trabalho())
            return {"message": "ok"}

    t = replay.gravar(mensagem="oi", respostas_llm=[], ambiente={"pasta_de_trabalho": str(producao)})
    saida = await replay.repetir(t, lambda planner, responder: _Orquestrador())
    assert saida["ok"], saida.get("erro")
    assert vista == [producao.resolve()]
    assert arquivos.raiz_de_trabalho() == (tmp_path / "outra").resolve()


def test_gravacao_guarda_a_pasta_de_trabalho(tmp_path, monkeypatch):
    from sentury.harness import gravacao_do_turno

    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    assert gravacao_do_turno._ambiente("low")["pasta_de_trabalho"] == str(tmp_path.resolve())
