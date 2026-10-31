"""Ajustes que precisam valer antes de qualquer coisa ser importada.

O pytest lê este arquivo na raiz antes de abrir os processos paralelos do
`-n`, então o que for definido aqui vale também para eles.
"""
from __future__ import annotations

import os

# Caminho com acento (ex.: "Área de Trabalho") mata o `-n` do xdist: o
# `execnet` abre o trabalhador pela codificação ANSI do console, o nome não
# sobrevive e a rodada inteira morre com EOFError antes do primeiro teste.
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
# A suite legada testa o sandbox em processo. A fronteira de processo tem uma
# bateria propria que a liga explicitamente; assim os dois modos nao se misturam
# por acidente e a aplicacao continua com o default seguro ligado.
os.environ.setdefault("SENTURY_PY_CHILD", "false")
# Gravar traco e o padrao da aplicacao, nao da suite: 1779 testes chamando
# `handle_message` encheriam `~/.sentury/tracos` de lixo e cobrariam a
# escrita em disco de cada um. A bateria do replay liga explicitamente.
os.environ.setdefault("SENTURY_GRAVAR_TRACOS", "false")

# Sem isto o hypothesis grava `.hypothesis/` na raiz a cada rodada. O caso que
# importa repetir fica escrito no próprio teste.
try:
    from hypothesis import settings

    settings.register_profile("sentury", database=None)
    settings.load_profile("sentury")
except ImportError:
    pass
