"""O turno grava a si mesmo, e o gravado repete.

`replay.gravar()` existia e nenhum turno era gravado. Esta bateria cobre o laco
inteiro: o turno acontece, vira traco, o traco repete, e a comparacao diz que
nao mudou nada. Sem isso, "ficou melhor depois da mudanca" nao tem como ser
respondido.
"""
import json

import pytest

from tests.fixtures.setor_teste.dados import StoreTeste
from sentury.harness import gravacao_do_turno as grav
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.mutation import replay


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_TRACOS_DIR", str(tmp_path / "tracos"))
    monkeypatch.setenv("SENTURY_GRAVAR_TRACOS", "true")
    from sentury.config import settings

    monkeypatch.setattr(settings, "SENTURY_GRAVAR_TRACOS", True, raising=False)
    yield


class LlmDeTeste:
    """Um provedor que responde o combinado e anota como a cadeia anotaria."""

    def __init__(self, respostas):
        self._fila = list(respostas)
        self.last_model = "teste:m1"
        self.last_provider = "teste"
        self.last_usage = None
        self.last_tool_calls = None

    async def complete(self, messages, *args, **kwargs):
        texto = self._fila.pop(0) if self._fila else json.dumps(
            {"action": "respond", "message": "pronto"})
        from robinbandit.chain import anotar_resposta

        anotar_resposta(texto=texto, tool_calls=None, modelo=self.last_model,
                        provedor=self.last_provider, ms=1)
        return texto


def _responder(mensagem="pronto"):
    return json.dumps({"action": "respond", "message": mensagem})


def _orquestrador(planner, responder):
    return SenturyOrchestrator(
        planner=planner, responder=responder,
        store=StoreTeste(),
    )


class TestOLacoFecha:
    async def test_o_turno_vira_traco(self):
        llm = LlmDeTeste([_responder("oi, tudo bem")])
        orq = _orquestrador(llm, llm)
        estado = AnalysisState.new("sessao-teste", "dono")

        await orq.handle_message(estado, "oi")

        tracos = replay.listar()
        assert len(tracos) == 1, "o turno tinha que ter sido gravado"
        t = tracos[0]
        assert t.mensagem == "oi"
        assert t.origem == "sessao-teste"
        assert t.respostas_llm, "sem a resposta do modelo o replay chamaria o modelo de novo"
        assert t.estado_inicial, "o estado de ANTES e o que faz o replay partir do mesmo lugar"

    async def test_o_estado_gravado_e_o_de_antes(self):
        """Se fosse o de depois, o traco ja traria a resposta junto da pergunta
        e o replay comecaria com o turno feito."""
        llm = LlmDeTeste([_responder()])
        orq = _orquestrador(llm, llm)
        estado = AnalysisState.new("s", "u")

        await orq.handle_message(estado, "primeira pergunta")

        t = replay.listar()[0]
        gravado = json.dumps(t.estado_inicial.get("history") or [], ensure_ascii=False)
        assert "primeira pergunta" not in gravado
        assert len(estado.history) > 0, "o estado vivo seguiu sendo mutado"

    async def test_o_ambiente_vai_junto(self):
        """Baseline e candidata podem diferir por ambiente; sem registrar, a
        diferenca e creditada ao codigo."""
        llm = LlmDeTeste([_responder()])
        await _orquestrador(llm, llm).handle_message(AnalysisState.new("s", "u"), "oi")

        ambiente = replay.listar()[0].ambiente
        assert "dominio" in ambiente and "native_tools" in ambiente
        assert "modo" in ambiente

    async def test_nasce_em_desenvolvimento_e_nao_em_avaliacao(self):
        """Turno de producao caindo em `avaliacao` e o vazamento que
        `separar_holdout()` existe para evitar."""
        llm = LlmDeTeste([_responder()])
        await _orquestrador(llm, llm).handle_message(AnalysisState.new("s", "u"), "oi")

        assert replay.listar()[0].conjunto == "desenvolvimento"

    async def test_o_traco_repete_e_a_comparacao_diz_que_nao_mudou(self):
        """O criterio de saida da fase: gravar, repetir, comparar."""
        llm = LlmDeTeste([_responder("a resposta de sempre")])
        await _orquestrador(llm, llm).handle_message(AnalysisState.new("s", "u"), "me responde")

        t = replay.listar()[0]
        base = await replay.repetir(t, _orquestrador)
        cand = await replay.repetir(t, _orquestrador)
        assert base["ok"] and cand["ok"], base.get("erro") or cand.get("erro")

        diff = replay.comparar(base, cand)
        assert diff["comparavel"] and not diff["mudou"]


class TestNaoAtrapalha:
    async def test_desligado_nao_grava_nada(self, monkeypatch):
        from sentury.config import settings

        monkeypatch.setattr(settings, "SENTURY_GRAVAR_TRACOS", False, raising=False)
        llm = LlmDeTeste([_responder()])
        await _orquestrador(llm, llm).handle_message(AnalysisState.new("s", "u"), "oi")
        assert replay.listar() == []

    async def test_o_replay_nao_grava_a_si_mesmo(self):
        """Sem esta guarda, cada rodada de mutacao multiplica o corpus com
        copias do proprio replay."""
        llm = LlmDeTeste([_responder()])
        await _orquestrador(llm, llm).handle_message(AnalysisState.new("s", "u"), "oi")
        assert len(replay.listar()) == 1

        await replay.repetir(replay.listar()[0], _orquestrador)
        assert len(replay.listar()) == 1, "o replay gravou a si mesmo"

    async def test_falha_do_gravador_nao_derruba_o_turno(self, monkeypatch):
        """Observabilidade que derruba o turno que ela observa e pior que
        observabilidade nenhuma."""
        def explode(**kwargs):
            raise RuntimeError("disco cheio")

        monkeypatch.setattr(replay, "gravar", explode)
        llm = LlmDeTeste([_responder("continuou funcionando")])
        r = await _orquestrador(llm, llm).handle_message(AnalysisState.new("s", "u"), "oi")
        assert r["message"]


class TestDeterminismo:
    def test_ferramenta_de_rede_marca_o_traco_como_nao_deterministico(self):
        assert "buscar_web" in grav._nao_deterministas()
        assert "browser" in grav._nao_deterministas()
