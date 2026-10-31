"""A medição de uma candidata e a API da aba do Mutation.

Os portões rodam na cópia isolada e o resultado vai para o registro; promover é
decisão humana e a API não pula etapa do caminho declarado.
"""
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentury.mutation import api, ciclo, isolamento, medir, registro

VERDE = {
    "suite": (0, "3200 passed, 22 skipped in 90s"),
    "replay": (0, "  iguais a producao: 19\n  mudaram:           0\n  falharam:          0\nFIEL"),
    "evals": (0, "23/23 casos reais passaram."),
}


def _repo(tmp_path):
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
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_MUTATION_DIR", str(tmp_path / "registro"))
    monkeypatch.setenv("SENTURY_MUTATION_WORKTREES", str(tmp_path / "copias"))


def _executor(saidas):
    vistos = []

    def executar(comando, pasta, prazo):
        nome = next(n for n, argumentos, _ in medir.PORTOES if tuple(comando[1:]) == argumentos)
        vistos.append((nome, pasta))
        return saidas[nome]
    return executar, vistos


def _candidata(tmp_path, arquivo="core.py"):
    raiz = _repo(tmp_path)
    aberta = ciclo.propor(alvo="harness.teste", hipotese="valor maior responde melhor", repo=str(raiz))
    (isolamento.pasta_das_copias() / aberta["id"] / arquivo).parent.mkdir(parents=True, exist_ok=True)
    (isolamento.pasta_das_copias() / aberta["id"] / arquivo).write_text("VALOR = 2\n", encoding="utf-8")
    assert ciclo.construida(aberta["id"])["ok"]
    return raiz, aberta["id"]


def test_os_tres_portoes_rodam_na_copia_e_aprovam(tmp_path):
    _, mid = _candidata(tmp_path)
    executar, vistos = _executor(VERDE)
    medir.medir(mid, executar=executar)
    mutacao = registro.carregar(mid)
    assert mutacao.estado == "aprovada"
    assert [nome for nome, _ in vistos] == ["suite", "replay", "evals"]
    assert all(pasta.endswith(mid) for _, pasta in vistos), "mede a cópia, nunca o repositório vivo"
    assert mutacao.fitness["evals"] == {"ok": True, "passaram": 23, "total": 23, "segundos": 0}
    assert mutacao.fitness["replay"]["iguais"] == 19 and mutacao.fitness["mexe_em_teste"] == []


def test_reprovacao_guarda_o_nome_do_teste_que_falhou(tmp_path):
    """Os avisos do pytest saem depois do resumo. O registro precisa manter a linha
    FAILED, senão a mutação fica reprovada sem dizer qual teste caiu."""
    _, mid = _candidata(tmp_path)
    avisos = "PytestDeprecationWarning: asyncio_default_fixture_loop_scope is unset\n" * 60
    saida = ("FAILED tests/test_mesa.py::test_vez_da_mesa - AssertionError\n"
             "1 failed, 3323 passed in 173s\n" + avisos)
    executar, _ = _executor({**VERDE, "suite": (1, saida)})
    medir.medir(mid, executar=executar)
    suite = next(e for e in registro.historico(mid) if e["tipo"] == "portao_suite")
    assert "FAILED tests/test_mesa.py::test_vez_da_mesa" in suite["detalhe"]
    assert "1 failed, 3323 passed" in suite["detalhe"]
    assert registro.carregar(mid).fitness["suite"]["falharam"] == 1


def test_um_portao_vermelho_rejeita_com_o_motivo(tmp_path):
    _, mid = _candidata(tmp_path)
    executar, _ = _executor({**VERDE, "evals": (1, "21/23 casos reais passaram.")})
    medir.medir(mid, executar=executar)
    mutacao = registro.carregar(mid)
    assert mutacao.estado == "rejeitada" and "evals" in mutacao.motivo


def test_mexer_nos_testes_fica_marcado_para_quem_decide(tmp_path):
    """Os testes que rodam são os da cópia: afrouxar um deles passaria nos portões."""
    _, mid = _candidata(tmp_path, arquivo="tests/test_core.py")
    executar, _ = _executor(VERDE)
    medir.medir(mid, executar=executar)
    assert registro.carregar(mid).fitness["mexe_em_teste"] == ["tests/test_core.py"]


def test_so_se_mede_uma_candidata(tmp_path):
    raiz = _repo(tmp_path)
    aberta = ciclo.propor(alvo="harness.teste", hipotese="h", repo=str(raiz))
    assert "candidata" in medir.iniciar(aberta["id"])["erro"]


def test_diff_compara_com_a_baseline_mesmo_depois_de_commitar_na_copia(tmp_path):
    _, mid = _candidata(tmp_path)
    copia = isolamento.pasta_das_copias() / mid
    subprocess.run(["git", "add", "-A"], cwd=copia, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "trabalho"], cwd=copia, check=True, capture_output=True)
    diff = isolamento.diferenca(mid, base=registro.carregar(mid).baseline_commit, com_patch=True)
    assert diff["alterados"] == ["core.py"] and "+VALOR = 2" in diff["patch"]


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    raiz = _repo(tmp_path)
    monkeypatch.setattr(api, "_repo", lambda: str(raiz))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app), raiz


def test_api_propoe_lista_e_mostra_o_diff(cliente):
    http, _ = cliente
    aberta = http.post("/sentury/mutacoes", json={"alvo": "harness.teste", "hipotese": "h"}).json()
    copia = isolamento.pasta_das_copias() / aberta["id"]
    (copia / "core.py").write_text("VALOR = 3\n", encoding="utf-8")
    assert http.post(f"/sentury/mutacoes/{aberta['id']}/construida").status_code == 200
    lista = http.get("/sentury/mutacoes").json()
    assert lista["mutacoes"][0]["estado"] == "candidata" and lista["portoes"] == ["suite", "replay", "evals"]
    detalhe = http.get(f"/sentury/mutacoes/{aberta['id']}").json()
    assert "+VALOR = 3" in detalhe["diff"]["patch"]


def test_api_recusa_pular_etapa_e_promocao_sem_responsavel(cliente):
    http, _ = cliente
    aberta = http.post("/sentury/mutacoes", json={"alvo": "harness.teste", "hipotese": "h"}).json()
    assert http.post(f"/sentury/mutacoes/{aberta['id']}/promover", json={"decidido_por": "ryan"}).status_code == 409
    assert http.post(f"/sentury/mutacoes/{aberta['id']}/promover", json={"decidido_por": " "}).status_code == 400
    assert http.post("/sentury/mutacoes", json={"alvo": "x"}).status_code == 400


def test_api_descarta_proposta_e_remove_a_copia(cliente):
    http, _ = cliente
    aberta = http.post("/sentury/mutacoes", json={"alvo": "harness.teste", "hipotese": "h"}).json()
    assert http.post(f"/sentury/mutacoes/{aberta['id']}/descartar", json={"motivo": "outra ideia"}).status_code == 200
    assert registro.carregar(aberta["id"]).estado == "descartada"
    assert not (isolamento.pasta_das_copias() / aberta["id"]).exists()
