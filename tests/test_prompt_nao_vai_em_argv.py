"""Texto grande não viaja pela linha de comando: em nenhum provedor.

O `CreateProcess` do Windows corta a linha de comando em **32.767 caracteres**. A
persona do Sentury sozinha tem 27.048: **83% do limite** antes de qualquer
pergunta ou histórico. O provedor do Claude Code montava
`claude -p <prompt> --append-system-prompt <sistema>`, com os dois como argumento.

Medido antes do conserto:

```
10.000 chars ->  6,4s   funciona
25.000 chars ->  6,5s   funciona
33.000 chars ->  FileNotFoundError, instantâneo
45.000 chars ->  FileNotFoundError, instantâneo
```

E o erro mentia: *"FileNotFoundError ao chamar o Claude Code"* parece binário
ausente. O binário estava lá; a linha de comando é que não cabia. Depois do
conserto, 80.000 caracteres passam em 10,4s.

## Por que o teste cobre todos, e não só o Claude

Consertar um provedor e descobrir o mesmo no próximo é o desperdício que este
arquivo existe para evitar. Hoje a situação é:

- **HTTP** (Gemini, Groq, OpenRouter, Mistral…): o texto vai no corpo JSON. Não
  existe esse limite.
- **Codex**: as mensagens vão por JSON-RPC no `stdin` do `app-server`. Já estava
  certo.
- **Claude Code**: era o único por `argv`.

O teto vale por processo, então o que precisa ser verdade é uma coisa só: nenhum
comando montado por provedor pode crescer com o tamanho da conversa.
"""
import pathlib

import pytest

from robinbandit.providers.claude_code_provider import ClaudeCodeProvider
from robinbandit.providers.codex_provider import CodexAppServerClient

LIMITE_WINDOWS = 32767
PROVEDORES = pathlib.Path(
    "sentury/plugins/robinbandit/src/robinbandit/providers"
)


def _tamanho(comando):
    """O que o sistema operacional vê: tudo junto, com os espaços."""
    return sum(len(a) for a in comando) + len(comando)


# ------------------------------------------------- Claude Code

def test_o_comando_do_claude_nao_cresce_com_o_prompt():
    p = ClaudeCodeProvider(models=["claude-haiku-4-5"])
    comando = p._comando("C:/temp/sistema.txt", "claude-haiku-4-5")
    assert _tamanho(comando) < 2000, comando


def test_o_comando_do_claude_aponta_para_o_arquivo_de_sistema():
    """O sistema vai por arquivo: é a rota que o próprio CLI oferece."""
    p = ClaudeCodeProvider(models=["x"])
    comando = p._comando("C:/temp/sistema.txt", "x")
    # Substitui a persona do CLI em vez de anexar: a dele descreve
    # ferramentas que aqui estao desligadas.
    assert comando[comando.index("--system-prompt-file") + 1] == "C:/temp/sistema.txt"
    assert "--system-prompt" not in comando


def test_o_prompt_do_claude_vai_por_stdin():
    """`-p` sem argumento lê de stdin. Se voltar a ter argumento, volta o teto."""
    p = ClaudeCodeProvider(models=["x"])
    comando = p._comando("", "x")
    i = comando.index("-p")
    assert comando[i + 1].startswith("--"), comando


# ------------------------------------------------- Codex

def test_o_comando_do_codex_nao_leva_mensagem():
    """Já estava certo: as mensagens vão por JSON-RPC no stdin do app-server."""
    comando = CodexAppServerClient()._command("codex.exe")
    assert _tamanho(comando) < 2000, comando
    assert not any(len(a) > 200 for a in comando), comando


# ------------------------------------------------- o alarme para o futuro

def test_so_dois_provedores_usam_processo():
    """Tripwire: um provedor de CLI novo tem que passar por aqui.

    Não é sobre o número. É que quem escrever o próximo provedor de linha de
    comando descubra este arquivo pelo teste vermelho, em vez de descobrir o
    limite em produção: que foi como nós descobrimos.
    """
    if not PROVEDORES.is_dir():
        pytest.skip("pacote do RobinBandit não está no caminho esperado")
    com_processo = sorted(
        f.name for f in PROVEDORES.glob("*_provider.py")
        if "subprocess" in f.read_text(encoding="utf-8", errors="ignore")
    )
    assert com_processo == ["claude_code_provider.py", "codex_provider.py"], com_processo
