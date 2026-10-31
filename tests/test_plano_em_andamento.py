"""`[-]` e em andamento no checklist.

Um item em andamento nao pode sumir do plano, senao a proxima tarefa apontada
passa a ser a errada; e `marcar(..., "fazendo")` grava `[-]` para quem abre o
arquivo ver o que esta em curso.
"""
import pytest

from sentury.memory import plano, workflow


@pytest.fixture(autouse=True)
def casa(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    yield


@pytest.fixture
def trabalho(tmp_path):
    return tmp_path / "projeto"


def _arquivo(trabalho):
    return trabalho / ".sentury" / "planos" / "obra" / "tarefas.md"


def _plano(trabalho):
    plano.criar("obra", "Plano escrito à mão", [
        "- [x] 1. Ler o formato",
        "- [-] 2. Aceitar o em andamento",
        "  - [ ] 2.1 Escrever o teste",
        "- [ ] 3. Marcar o plano de aterrar",
    ], trabalho=trabalho)


def test_item_em_andamento_nao_some_do_plano(trabalho):
    _plano(trabalho)
    tarefas = plano.ler("obra", trabalho)

    assert [t.id for t in tarefas] == ["1", "2", "2.1", "3"]
    dois = tarefas[1]
    assert dois.estado == "fazendo"
    assert dois.feito is False


def test_em_andamento_ainda_falta_e_e_a_proxima(trabalho):
    """Em andamento nao e feito: o plano nao fecha, e retomar volta nele."""
    _plano(trabalho)
    resumo = plano.resumo("obra", trabalho)

    assert resumo["faltam"] == 3
    assert resumo["proxima"]["id"] == "2"
    assert resumo["proxima"]["estado"] == "fazendo"


def test_marcar_fazendo_grava_o_traco(trabalho):
    _plano(trabalho)
    plano.marcar("obra", "3", "fazendo", trabalho=trabalho)

    assert "- [-] 3. Marcar o plano de aterrar" in _arquivo(trabalho).read_text(encoding="utf-8")


def test_o_traco_sai_quando_a_tarefa_termina_ou_volta(trabalho):
    _plano(trabalho)
    plano.marcar("obra", "2", "feito", trabalho=trabalho)
    plano.marcar("obra", "3", "fazendo", trabalho=trabalho)
    plano.marcar("obra", "3", "pendente", trabalho=trabalho)

    texto = _arquivo(trabalho).read_text(encoding="utf-8")
    assert "- [x] 2. Aceitar o em andamento" in texto
    assert "- [ ] 3. Marcar o plano de aterrar" in texto


def test_marcar_outra_tarefa_nao_apaga_o_em_andamento_escrito_a_mao(trabalho):
    """A reescrita das marcas passa por todas as linhas. Um `[-]` que so existe
    no Markdown nao pode virar `[ ]` porque outra tarefa mudou."""
    _plano(trabalho)
    plano.marcar("obra", "3", "feito", trabalho=trabalho)

    texto = _arquivo(trabalho).read_text(encoding="utf-8")
    assert "- [-] 2. Aceitar o em andamento" in texto
    assert "- [x] 3. Marcar o plano de aterrar" in texto


def test_em_andamento_com_sinal_de_portao_e_opcional(trabalho):
    plano.criar("sinais", "Sinais", [
        "- [-]! 1. Aprovar o deploy",
        "- [-]* 2. Medir depois",
    ], trabalho=trabalho)
    um, dois = plano.ler("sinais", trabalho)

    assert um.gate and um.estado == "fazendo"
    assert dois.opcional and dois.estado == "fazendo"


def test_passo_de_workflow_em_andamento_nao_some(trabalho):
    pasta = workflow.raiz_dos_workflows(trabalho) / "rotina"
    pasta.mkdir(parents=True)
    (pasta / "workflow.md").write_text(
        "# Rotina\n\n- [x] 1. Abrir\n- [-] 2. Conferir\n- [ ] 3. Fechar\n", encoding="utf-8",
    )

    assert workflow.ler("rotina", trabalho)["passos"] == ["1. Abrir", "2. Conferir", "3. Fechar"]
