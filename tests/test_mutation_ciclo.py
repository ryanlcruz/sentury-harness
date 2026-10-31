"""O ciclo inteiro: abrir, isolar, avaliar, decidir, reverter."""
import subprocess

import pytest

from sentury.mutation import ciclo, isolamento, registro


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
    yield


def test_ciclo_completo_ate_promocao(tmp_path):
    raiz = _repo(tmp_path)
    aberta = ciclo.propor(alvo="harness.reviewer", hipotese="ativar so em risco alto",
                          observacao="reviewer roda em tudo", repo=str(raiz))
    assert aberta["ok"] and aberta["branch"].startswith("mutation/AM-0001")

    # O trabalho acontece na copia, nunca no vivo.
    copia = tmp_path / "copias" / aberta["id"]
    (copia / "core.py").write_text("VALOR = 2\n", encoding="utf-8")
    assert (raiz / "core.py").read_text(encoding="utf-8") == "VALOR = 1\n"

    construida = ciclo.construida(aberta["id"])
    assert construida["ok"] and "core.py" in construida["alterados"]

    ciclo.avaliar(aberta["id"])
    ciclo.concluir_avaliacao(aberta["id"], passou=True, fitness={"acerto": 0.93})
    promovida = ciclo.promover(aberta["id"], decidido_por="ryan")
    assert promovida["estado"] == "promovida"

    trilha = [e["tipo"] for e in registro.historico(aberta["id"])]
    assert "isolada" in trilha and "aprovacao_humana" in trilha


def test_copia_que_nao_mudou_nada_nao_e_candidata(tmp_path):
    """Pasta vazia esperando alguem perceber nao e mutacao."""
    raiz = _repo(tmp_path)
    aberta = ciclo.propor(alvo="harness.x", hipotese="alguma ideia", repo=str(raiz))
    recusado = ciclo.construida(aberta["id"])
    assert not recusado["ok"] and "nao mudou nada" in recusado["erro"]


def test_registro_dentro_do_repositorio_nao_suja_a_arvore(tmp_path, monkeypatch):
    """O registro mora no repositório e nasce antes da cópia. Se ele contasse
    como árvore suja, toda proposta seria descartada no mesmo instante."""
    raiz = _repo(tmp_path)
    monkeypatch.setenv("SENTURY_MUTATION_DIR", str(raiz / "registro"))
    primeira = ciclo.propor(alvo="harness.x", hipotese="alguma ideia", repo=str(raiz))
    segunda = ciclo.propor(alvo="harness.y", hipotese="outra ideia", repo=str(raiz))
    assert primeira["ok"] and segunda["ok"]

    # Trabalho de verdade fora do registro continua barrando.
    (raiz / "rascunho.py").write_text("x = 1\n", encoding="utf-8")
    assert not isolamento.arvore_limpa(str(raiz))


def test_promover_exige_responsavel(tmp_path):
    """Promocao sem responsavel registrado e o que a mediacao humana existe
    para impedir."""
    raiz = _repo(tmp_path)
    a = ciclo.propor(alvo="harness.y", hipotese="ideia", repo=str(raiz))
    (tmp_path / "copias" / a["id"] / "core.py").write_text("VALOR = 3\n", encoding="utf-8")
    ciclo.construida(a["id"])
    ciclo.avaliar(a["id"])
    ciclo.concluir_avaliacao(a["id"], passou=True, fitness={"acerto": 0.9})
    with pytest.raises(ValueError, match="responsavel"):
        ciclo.promover(a["id"], decidido_por="  ")


def test_reprovar_nao_joga_a_evidencia_fora(tmp_path):
    """Descartar na hora da ma noticia perde o resultado que custou mais caro."""
    raiz = _repo(tmp_path)
    a = ciclo.propor(alvo="harness.z", hipotese="ideia", repo=str(raiz))
    (tmp_path / "copias" / a["id"] / "core.py").write_text("VALOR = 4\n", encoding="utf-8")
    ciclo.construida(a["id"])
    ciclo.avaliar(a["id"])
    ciclo.concluir_avaliacao(a["id"], passou=False, fitness={"acerto": 0.4},
                             motivo="regressao", revisit_if=["modelo mudar"])

    assert (tmp_path / "copias" / a["id"]).exists(), "a copia sumiu na reprovacao"
    guardada = registro.carregar(a["id"])
    assert guardada.estado == "rejeitada" and guardada.revisit_if == ["modelo mudar"]


def test_reverter_tira_do_ar_e_mantem_o_aprendizado(tmp_path):
    raiz = _repo(tmp_path)
    a = ciclo.propor(alvo="harness.w", hipotese="ideia", repo=str(raiz))
    (tmp_path / "copias" / a["id"] / "core.py").write_text("VALOR = 5\n", encoding="utf-8")
    ciclo.construida(a["id"])
    ciclo.avaliar(a["id"])
    ciclo.concluir_avaliacao(a["id"], passou=True, fitness={"acerto": 0.95})
    ciclo.promover(a["id"], decidido_por="ryan")

    ciclo.reverter(a["id"], motivo="latencia subiu em producao", repo=str(raiz))
    guardada = registro.carregar(a["id"])
    assert guardada.estado == "revertida" and "latencia" in guardada.motivo
    assert not (tmp_path / "copias" / a["id"]).exists()
    # O branch fica: o que ela tentou continua sendo evidencia.
    branches = subprocess.run(["git", "branch", "--list"], cwd=raiz,
                              capture_output=True, text=True).stdout
    assert a["id"] in branches
    with pytest.raises(ValueError, match="motivo"):
        ciclo.reverter(a["id"], motivo="", repo=str(raiz))


def test_nao_se_apaga_copia_do_que_esta_em_andamento(tmp_path):
    raiz = _repo(tmp_path)
    a = ciclo.propor(alvo="harness.v", hipotese="ideia", repo=str(raiz))
    (tmp_path / "copias" / a["id"] / "core.py").write_text("VALOR = 6\n", encoding="utf-8")
    ciclo.construida(a["id"])
    ciclo.avaliar(a["id"])
    recusado = ciclo.limpar_copia(a["id"], repo=str(raiz))
    assert not recusado["ok"] and "em andamento" in recusado["erro"]


def test_falha_ao_isolar_nao_deixa_registro_orfao(tmp_path):
    """Registro apontando para copia inexistente e pior que registro nenhum."""
    solto = tmp_path / "solto"
    solto.mkdir()
    resultado = ciclo.propor(alvo="harness.u", hipotese="ideia", repo=str(solto))
    assert not resultado["ok"]
    assert registro.carregar(resultado["id"]).estado == "descartada"


def test_painel_ve_estado_e_copias_orfas(tmp_path):
    raiz = _repo(tmp_path)
    a = ciclo.propor(alvo="harness.t", hipotese="ideia", repo=str(raiz))
    geral = ciclo.estado_geral()
    linha = next(m for m in geral["mutacoes"] if m["id"] == a["id"])
    assert linha["estado"] == "proposta" and linha["copia"]

    # Copia sem registro tambem aparece: e sinal de rastro perdido.
    (tmp_path / "copias" / "AM-9999").mkdir(parents=True)
    assert "AM-9999" in ciclo.estado_geral()["copias_orfas"]
