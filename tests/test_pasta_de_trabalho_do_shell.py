"""O shell trabalha na mesma pasta das ferramentas de arquivo.

Se o turno diz ao modelo que o diretório é a pasta de onde o servidor subiu, e
os arquivos moram na pasta de trabalho escolhida, o modelo usa o caminho errado:
lê e escreve dentro da instalação do Sentury, e cada passo pede autorização
para uma pasta que a pessoa nunca escolheu.
"""
from pathlib import Path

from sentury.tools import arquivos, shell


def _pasta_escolhida(tmp_path, monkeypatch) -> Path:
    trabalho = tmp_path / "trabalho"
    trabalho.mkdir()
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_WORKSPACE", str(trabalho))
    return trabalho.resolve()


def test_o_ambiente_informa_a_pasta_de_trabalho(tmp_path, monkeypatch):
    trabalho = _pasta_escolhida(tmp_path, monkeypatch)
    assert arquivos.raiz_de_trabalho() == trabalho
    assert Path(shell.ambiente()["diretorio"]) == trabalho


def test_o_comando_roda_na_pasta_de_trabalho(tmp_path, monkeypatch):
    trabalho = _pasta_escolhida(tmp_path, monkeypatch)
    (trabalho / "notas.txt").write_text("uma\nduas\n", encoding="utf-8")
    resultado = shell.executar(shell.ambiente()["listar"], habilitado=True, segundo_plano=False)
    assert resultado.get("ok"), resultado
    assert "notas.txt" in (resultado.get("saida") or "")
