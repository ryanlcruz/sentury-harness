"""Leitura pelo shell roda sem cartao e com os argumentos inteiros.

- A pre-checagem do plano nao pede autorizacao para leitura como `git log`;
  pedir pararia o turno no cartao antes de rodar nada.
- No Windows, `--format="%h %s"` chega ao git como um argumento so.
- `onde_definido` recebe a pasta, para "onde esta definida X em
  <repositorio>" procurar ali e nao na pasta de trabalho.
"""
import asyncio
import os

import pytest

from sentury.exec.politica import comando_a_autorizar
from sentury.harness.state import AnalysisState
from sentury.tools import arquivos, shell
from sentury.tools.catalog import execute_tool


@pytest.fixture(autouse=True)
def _politica():
    shell.politica(recarregar=True)
    yield


def test_leitura_nao_passa_pela_pre_checagem():
    assert comando_a_autorizar("executar_comando", {"comando": 'git -C "C:/a b/repo" log -1'}) == ""
    assert comando_a_autorizar("executar_comando", {"comando": "git commit -m x"}) == "git commit -m x"


@pytest.mark.skipif(os.name != "nt", reason="a quebra de argumentos do Windows")
def test_aspas_no_meio_do_argumento_ficam_num_pedaco_so():
    partes = shell.partes_do_comando(r'git -C "C:\pasta com espaco\repo" log --format="%h %s"')
    assert partes == ["git", "-C", r"C:\pasta com espaco\repo", "log", "--format=%h %s"]


def test_onde_definido_procura_na_pasta_pedida(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text("def alvo():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(arquivos, "raiz_de_trabalho", lambda: tmp_path / "outra")
    monkeypatch.setattr(arquivos, "tudo_liberado", lambda: True)

    saida = asyncio.run(execute_tool(None, AnalysisState("s", "u"), "onde_definido",
                                     {"nome": "alvo", "pasta": str(repo)}))
    assert saida.get("total") == 1
