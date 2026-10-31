"""Escrever plano com codigo produz o arquivo e nao produz o estado."""
import pytest

from sentury.tools.porta_do_plano import desvio


@pytest.mark.parametrize("tool, argumentos, esperado", [
    ("escrever_arquivo", {"caminho": ".sentury/planos/obra/tarefas.md"}, "criar_plano"),
    ("editar_arquivo", {"caminho": "C:/proj/.sentury/planos/obra/tarefas.md"}, "criar_plano"),
    ("escrever_arquivo", {"caminho": ".sentury/workflows/vagas/workflow.md"}, "criar_workflow"),
    ("executar_python", {"codigo": 'open(".sentury/planos/obra/tarefas.md", "w")'}, "criar_plano"),
    ("executar_script", {"conteudo": "echo x > .sentury/workflows/v/workflow.md"}, "criar_workflow"),
])
def test_recusa_a_porta_errada(tool, argumentos, esperado):
    recusa = desvio(tool, argumentos)
    assert recusa is not None
    assert recusa["recusado"] is True
    assert recusa["use"] == esperado
    # A recusa precisa NOMEAR a ferramenta certa: recusa sem saida vira o
    # modelo tentando a mesma coisa de outro jeito.
    assert "criar_plano" in recusa["erro"]


def test_caminho_com_barra_invertida():
    """No Windows o modelo escreve o caminho com a barra do sistema."""
    codigo = 'p = ".sentury' + chr(92) * 2 + 'workflows' + chr(92) * 2 + 'v"'
    assert (desvio("executar_python", {"codigo": codigo}) or {}).get("use") == "criar_workflow"


@pytest.mark.parametrize("tool, argumentos", [
    ("executar_python", {"codigo": "df.groupby('regiao').size()"}),
    ("escrever_arquivo", {"caminho": "relatorio.md"}),
    ("escrever_arquivo", {"caminho": "docs/planos-de-2026.md"}),
    ("ler_arquivo", {"caminho": ".sentury/planos/obra/tarefas.md"}),
    ("criar_plano", {"nome": "obra"}),
])
def test_deixa_passar_o_que_nao_e_a_porta_errada(tool, argumentos):
    assert desvio(tool, argumentos) is None
