"""Snapshots endereçaveis por conteudo.

`snapshots/<hash>/<arquivo>`, uma copia por alteracao. O isolamento por
worktree diz o que a mutacao mudou; o snapshot diz como o arquivo estava antes,
sem depender do git da copia continuar vivo.
"""

from pathlib import Path

import pytest

from sentury.mutation import snapshot


@pytest.fixture(autouse=True)
def casa(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    yield


def test_guarda_e_le_o_conteudo_exato(tmp_path):
    alvo = tmp_path / "codigo.py"
    alvo.write_text("def somar(a, b):\n    return a + b\n", encoding="utf-8")

    r = snapshot.guardar(alvo, mutacao_id="AM-0001")
    assert r["ok"]
    assert snapshot.ler(r["hash"]).decode("utf-8").startswith("def somar")


def test_mesmo_conteudo_e_o_mesmo_hash(tmp_path):
    """Enderecar pelo conteudo significa que dois arquivos iguais ocupam um
    espaco so, e gravar duas vezes e idempotente."""
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("x = 1\n", encoding="utf-8")
    b.write_text("x = 1\n", encoding="utf-8")

    assert snapshot.guardar(a)["hash"] == snapshot.guardar(b)["hash"]
    assert len(snapshot.inventario()) == 1


def test_procedencia_diz_de_onde_cada_copia_veio(tmp_path):
    """O conteudo e compartilhado entre arquivos iguais, entao a procedencia
    fica do lado de fora dele: senao dois arquivos identicos brigariam pelo
    mesmo registro."""
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("igual\n", encoding="utf-8")
    b.write_text("igual\n", encoding="utf-8")
    h = snapshot.guardar(a, mutacao_id="AM-1")["hash"]
    snapshot.guardar(b, mutacao_id="AM-2")

    caminhos = {v["caminho"] for v in snapshot.procedencia(h)}
    assert len(caminhos) == 2
    assert {v["mutacao"] for v in snapshot.procedencia(h)} == {"AM-1", "AM-2"}


def test_restaurar_volta_o_arquivo(tmp_path):
    alvo = tmp_path / "vivo.py"
    alvo.write_text("versao boa\n", encoding="utf-8")
    bom = snapshot.guardar(alvo)["hash"]

    alvo.write_text("versao que quebrou tudo\n", encoding="utf-8")
    r = snapshot.restaurar(bom, alvo)

    assert r["ok"]
    assert alvo.read_text(encoding="utf-8") == "versao boa\n"


def test_restaurar_guarda_o_que_estava_la(tmp_path):
    """Desfazer nao pode ser porta de mao unica: se a restauracao foi engano, o
    que estava la ainda precisa existir."""
    # Bytes, nao texto: o snapshot preserva o arquivo exatamente como esta no
    # disco, e `write_text` traduz a quebra de linha no Windows.
    alvo = tmp_path / "vivo.py"
    alvo.write_bytes(b"primeira\n")
    primeira = snapshot.guardar(alvo)["hash"]
    alvo.write_bytes(b"segunda\n")

    r = snapshot.restaurar(primeira, alvo)
    assert r["anterior"], "nao guardou o conteudo que foi substituido"
    assert snapshot.ler(r["anterior"]) == b"segunda\n"


def test_restaurar_hash_inexistente_falha_sem_tocar_no_arquivo(tmp_path):
    alvo = tmp_path / "vivo.py"
    alvo.write_text("intacto\n", encoding="utf-8")

    r = snapshot.restaurar("naoexiste", alvo)
    assert not r["ok"]
    assert alvo.read_text(encoding="utf-8") == "intacto\n"


def test_conjunto_de_uma_mutacao_volta_arquivo_por_arquivo(tmp_path):
    """E esse mapa que permite voltar um arquivo so, em vez de reverter o
    trabalho inteiro."""
    arquivos = []
    for i in range(3):
        p = tmp_path / f"m{i}.py"
        p.write_text(f"antes {i}\n", encoding="utf-8")
        arquivos.append(str(p))

    r = snapshot.guardar_muitos(arquivos, mutacao_id="AM-7")
    assert r["ok"] and len(r["hashes"]) == 3

    Path(arquivos[1]).write_text("depois\n", encoding="utf-8")
    snapshot.restaurar(r["hashes"][arquivos[1]], arquivos[1])
    assert Path(arquivos[1]).read_text(encoding="utf-8") == "antes 1\n"


def test_snapshot_sobrevive_a_copia_sumir(tmp_path):
    """O ponto de existir alem da worktree: o conteudo continua legivel depois
    de o arquivo de origem ser apagado."""
    alvo = tmp_path / "some.py"
    alvo.write_bytes(b"conteudo que importa\n")
    h = snapshot.guardar(alvo)["hash"]
    alvo.unlink()

    assert snapshot.ler(h) == b"conteudo que importa\n"


def test_nao_guarda_o_que_nao_e_arquivo(tmp_path):
    assert not snapshot.guardar(tmp_path)["ok"]
    assert not snapshot.guardar(tmp_path / "nao-existe.py")["ok"]
