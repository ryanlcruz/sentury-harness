"""O corpus de tracos tem teto e prazo.

Cada turno grava um traco, e nada apagava. O diretorio so crescia, e
`replay.listar()` lia tudo para a memoria para usar os ultimos vinte. E o traco
guarda a conversa inteira, anexo incluso: ficar para sempre nao foi decisao de
ninguem.
"""
import os
import time

import pytest

from sentury.mutation import replay


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_TRACOS_DIR", str(tmp_path / "tracos"))
    from sentury.config import settings

    monkeypatch.setattr(settings, "SENTURY_TRACOS_MAXIMO", 500, raising=False)
    monkeypatch.setattr(settings, "SENTURY_TRACOS_DIAS", 30, raising=False)
    yield


def _gravar(n, conjunto="desenvolvimento", comeco=1_000_000):
    """N tracos com datas de arquivo distintas: a ordem nao pode depender de
    dois arquivos caindo no mesmo tique do relogio."""
    ids = []
    for i in range(n):
        t = replay.gravar(mensagem=f"turno {i}", respostas_llm=["ok"], conjunto=conjunto,
                          traco_id=f"{conjunto[:3]}-{i:03d}")
        quando = comeco + i * 10
        os.utime(replay.pasta() / f"{t.id}.json", (quando, quando))
        ids.append(t.id)
    return ids


def _existentes():
    return sorted(p.stem for p in replay.pasta().glob("*.json"))


class TestTeto:
    def test_fica_so_o_mais_novo(self):
        ids = _gravar(5)
        resultado = replay.podar(maximo=3, dias=0)

        assert resultado == {"mantidos": 3, "por_idade": 0, "por_teto": 2}
        assert _existentes() == ids[2:]

    def test_avaliacao_e_holdout_nao_sao_podados(self):
        """Sao curados: apagar ali muda a bateria que julga o mutation."""
        _gravar(3)
        avaliacao = _gravar(2, "avaliacao")
        holdout = _gravar(2, "holdout")

        replay.podar(maximo=1, dias=0)
        restantes = _existentes()
        assert set(avaliacao) <= set(restantes)
        assert set(holdout) <= set(restantes)
        assert sum(1 for r in restantes if r.startswith("des")) == 1


class TestPrazo:
    def test_traco_velho_sai_mesmo_abaixo_do_teto(self):
        _gravar(2)
        daqui_a_31_dias = time.time() + 31 * 86400

        resultado = replay.podar(maximo=500, dias=30, agora=daqui_a_31_dias)
        assert resultado["por_idade"] == 2
        assert _existentes() == []

    def test_dentro_do_prazo_fica(self):
        _gravar(2)
        assert replay.podar(maximo=500, dias=30)["mantidos"] == 2

    def test_prazo_zero_desliga_o_criterio(self):
        _gravar(2)
        assert replay.podar(maximo=500, dias=0, agora=time.time() + 10**9)["mantidos"] == 2


class TestQuandoPodar:
    def test_abaixo_do_teto_e_podado_ha_pouco_nao_faz_nada(self):
        _gravar(2)
        replay.podar()
        assert replay.podar_se_preciso() is None

    def test_passou_do_teto_poda(self, monkeypatch):
        from sentury.config import settings

        _gravar(4)
        replay.podar(maximo=500)            # marca a poda como recente
        monkeypatch.setattr(settings, "SENTURY_TRACOS_MAXIMO", 2, raising=False)

        assert replay.podar_se_preciso()["por_teto"] == 2

    def test_um_dia_depois_poda_mesmo_abaixo_do_teto(self):
        """Sem isto o prazo nunca venceria num corpus que fica abaixo do teto."""
        _gravar(1)
        replay.podar()
        amanha = time.time() + 25 * 3600
        assert replay.podar_se_preciso(agora=amanha) is not None


class TestListar:
    def test_limite_abre_so_os_mais_novos_e_devolve_em_ordem(self):
        ids = _gravar(5)
        assert [t.id for t in replay.listar(limite=2)] == ids[3:]

    def test_limite_vale_dentro_do_conjunto(self):
        _gravar(3)
        avaliacao = _gravar(3, "avaliacao", comeco=2_000_000)
        assert [t.id for t in replay.listar("desenvolvimento", limite=5)] != avaliacao
        assert len(replay.listar("desenvolvimento", limite=5)) == 3


class TestNoTurno:
    async def test_o_gravador_poda_depois_de_gravar(self, monkeypatch, tmp_path):
        import json

        from sentury.config import settings
        from tests.fixtures.setor_teste.dados import StoreTeste
        from sentury.harness.orchestrator import SenturyOrchestrator
        from sentury.harness.state import AnalysisState

        monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
        monkeypatch.setattr(settings, "SENTURY_GRAVAR_TRACOS", True, raising=False)
        monkeypatch.setattr(settings, "SENTURY_TRACOS_MAXIMO", 2, raising=False)

        class Llm:
            last_model = last_provider = "t"
            last_usage = last_tool_calls = None

            async def complete(self, messages, *a, **k):
                from robinbandit.chain import anotar_resposta

                texto = json.dumps({"action": "respond", "message": "ok"})
                anotar_resposta(texto=texto, tool_calls=None, modelo="t", provedor="t", ms=1)
                return texto

        llm = Llm()
        orq = SenturyOrchestrator(planner=llm, responder=llm,
                                  store=StoreTeste())
        for i in range(4):
            await orq.handle_message(AnalysisState.new(f"s{i}", "u"), f"oi {i}")

        assert len(replay.listar()) == 2
