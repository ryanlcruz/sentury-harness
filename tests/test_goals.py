"""O goal: um objetivo que o agente persegue ate cumprir.

O agente propoe e a pessoa aprova; o agente declara cumprido com evidencia e a
pessoa confirma. O modelo nao tem acao que ligue o executor
nem que encerre o goal sozinho.
"""
import pytest

from sentury.harness.state import AnalysisState
from sentury.memory import goals
from sentury.tools.catalog import execute_tool


@pytest.fixture(autouse=True)
def casa(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    yield


def _proposto(sessao="s1"):
    return goals.propor(sessao, "dono", "Zerar Pokemon Red", "creditos finais na tela",
                        ["insignia 1", "insignia 2"])


class TestModelo:
    def test_propor_exige_criterio(self):
        with pytest.raises(goals.GoalInvalido, match="criterio"):
            goals.propor("s1", "dono", "Zerar Pokemon Red", "")

    def test_nasce_proposto_e_so_liga_quando_aprovado(self):
        g = _proposto()
        assert g.estado == goals.PROPOSTO and g.iniciado_em == 0
        g = goals.aprovar(g.id, modo="dedicado")
        assert g.estado == goals.ATIVO and g.modo == "dedicado" and g.iniciado_em > 0

    def test_proposta_nova_substitui_a_nao_aprovada(self):
        velho = _proposto()
        novo = goals.propor("s1", "dono", "Zerar Pokemon Blue", "creditos")
        assert goals.carregar(velho.id).estado == goals.ABANDONADO
        assert goals.em_aberto("s1").id == novo.id

    def test_um_goal_aberto_por_conversa(self):
        goals.aprovar(_proposto().id)
        with pytest.raises(goals.GoalInvalido, match="ja tem um goal"):
            goals.propor("s1", "dono", "outra coisa", "outro criterio")
        # Outra conversa nao e afetada.
        assert goals.propor("s2", "dono", "outra coisa", "outro criterio").estado == goals.PROPOSTO

    def test_marco_sem_evidencia_e_recusado(self):
        g = goals.aprovar(_proposto().id)
        with pytest.raises(goals.GoalInvalido, match="evidencia"):
            goals.marcar(g.id, "insignia 1", "")
        g = goals.marcar(g.id, "Insignia 1", "print da insignia")
        assert g.marcos[0]["feito"] and g.publico()["marcos_feitos"] == 1

    def test_marco_fora_da_lista_entra_no_fim(self):
        g = goals.aprovar(_proposto().id)
        g = goals.marcar(g.id, "pegou o Pikachu", "print")
        assert g.marcos[-1]["titulo"] == "pegou o Pikachu" and g.marcos[-1]["feito"]

    def test_declarar_cumprido_espera_a_pessoa(self):
        g = goals.aprovar(_proposto().id)
        with pytest.raises(goals.GoalInvalido, match="evidencia"):
            goals.declarar_cumprido(g.id, "  ")
        g = goals.declarar_cumprido(g.id, "print dos creditos")
        assert g.estado == goals.AGUARDANDO and g.evidencia_final == "print dos creditos"
        assert goals.confirmar(g.id, True).estado == goals.CUMPRIDO
        assert goals.em_aberto("s1") is None

    def test_nao_cumpriu_volta_ao_trabalho_com_a_nota(self):
        g = goals.aprovar(_proposto().id)
        goals.declarar_cumprido(g.id, "print")
        g = goals.confirmar(g.id, False, "isso e o Hall da Fama, falta a Elite")
        assert g.estado == goals.ATIVO and g.evidencia_final is None
        assert "falta a Elite" in goals.mensagem_de_continuacao(g)

    def test_limite_de_turnos_e_de_horas(self):
        g = goals.propor("s1", "dono", "x", "y", limite_turnos=2, limite_horas=1)
        g = goals.aprovar(g.id)
        assert goals.limite_estourado(g) is None
        goals.contar_turno(g.id)
        g = goals.contar_turno(g.id)
        assert "2 turnos" in goals.limite_estourado(g)
        g.turnos = 0
        assert "1 h" in goals.limite_estourado(g, agora=g.iniciado_em + 3601)

    def test_retomar_estende_o_limite(self):
        g = goals.aprovar(goals.propor("s1", "dono", "x", "y", limite_turnos=5).id)
        goals.pausar(g.id, "limite")
        g = goals.retomar(g.id, mais_turnos=10)
        assert g.estado == goals.ATIVO and g.limite_turnos == 15

    def test_transicao_invalida_e_recusada(self):
        g = _proposto()
        with pytest.raises(goals.GoalInvalido):
            goals.pausar(g.id, "x")
        with pytest.raises(goals.GoalInvalido):
            goals.confirmar(g.id, True)

    def test_continuacao_se_marca_como_automatica(self):
        g = goals.contar_turno(goals.aprovar(_proposto().id).id)
        texto = goals.mensagem_de_continuacao(g)
        assert texto.startswith("[continuacao automatica do goal, turno 1 de 60]")
        assert "- [ ] insignia 1" in texto and "creditos finais" in texto


async def _goal(sessao="s1", **argumentos):
    return await execute_tool(None, AnalysisState.new(sessao, "dono"), "goal", argumentos)


class TestFerramenta:
    async def test_propor_devolve_o_goal_para_a_tela(self):
        r = await _goal(acao="propor", objetivo="Zerar Pokemon Red", criterio="creditos",
                        marcos="insignia 1\ninsignia 2")
        assert r["ok"] and r["goal"]["estado"] == "proposto"
        assert [m["titulo"] for m in r["goal"]["marcos"]] == ["insignia 1", "insignia 2"]

    async def test_sem_criterio_o_erro_volta_ao_modelo(self):
        r = await _goal(acao="propor", objetivo="Zerar")
        assert r["ok"] is False and "criterio" in r["erro"]

    async def test_proposto_nao_aceita_marco_nem_cumprido(self):
        """O modelo nao pula a aprovacao declarando progresso."""
        await _goal(acao="propor", objetivo="Zerar", criterio="creditos")
        r = await _goal(acao="cumprido", evidencia="print")
        assert r["ok"] is False and "proposto" in r["erro"]

    async def test_marco_e_cumprido_no_goal_ativo(self):
        r = await _goal(acao="propor", objetivo="Zerar", criterio="creditos")
        goals.aprovar(r["goal"]["id"])
        r = await _goal(acao="marco", titulo="insignia 1", evidencia="print")
        assert r["ok"] and r["goal"]["marcos_feitos"] == 1
        r = await _goal(acao="cumprido", evidencia="")
        assert r["ok"] is False
        r = await _goal(acao="cumprido", evidencia="print dos creditos")
        assert r["goal"]["estado"] == "aguardando_confirmacao"

    async def test_ver_sem_goal_e_acao_invalida(self):
        assert (await _goal(acao="ver"))["goal"] is None
        assert "nao existe" in (await _goal(acao="aprovar"))["erro"]
        assert (await _goal(acao="marco", titulo="x", evidencia="y"))["ok"] is False
