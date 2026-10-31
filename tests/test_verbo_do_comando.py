"""O verbo de `git -C <pasta> log` e `log`, na leitura e na permissao."""
import pytest

from sentury.tools import permissoes, shell


@pytest.fixture(autouse=True)
def _politica_do_repositorio():
    shell.politica(recarregar=True)
    yield
    shell.politica(recarregar=True)


def test_leitura_com_pasta_apontada_nao_pede_permissao():
    shell.validar('git -C "C:/pasta com espaco/repo" log -1 --format=%h')


def test_permissao_de_um_verbo_nao_cobre_outro_na_mesma_pasta():
    commit = permissoes.assinatura('git -C "C:/pasta com espaco/repo" commit -m x')
    push = permissoes.assinatura('git -C "C:/pasta com espaco/repo" push')
    assert commit == "git commit" and push == "git push"


@pytest.mark.parametrize("comando", [
    "git config core.fsmonitor calc.exe",
    "npm run build",
    "npm test",
])
def test_o_que_executa_codigo_nao_passa_como_leitura(comando):
    with pytest.raises(shell.ComandoRecusado):
        shell.validar(comando)


@pytest.mark.parametrize("comando,leitura", [
    ("python --version", True),
    ("node -v", True),
    ("python -v", False),
    ("python --version script.py", False),
    ("python -c print(1)", False),
])
def test_consultar_versao_nao_roda_codigo(comando, leitura):
    if leitura:
        shell.validar(comando)
    else:
        with pytest.raises(shell.ComandoRecusado):
            shell.validar(comando)
