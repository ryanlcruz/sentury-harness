"""A `Missao` chega ao modelo.

Ela existia (`memory/unidades.py`) e nenhuma ferramenta a usava. O case da vaga
tem 5 vagas x 4 fontes = 20 unidades: nao cabe num turno, e sem registrar,
abrir antes de agir e fechar com evidencia, o turno seguinte nao sabe onde o
anterior parou.
"""
import pytest

from sentury.harness.state import AnalysisState
from sentury.tools.catalog import execute_tool


@pytest.fixture(autouse=True)
def casa(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    yield


def _estado(sessao="sessao-1"):
    return AnalysisState.new(sessao, "dono")


async def _missao(**argumentos):
    return await execute_tool(None, _estado(), "missao", argumentos)


_VAGAS = [{"alvo": f"vaga-{v}", "item": fonte} for v in (1, 2) for fonte in ("site", "glassdoor")]


class TestRegistrar:
    async def test_entra_na_ordem_e_diz_o_que_falta(self):
        r = await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        assert r["ok"] and r["entraram"] == 4 and r["faltam"] == 4
        assert [(u["alvo"], u["item"]) for u in r["proximas"]][:2] == [("vaga-1", "site"), ("vaga-1", "glassdoor")]

    async def test_registrar_de_novo_nao_duplica(self):
        """O turno que retoma costuma registrar tudo de novo: nao pode dobrar."""
        await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        r = await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        assert r["entraram"] == 0 and r["total"] == 4

    async def test_aceita_alvo_e_item_numa_string(self):
        r = await _missao(acao="registrar", missao="m", unidades=["vaga-9::site"])
        assert r["proximas"][0] == {"alvo": "vaga-9", "item": "site", "estado": "pendente", "tentativas": 0}


class TestCiclo:
    async def test_aberta_e_nao_fechada_volta_ao_retomar(self):
        """Abrir grava ANTES de agir. Se o turno cai no meio, a unidade volta
        como a proxima: e nao some."""
        await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        await _missao(acao="abrir", missao="dossie", alvo="vaga-1", item="site")

        r = await _missao(acao="ver", missao="dossie")
        assert r["proximas"][0]["alvo"] == "vaga-1" and r["proximas"][0]["estado"] == "fazendo"
        assert r["faltam"] == 4

    async def test_feito_sem_evidencia_e_recusado(self):
        await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        await _missao(acao="abrir", missao="dossie", alvo="vaga-1", item="site")

        r = await _missao(acao="fechar", missao="dossie", alvo="vaga-1", item="site", estado="feito")
        assert r["ok"] is False and "evidencia" in r["erro"]

    async def test_feito_com_evidencia_sai_da_fila(self):
        await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        await _missao(acao="abrir", missao="dossie", alvo="vaga-1", item="site")

        r = await _missao(acao="fechar", missao="dossie", alvo="vaga-1", item="site",
                          estado="feito", evidencia="https://empresa.com/vagas/1", confianca=0.9)
        assert r["ok"] and r["faltam"] == 3
        assert r["unidade"]["evidencia"] == "https://empresa.com/vagas/1"

    async def test_descartar_nao_precisa_de_prova(self):
        """Vaga que nao serve e resultado bom, e nao ha URL do que nao existe."""
        await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        r = await _missao(acao="fechar", missao="dossie", alvo="vaga-2", item="site",
                          estado="descartada", nota="exige presencial")
        assert r["ok"] and r["faltam"] == 3


class TestRecusasQueExplicam:
    async def test_abrir_o_que_ja_fechou_manda_seguir(self):
        await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        await _missao(acao="fechar", missao="dossie", alvo="vaga-2", item="site", estado="descartada")

        r = await _missao(acao="abrir", missao="dossie", alvo="vaga-2", item="site")
        assert r["ok"] is False and "ja fechada" in r["erro"]

    async def test_abrir_o_que_nao_foi_registrado(self):
        await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        r = await _missao(acao="abrir", missao="dossie", alvo="vaga-7", item="site")
        assert r["ok"] is False and "registrar" in r["erro"]

    async def test_tres_quedas_vao_para_revisao(self):
        """A quarta tentativa numa unidade que morreu tres vezes e insistencia,
        nao persistencia."""
        await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        for _ in range(3):
            assert (await _missao(acao="abrir", missao="dossie", alvo="vaga-1", item="site"))["ok"]

        r = await _missao(acao="abrir", missao="dossie", alvo="vaga-1", item="site")
        assert r["ok"] is False and "revisao" in r["erro"]
        assert (await _missao(acao="ver", missao="dossie"))["faltam"] == 3

    async def test_acao_desconhecida(self):
        r = await _missao(acao="apagar", missao="dossie")
        assert "registrar, abrir, fechar ou ver" in r["erro"]


class TestNaMesa:
    async def test_ver_sem_nome_lista_as_missoes(self):
        await _missao(acao="registrar", missao="dossie", unidades=_VAGAS)
        await _missao(acao="registrar", missao="outra", unidades=["x::y"])

        r = await _missao(acao="ver")
        assert {m["missao"] for m in r["missoes"]} == {"dossie", "outra"}

    def test_e_do_motor_e_chega_ao_generalista(self, monkeypatch):
        from sentury.domains import escolha
        from sentury.llm.tool_schemas import build_tool_schemas

        monkeypatch.setattr(escolha, "ler", lambda *a, **k: "generalista")
        nomes = [s["function"]["name"] for s in build_tool_schemas() if "function" in s]
        assert "missao" in nomes

    def test_o_traco_que_usou_missao_nao_se_diz_repetivel(self):
        """O resultado depende do lote em disco: o replay de amanha ve outro."""
        from sentury.harness import gravacao_do_turno as grav

        assert "missao" in grav._nao_deterministas()
