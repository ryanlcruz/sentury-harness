"""Remocao sensivel e recusada sem apelacao, em qualquer linguagem.

Vale com "permitir tudo" ligado e para cada forma de escrever a mesma
remocao: `rm -rf ~`, `rm -rf $HOME/*` e `rm -rf /etc` sao barrados como o
`rm -rf /` literal.

Apagar DENTRO da pasta do usuario continua liberado: `~/projeto/build` e
trabalho normal, e passa pela aprovacao de sempre.

Estes testes so chamam a funcao que decide. Nenhum comando roda.
"""
import pytest

from sentury.exec import hardline

SENSIVEIS = [
    # bash
    "rm -rf ~", "rm -rf ~/", "rm -rf ~/*", "rm -rf $HOME", 'rm -rf "$HOME"/*', "rm -rf ${HOME}",
    "rm -rf /etc", "rm /etc/passwd", "rm -rf /usr/lib", "rm -rf /", "rm -rf /*",
    "rm -rf /home/ryan", "rm -rf /Users/ryan/", "rm -rf /root", "cd /tmp && rm -rf /var/log",
    "find / -name '*.log' -delete", "find ~ -type f -delete", "shred -u /etc/shadow",
    # PowerShell e cmd
    "Remove-Item -Recurse -Force $HOME", "Remove-Item -Recurse -Force $env:USERPROFILE\\*",
    "Remove-Item C:\\Windows\\System32 -Recurse", "Remove-Item -Recurse -Force C:\\",
    "rd /s /q C:\\Users\\pessoa",'del /s /q "C:\\Program Files"',
    # Python e Node, dentro do executar_script
    "import shutil, os; shutil.rmtree(os.path.expanduser('~'))",
    "from pathlib import Path; import shutil; shutil.rmtree(Path.home())",
    "os.remove('/etc/hosts')",
    "fs.rmSync(os.homedir(), {recursive: true})",
]

LEGITIMOS = [
    "rm -rf ~/projeto/build", "rm -rf ./dist", "rm -rf node_modules", "rm -rf $HOME/.cache/pip",
    "rm -rf /tmp/sentury-teste", "rm -rf ./usr/local-build", "rm -rf ~/Downloads/lixo", "rm -f relatorio.csv",
    "Remove-Item -Recurse -Force .\\dist", "Remove-Item .\\saida\\*.tmp", "del saida.log",
    "find . -name '*.pyc' -delete", "shutil.rmtree('build')", "git rm --cached arquivo.txt",
    "ls /etc", "cat /usr/share/dict/words", "grep -r TODO ~/projeto", "echo ~", "cp -r ~/projeto /tmp/copia",
    "echo 'nao rode rm -rf ~'", "npm run build",
]


@pytest.mark.parametrize("comando", SENSIVEIS)
def test_remocao_sensivel_e_recusada(comando):
    assert hardline.recusar(comando), comando


@pytest.mark.parametrize("comando", LEGITIMOS)
def test_trabalho_normal_passa(comando):
    """Cada recusa indevida ensina a pessoa a desligar a trava."""
    assert hardline.recusar(comando) is None, comando


def test_dentro_de_um_script_de_varias_linhas():
    script = "set -e\ncd ~/projeto\nnpm run build\nrm -rf $HOME/*\n"
    assert hardline.recusar(script)


def test_comentario_nao_conta():
    assert hardline.recusar("# nunca faca rm -rf ~\nls") is None
