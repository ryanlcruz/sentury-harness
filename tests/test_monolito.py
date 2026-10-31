"""O `_handle_message_inner` e o `orchestrator.py` não crescem sem alguém ver.

Num bloco desse tamanho não dá para isolar o que mudou, e o teste que quebra
não aponta a causa. Passou do teto, extrai-se um módulo; o teto não sobe.
"""
import ast
from pathlib import Path

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "sentury" / "harness" / "orchestrator.py"

# O teto de hoje. Cada extracao baixa este numero no mesmo commit que a faz, e o
# commit diz antes -> depois.
TETO_DO_METODO = 48

# O arquivo inteiro tambem tem teto: extrair um bloco para um metodo vizinho
# no mesmo arquivo so muda o lugar do problema.
TETO_DO_ARQUIVO = 778


def _tamanho(nome: str) -> int:
    fonte = ORCHESTRATOR.read_text(encoding="utf-8", errors="replace")
    for no in ast.walk(ast.parse(fonte)):
        if getattr(no, "name", "") == nome:
            fim = max((getattr(x, "end_lineno", no.lineno) or no.lineno) for x in ast.walk(no))
            return fim - no.lineno + 1
    raise AssertionError(f"{nome} nao existe mais — atualize este teste")


def test_o_metodo_principal_nao_volta_a_crescer():
    tamanho = _tamanho("_handle_message_inner")
    assert tamanho <= TETO_DO_METODO, (
        f"_handle_message_inner esta com {tamanho} linhas, acima do teto de "
        f"{TETO_DO_METODO}. Extraia um bloco em vez de subir o teto — e se for "
        f"mesmo para subir, mude o numero aqui e diga por que no commit."
    )


def test_o_arquivo_nao_incha_no_lugar_do_metodo():
    linhas = len(ORCHESTRATOR.read_text(encoding="utf-8", errors="replace").splitlines())
    assert linhas <= TETO_DO_ARQUIVO, (
        f"orchestrator.py esta com {linhas} linhas, acima do teto de "
        f"{TETO_DO_ARQUIVO}. Mover o bloco para um metodo vizinho no mesmo "
        f"arquivo so muda o lugar do problema."
    )


def test_o_teto_acompanha_a_realidade():
    """Um teto muito acima do tamanho real nao protege nada: ele vira a folga
    onde o metodo cresce de novo sem o teste reclamar."""
    tamanho = _tamanho("_handle_message_inner")
    assert TETO_DO_METODO - tamanho <= 40, (
        f"o metodo tem {tamanho} linhas e o teto e {TETO_DO_METODO}: sobra folga "
        f"demais. Baixe o teto para perto do tamanho atual."
    )


def test_o_teto_do_arquivo_tambem_acompanha():
    """A mesma razao, no arquivo: folga grande depois de uma extracao deixa a
    feature seguinte caber inteira nela sem ninguem ver."""
    linhas = len(ORCHESTRATOR.read_text(encoding="utf-8", errors="replace").splitlines())
    assert TETO_DO_ARQUIVO - linhas <= 60, (
        f"o arquivo tem {linhas} linhas e o teto e {TETO_DO_ARQUIVO}: sobra folga "
        f"demais. Baixe o teto para perto do tamanho atual."
    )
