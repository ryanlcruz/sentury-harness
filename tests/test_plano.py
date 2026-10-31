"""O plano de trabalho sobrevive a sessao.

Um plano que so existe na conversa morre com ela. O checklist fica em Markdown
legivel, e o estado de execucao num JSON fora do repositorio.
"""
import tempfile
from pathlib import Path

import pytest

from sentury.memory import plano


@pytest.fixture(autouse=True)
def casa(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    yield


@pytest.fixture
def trabalho(tmp_path):
    return tmp_path / "projeto"


def _plano(trabalho):
    plano.criar("refatorar", "Refatorar o loop", [
        "- [ ] 1. Mapear os blocos",
        "  - [ ] 1.1 Listar os comentarios",
        "  - [ ]* 1.2 Medir cada bloco",
        "- [ ] 2. Extrair o fechamento",
        "  _Requisitos: o fechamento nao decide nada do turno_",
    ], contexto="O metodo tem 1139 linhas.", trabalho=trabalho)


def test_le_hierarquia_e_opcional(trabalho):
    """`- [ ]* 1.2` marca opcional. O plano distingue obrigatorio de desejavel,
    senao o agente corta o que nao devia."""
    _plano(trabalho)
    tarefas = plano.ler("refatorar", trabalho)

    assert [t.id for t in tarefas] == ["1", "1.1", "1.2", "2"]
    assert tarefas[1].nivel == 1
    assert tarefas[2].opcional is True
    assert tarefas[0].opcional is False


def test_a_tarefa_carrega_o_porque(trabalho):
    """`_Requisitos: ..._` liga o item a decisao que o justifica. Quem executar
    a tarefa dias depois sabe contra o que esta codando."""
    _plano(trabalho)
    dois = next(t for t in plano.ler("refatorar", trabalho) if t.id == "2")
    assert "nao decide nada" in dois.requisitos


def test_marcar_escreve_nos_dois_lugares(trabalho):
    """O JSON guarda quem tentou e quando; o Markdown continua legivel para uma
    pessoa abrir e entender sem ferramenta nenhuma."""
    _plano(trabalho)
    plano.marcar("refatorar", "1", "feito", session_id="s-1", trabalho=trabalho)

    texto = (trabalho / ".sentury" / "planos" / "refatorar" / "tarefas.md").read_text(encoding="utf-8")
    assert "- [x] 1. Mapear os blocos" in texto
    assert next(t for t in plano.ler("refatorar", trabalho) if t.id == "1").feito


def test_o_historico_e_append_only(trabalho):
    """Uma tentativa que falhou e evidencia, nao lixo a ser sobrescrito pela
    seguinte: e o Mutation precisa dela para avaliar."""
    _plano(trabalho)
    plano.marcar("refatorar", "1", "falhou", session_id="s-1", nota="51 testes cairam", trabalho=trabalho)
    plano.marcar("refatorar", "1", "feito", session_id="s-2", trabalho=trabalho)

    um = next(t for t in plano.ler("refatorar", trabalho) if t.id == "1")
    assert len(um.tentativas) == 2
    assert um.tentativas[0]["estado"] == "falhou"
    assert "51 testes" in um.tentativas[0]["nota"]
    assert um.estado == "feito"


def test_diz_qual_e_a_proxima(trabalho):
    """E a pergunta que o plano existe para responder."""
    _plano(trabalho)
    resultado = plano.marcar("refatorar", "1", "feito", trabalho=trabalho)

    assert resultado["proxima"]["id"] == "1.1"
    assert resultado["restantes"] == 2   # 1.1 e 2; a opcional nao conta


def test_opcional_nao_impede_o_plano_de_acabar(trabalho):
    _plano(trabalho)
    for tarefa in ("1", "1.1", "2"):
        plano.marcar("refatorar", tarefa, "feito", trabalho=trabalho)

    resumo = plano.resumo("refatorar", trabalho)
    assert resumo["faltam"] == 0
    assert resumo["proxima"] is None


def test_reescrever_preserva_a_prosa(trabalho):
    """Regenerar o Markdown a partir das tarefas apagaria o que alguem escreveu
    entre os itens: e essa prosa costuma ser o motivo."""
    _plano(trabalho)
    alvo = trabalho / ".sentury" / "planos" / "refatorar" / "tarefas.md"
    texto = alvo.read_text(encoding="utf-8")
    alvo.write_text(texto.replace("## Tarefas", "## Tarefas\n\nCuidado com o acoplamento escondido.\n"), encoding="utf-8")

    plano.marcar("refatorar", "2", "feito", trabalho=trabalho)

    depois = alvo.read_text(encoding="utf-8")
    assert "Cuidado com o acoplamento escondido." in depois
    assert "_Requisitos: o fechamento nao decide nada do turno_" in depois


def test_tarefa_inexistente_diz_quais_existem(trabalho):
    """Recusar sem dizer o que existe transfere o problema para quem chamou."""
    _plano(trabalho)
    resposta = plano.marcar("refatorar", "9.9", "feito", trabalho=trabalho)

    assert resposta["ok"] is False
    assert "1.1" in resposta["existentes"]


def test_estado_invalido_e_recusado(trabalho):
    _plano(trabalho)
    assert plano.marcar("refatorar", "1", "quase", trabalho=trabalho)["ok"] is False


def test_o_estado_nao_mora_no_repositorio(trabalho):
    """Um `git status` sujo a cada tarefa concluida tornaria o plano um estorvo.
    Quem tentou o que e desta maquina."""
    _plano(trabalho)
    plano.marcar("refatorar", "1", "feito", session_id="s-1", trabalho=trabalho)

    dentro = list((trabalho / ".sentury" / "planos" / "refatorar").iterdir())
    assert all(p.suffix != ".json" for p in dentro), [p.name for p in dentro]


def test_item_novo_escrito_a_mao_aparece_sem_historico(trabalho):
    """O Markdown e a verdade sobre QUAIS tarefas existem; o JSON, sobre o que
    aconteceu com elas."""
    _plano(trabalho)
    alvo = trabalho / ".sentury" / "planos" / "refatorar" / "tarefas.md"
    alvo.write_text(alvo.read_text(encoding="utf-8") + "- [ ] 3. Fechar o loop\n", encoding="utf-8")

    tres = next(t for t in plano.ler("refatorar", trabalho) if t.id == "3")
    assert tres.estado == "pendente"
    assert tres.tentativas == []


def test_listar_mostra_quanto_falta(trabalho):
    _plano(trabalho)
    plano.criar("outro", "Outro plano", ["Fazer uma coisa"], trabalho=trabalho)

    listagem = {p["plano"]: p for p in plano.listar(trabalho)}
    assert set(listagem) == {"refatorar", "outro"}
    assert listagem["refatorar"]["faltam"] == 3


def test_o_contexto_volta_com_o_resumo(trabalho):
    """Retomar sem o porque e reexecutar um checklist sem saber o alvo."""
    _plano(trabalho)
    assert "1139 linhas" in plano.resumo("refatorar", trabalho)["contexto"]
