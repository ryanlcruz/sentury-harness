"""A saída de comando, script e código chega ao card como terminal.

O card mostrava 420 caracteres de um campo só: a falha do teste ficava depois
do corte e o erro sumia atrás da saída normal (ver tools/saida_da_tela.py).
"""
import asyncio
import threading

import pytest

from sentury.harness.emissor import EMISSOR
from sentury.tools import saida_da_tela as tela

PYTEST_FALHOU = [
    ("out", "collecting ... 71 items"),
    ("out", "........F...."),
    ("err", "E       AssertionError: assert ''"),
    ("out", "=========== 1 failed, 70 passed in 14.08s ==========="),
]


def test_as_linhas_saem_em_ordem_com_a_origem_e_o_codigo():
    resultado = {"codigo": 1, "saida": "ignorado", "erro": "ignorado", "linhas": PYTEST_FALHOU}
    montado = tela.montar("executar_comando", resultado)
    assert montado["linhas"][2] == ["err", "E       AssertionError: assert ''"]
    assert [o for o, _ in montado["linhas"]] == ["out", "out", "err", "out"]
    assert montado["codigo"] == 1
    assert montado["resumo"] == "1 de 71 testes falhou"


def test_sem_ordem_a_saida_vem_antes_do_erro():
    montado = tela.montar("executar_script", {"codigo": 0, "saida": "a\nb\n", "erro": "aviso\n"})
    assert montado["linhas"] == [["out", "a"], ["out", "b"], ["err", "aviso"]]
    assert montado["codigo"] == 0


def test_no_python_o_codigo_e_do_erro_e_nao_o_fonte():
    """`codigo` no resultado do Python e o fonte que rodou."""
    ok = tela.montar("executar_python", {"codigo": "print(1)", "saida": "1\n"})
    falhou = tela.montar("executar_python", {"codigo": "1/0", "erro": "ZeroDivisionError: division by zero"})
    assert ok["codigo"] == 0 and ok["linhas"] == [["out", "1"]]
    assert falhou["codigo"] == 1 and falhou["linhas"] == [["err", "ZeroDivisionError: division by zero"]]


def test_rodando_nao_tem_codigo():
    assert tela.montar("command_status", {"rodando": True, "codigo": None, "saida": "x"})["codigo"] is None


def test_quem_nao_e_terminal_nao_vai_ao_card():
    assert tela.montar("ler_arquivo", {"saida": "x"}) is None


def test_o_teto_guarda_as_ultimas_linhas_e_conta_as_cortadas():
    linhas = [("out", f"linha {i}") for i in range(tela.MAX_LINHAS + 50)]
    montado = tela.montar("executar_comando", {"codigo": 0, "linhas": linhas})
    assert len(montado["linhas"]) == tela.MAX_LINHAS
    assert montado["linhas"][-1] == ["out", f"linha {tela.MAX_LINHAS + 49}"]
    assert montado["cortadas"] == 50


def test_credencial_e_cor_de_terminal_nao_chegam_a_tela():
    montado = tela.montar("executar_comando", {"codigo": 0, "linhas": [
        ("out", "\x1b[32mok\x1b[0m"), ("out", "OPENAI_API_KEY=sk-abc123def456ghi789jkl012mno345"),
    ]})
    assert montado["linhas"][0] == ["out", "ok"]
    assert "sk-abc123def456ghi789jkl012mno345" not in montado["linhas"][1][1]


def test_resumo_so_quando_reconhece():
    assert tela.resumo([("out", "71 passed in 11.62s")]) == "71 de 71 testes passaram"
    assert tela.resumo([("out", "Found 3 errors in 2 files.")]) == "3 erros de tipo"
    assert tela.resumo([("out", "tudo certo")]) is None


def test_as_linhas_em_ordem_nao_vao_ao_modelo():
    resultado = {"saida": "a\n", "linhas": [("out", "a")], "linhas_cortadas": 0}
    tela.tirar_do_resultado(resultado)
    assert resultado == {"saida": "a\n"}


@pytest.mark.asyncio
async def test_ao_vivo_manda_em_lotes_e_para_depois_do_fim():
    eventos = []
    token = EMISSOR.set(eventos.append)
    try:
        ao_vivo = tela.AoVivo("executar_comando")

        def processo():
            for i in range(5):
                ao_vivo("out", f"linha {i}")

        thread = threading.Thread(target=processo)
        thread.start()
        thread.join()
        await asyncio.sleep(tela.AoVivo.INTERVALO + 0.1)
        ao_vivo("err", "tarde")
        ao_vivo.encerrar()
        ao_vivo("out", "depois do fim")
        await asyncio.sleep(tela.AoVivo.INTERVALO + 0.1)
    finally:
        EMISSOR.reset(token)

    parciais = [e for e in eventos if e["type"] == "saida_parcial"]
    assert parciais[0]["linhas"] == [["out", f"linha {i}"] for i in range(5)], "cinco linhas, um lote"
    todas = [l for e in parciais for l in e["linhas"]]
    assert ["err", "tarde"] in todas
    assert ["out", "depois do fim"] not in todas


@pytest.mark.asyncio
async def test_o_comando_chega_ao_card_pelo_catalogo(monkeypatch):
    """Ponta a ponta pelo catalogo: o evento final leva a saida e o codigo,
    e o resultado que vai ao modelo nao leva as linhas."""
    from sentury.config import settings
    from sentury.harness.state import AnalysisState
    from sentury.tools.catalog import execute_tool

    monkeypatch.setattr(settings, "SENTURY_SHELL", True)
    eventos = []
    token = EMISSOR.set(eventos.append)
    try:
        resultado = await execute_tool(
            None, AnalysisState.new("s-saida", "u"), "executar_comando", {"comando": "git --version"},
        )
    finally:
        EMISSOR.reset(token)

    assert resultado["ok"] is True, resultado
    assert "linhas" not in resultado and "linhas_cortadas" not in resultado
    final = [e for e in eventos if e["type"] == "saida"]
    assert len(final) == 1
    assert final[0]["ferramenta"] == "executar_comando"
    assert final[0]["codigo"] == 0
    assert any("git version" in texto for _, texto in final[0]["linhas"])


def test_o_passo_guarda_a_saida_final():
    from sentury.harness.processo_do_turno import criar_registrador

    processo = []
    registrar = criar_registrador(processo)
    registrar({"type": "tool_start", "id": "p1", "tool": "executar_comando", "title": "git"})
    registrar({"type": "saida_parcial", "ferramenta": "executar_comando", "linhas": [["out", "x"]]})
    registrar({"type": "saida", "ferramenta": "executar_comando", "linhas": [["out", "x"]], "codigo": 0,
               "cortadas": 0, "resumo": None})
    assert processo[0]["saida"] == {"linhas": [["out", "x"]], "codigo": 0, "cortadas": 0, "resumo": None}
