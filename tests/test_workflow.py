"""Workflow é a receita; plano é a execução.

Agenda dentro de uma tarefa do plano é o workflow tentando nascer no lugar
errado: são duas coisas, e cada uma tem o seu arquivo.
"""
import pytest

from sentury.memory import workflow


@pytest.fixture(autouse=True)
def _limpa(tmp_path, monkeypatch):
    """Cada teste com o seu disco: as execuções moram fora do trabalho, em
    SENTURY_HOME, e são indexadas por NOME: sem isolar, um teste herda as
    execuções do outro."""
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    return tmp_path


class TestDefinir:
    def test_grava_a_receita_legivel(self, tmp_path):
        r = workflow.criar("resumo-semanal", "o gestor lê na segunda",
                           "0 8 * * 1", ["Buscar o relatório", "Analisar", "Atualizar a base"],
                           trabalho=tmp_path)
        assert r["ok"] is True and r["passos"] == 3
        lido = workflow.ler("resumo-semanal", tmp_path)
        assert lido["gatilho"] == "0 8 * * 1"
        assert lido["porque"] == "o gestor lê na segunda"
        assert lido["passos"][0] == "1. Buscar o relatório"

    def test_sem_gatilho_continua_workflow_manual(self, tmp_path):
        """Cron e opcional: o processo pode ser iniciado e retomado manualmente."""
        r = workflow.criar("qualquer", "porque sim", "", ["um passo"], trabalho=tmp_path)
        assert r["ok"] is True
        assert r["gatilho"] == ""
        assert workflow.ler("qualquer", tmp_path)["gatilho"] == ""

    def test_sem_passo_nao_roda_nada(self, tmp_path):
        assert workflow.criar("vazio", "", "0 8 * * 1", [], trabalho=tmp_path)["ok"] is False

    def test_definir_nao_dispara(self, tmp_path):
        """Definir e rodar são momentos diferentes: confundi-los faz rotina
        rodar antes de alguém revisar."""
        workflow.criar("w", "p", "0 8 * * 1", ["passo"], trabalho=tmp_path)
        assert workflow.resumo("w", tmp_path)["total_de_execucoes"] == 0


class TestExecucoes:
    def _receita(self, tmp_path):
        workflow.criar("w", "p", "0 8 * * 1", ["passo"], trabalho=tmp_path)

    def test_cada_disparo_aponta_o_plano_que_nasceu(self, tmp_path):
        self._receita(tmp_path)
        workflow.registrar_execucao("w", "w-2026-09-22", estado="feito")
        r = workflow.resumo("w", tmp_path)
        assert r["total_de_execucoes"] == 1
        assert r["ultima"]["plano"] == "w-2026-09-22"

    def test_historico_e_append_only(self, tmp_path):
        """A execução que falhou é a evidência de que a rotina não funciona:
        e é exatamente ela que alguém precisa ver."""
        self._receita(tmp_path)
        workflow.registrar_execucao("w", "run-1", estado="falhou", nota="sem rede")
        workflow.registrar_execucao("w", "run-2", estado="feito")
        r = workflow.resumo("w", tmp_path)
        assert r["total_de_execucoes"] == 2 and r["falhas"] == 1

    def test_o_resumo_nao_despeja_um_ano_de_historico(self, tmp_path):
        self._receita(tmp_path)
        for i in range(workflow.EXECUCOES_NO_RESUMO + 5):
            workflow.registrar_execucao("w", f"run-{i}")
        r = workflow.resumo("w", tmp_path)
        assert len(r["execucoes"]) == workflow.EXECUCOES_NO_RESUMO
        assert r["total_de_execucoes"] == workflow.EXECUCOES_NO_RESUMO + 5


class TestListar:
    def test_lista_com_o_ultimo_disparo(self, tmp_path):
        workflow.criar("a", "p", "0 8 * * 1", ["x"], trabalho=tmp_path)
        workflow.criar("b", "p", "0 9 * * *", ["y"], trabalho=tmp_path)
        workflow.registrar_execucao("a", "run")
        nomes = {w["workflow"]: w for w in workflow.listar(tmp_path)}
        assert nomes["a"]["execucoes"] == 1 and nomes["b"]["execucoes"] == 0
        assert nomes["b"]["gatilho"] == "0 9 * * *"

    def test_sem_pasta_nao_quebra(self, tmp_path):
        assert workflow.listar(tmp_path / "vazio") == []

    def test_inexistente_responde_sem_explodir(self, tmp_path):
        assert workflow.resumo("nao-existe", tmp_path)["ok"] is False


def test_workflow_do_turno_vira_card_sem_sintaxe_do_arquivo(tmp_path, monkeypatch):
    from sentury.harness.bloco import plano_do_turno

    monkeypatch.setattr(
        workflow, "raiz_dos_workflows",
        lambda trabalho=None: tmp_path / ".sentury" / "workflows",
    )
    workflow.criar("buscar-vagas", "acompanhar vagas", "0 8 * * 1", ["Buscar", "Atualizar"])
    card = plano_do_turno([{
        "tool": "criar_workflow",
        "result": {"ok": True, "workflow": "buscar-vagas"},
    }])
    assert card["tipo"] == "workflow"
    assert card["gatilho"] == "0 8 * * 1"
    assert card["estado"] == "proposto"
    assert card["aprovado"] is False
    assert [t["titulo"] for t in card["tarefas"]] == ["Buscar", "Atualizar"]
