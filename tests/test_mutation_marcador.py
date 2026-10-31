"""Marcador que liga um trecho a mutacao que o criou."""
import pytest

from sentury.mutation import marcador, registro


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_MUTATION_DIR", str(tmp_path / "reg"))
    yield


def test_marcador_respeita_a_sintaxe_da_linguagem():
    """Marcador com sintaxe errada vira erro de compilacao no arquivo que ele
    deveria explicar."""
    assert marcador.montar("AM-0014", "agrega o NPS por regiao") == \
        "# mutinfo AM-0014 - agrega o NPS por regiao"
    assert marcador.montar("AM-0014", "faz x", ".ts").startswith("// mutinfo")
    with pytest.raises(ValueError, match="nao sei comentar"):
        marcador.montar("AM-0014", "faz x", ".exe")


def test_marcador_exige_id_valido_e_resumo():
    with pytest.raises(ValueError, match="invalido"):
        marcador.montar("dc037", "faz x")
    with pytest.raises(ValueError, match="nao explica"):
        marcador.montar("AM-0001", "   ")


def test_encontra_e_filtra_por_mutacao(tmp_path):
    (tmp_path / "a.py").write_text(
        "def f():\n    # mutinfo AM-0014 - troca o criterio de ativacao\n    return 1\n",
        encoding="utf-8")
    (tmp_path / "b.ts").write_text(
        "// mutinfo AM-0002 - some com o card vazio\nexport const x = 1;\n", encoding="utf-8")

    todos = marcador.encontrar(str(tmp_path))
    assert {m["mutacao"] for m in todos} == {"AM-0014", "AM-0002"}
    so_um = marcador.encontrar(str(tmp_path), "AM-0014")
    assert len(so_um) == 1 and so_um[0]["linha"] == 2


def test_marcador_sem_registro_e_orfao(tmp_path):
    """Ponteiro para mutacao inexistente mente sobre a origem do trecho."""
    (tmp_path / "a.py").write_text("# mutinfo AM-0404 - veio de lugar nenhum\n", encoding="utf-8")
    assert [o["mutacao"] for o in marcador.orfaos(str(tmp_path))] == ["AM-0404"]


def test_documentacao_junta_registro_e_codigo(tmp_path):
    m = registro.abrir(alvo="harness.reviewer", hipotese="ativar so em risco alto",
                       observacao="reviewer roda em tudo")
    (tmp_path / "r.py").write_text(
        f"# mutinfo {m.id} - decide a ativacao pelo risco\n", encoding="utf-8")

    doc = marcador.documentar(m.id, str(tmp_path))
    assert m.id in doc and "harness.reviewer" in doc
    assert "risco alto" in doc and "r.py:1" in doc
    assert "Nenhum marcador" not in doc

    assert "não está no registro" in marcador.documentar("AM-9999", str(tmp_path))
