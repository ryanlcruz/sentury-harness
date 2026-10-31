"""Numero da resposta separado em: veio da evidencia, foi CALCULADO sobre
ela, ou ninguem explica de onde saiu.

Um balde so acusaria como invencao "11,5 pontos de diferenca" entre dois NPS
da mesa, e por isso o guard nao bloqueia: ele separa.
"""
from sentury.harness.grounding import classify_numbers

EVIDENCIA = "{'nps': -49.3, 'volume': 2009} {'nps': -37.8, 'volume': 990} {'pct_backlog': 45.4}"


def test_numero_da_evidencia_e_grounded():
    c = classify_numbers("O NPS do Sudeste e -49,3 com backlog de 45,4%.", EVIDENCIA)
    assert set(c["grounded"]) == {-49.3, 45.4}
    assert c["suspect"] == []


def test_diferenca_entre_dois_valores_e_derivada_nao_invencao():
    """O trabalho que a gente PEDE que ele faca nao pode ser tratado como
    fabricacao: -49,3 menos -37,8 da -11,5."""
    c = classify_numbers("A diferenca entre as regioes e de -11,5 pontos.", EVIDENCIA)
    assert -11.5 in c["derived"]
    assert c["suspect"] == []


def test_media_entre_dois_valores_tambem_e_derivada():
    c = classify_numbers("A media das duas regioes fica em -43,55.", EVIDENCIA)
    assert c["suspect"] == []


def test_numero_do_nada_fica_suspeito():
    """O que importa isolar: valor que nao esta na evidencia nem sai de conta
    sobre ela."""
    c = classify_numbers("A satisfacao media foi 4,7 e o churn projetado 12,8%.", EVIDENCIA)
    assert 4.7 in c["suspect"]
    assert 12.8 in c["suspect"]


def test_sem_evidencia_todo_decimal_e_suspeito():
    c = classify_numbers("O NPS fechou em -31,2.", "")
    assert c["suspect"] == [-31.2]


def test_resposta_sem_numero_nao_gera_ruido():
    c = classify_numbers("Vou consultar os indicadores.", EVIDENCIA)
    assert c == {"grounded": [], "derived": [], "suspect": []}
