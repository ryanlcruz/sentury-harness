"""A mutacao trabalha numa copia; o codigo vivo nunca e tocado."""
import subprocess

import pytest

from sentury.mutation import isolamento


def _repo(tmp_path):
    """Um repositorio de verdade, pequeno: worktree nao se testa com dubles."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    def git(*args):
        subprocess.run(["git", *args], cwd=raiz, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "teste@local")
    git("config", "user.name", "teste")
    (raiz / "core.py").write_text("VALOR = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "baseline")
    return raiz


@pytest.fixture(autouse=True)
def _copias_isoladas(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_MUTATION_WORKTREES", str(tmp_path / "copias"))
    yield


def test_copia_nasce_do_commit_e_nao_toca_o_vivo(tmp_path):
    raiz = _repo(tmp_path)
    criado = isolamento.criar("AM-0001", alvo="harness.reviewer", repo=str(raiz))
    assert criado["ok"], criado.get("erro")
    assert criado["branch"] == "mutation/AM-0001-harness-reviewer"

    copia = tmp_path / "copias" / "AM-0001"
    assert (copia / "core.py").read_text(encoding="utf-8") == "VALOR = 1\n"

    # Mexer na copia nao muda o original: e essa e a garantia inteira.
    (copia / "core.py").write_text("VALOR = 2\n", encoding="utf-8")
    assert (raiz / "core.py").read_text(encoding="utf-8") == "VALOR = 1\n"


def test_arvore_suja_impede_isolar(tmp_path):
    """Copia feita por cima de trabalho nao commitado nasce de uma baseline que
    nao existe em commit nenhum, e a comparacao depois nao significa nada."""
    raiz = _repo(tmp_path)
    (raiz / "core.py").write_text("VALOR = 99\n", encoding="utf-8")
    recusado = isolamento.criar("AM-0001", repo=str(raiz))
    assert not recusado["ok"] and "suja" in recusado["erro"]


def test_diferenca_mostra_o_que_mudou(tmp_path):
    raiz = _repo(tmp_path)
    isolamento.criar("AM-0002", repo=str(raiz))
    copia = tmp_path / "copias" / "AM-0002"
    (copia / "core.py").write_text("VALOR = 2\n", encoding="utf-8")
    (copia / "novo.py").write_text("# arquivo novo\n", encoding="utf-8")

    diff = isolamento.diferenca("AM-0002")
    assert diff["ok"] and diff["mudou"]
    assert "core.py" in diff["alterados"]
    # Arquivo novo tambem conta: senao uma mutacao que so ACRESCENTA passaria
    # como se nao tivesse mudado nada.
    assert "novo.py" in diff["novos"]


def test_descartar_e_o_rollback_do_que_nao_foi_promovido(tmp_path):
    raiz = _repo(tmp_path)
    isolamento.criar("AM-0003", repo=str(raiz))
    copia = tmp_path / "copias" / "AM-0003"
    (copia / "core.py").write_text("VALOR = 666\n", encoding="utf-8")

    assert isolamento.descartar("AM-0003", repo=str(raiz))["ok"]
    assert not copia.exists()
    # O vivo nunca foi tocado, entao nao ha o que desfazer nele.
    assert (raiz / "core.py").read_text(encoding="utf-8") == "VALOR = 1\n"
    # Descartar de novo nao e erro.
    assert isolamento.descartar("AM-0003", repo=str(raiz))["ok"]


def test_branch_da_rejeitada_sobrevive_ao_descarte(tmp_path):
    """Uma mutacao rejeitada e evidencia: apagar o que ela tentou junto com a
    pasta destroi o que se aprendeu com ela."""
    raiz = _repo(tmp_path)
    isolamento.criar("AM-0004", repo=str(raiz))
    isolamento.descartar("AM-0004", repo=str(raiz))

    branches = subprocess.run(["git", "branch", "--list"], cwd=raiz,
                              capture_output=True, text=True).stdout
    assert "mutation/AM-0004" in branches


def test_duas_copias_convivem(tmp_path):
    """Baseline e candidata ao mesmo tempo e o motivo de usar worktree."""
    raiz = _repo(tmp_path)
    assert isolamento.criar("AM-0005", repo=str(raiz))["ok"]
    assert isolamento.criar("AM-0006", repo=str(raiz))["ok"]
    assert {c["mutacao"] for c in isolamento.listar()} == {"AM-0005", "AM-0006"}
    # A mesma mutacao nao abre duas vezes.
    assert not isolamento.criar("AM-0005", repo=str(raiz))["ok"]


def test_fora_de_repositorio_recusa(tmp_path):
    solto = tmp_path / "solto"
    solto.mkdir()
    assert not isolamento.criar("AM-0007", repo=str(solto))["ok"]
