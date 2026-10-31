"""A bancada do aprendizado julga certo antes de julgar o modelo.

Os casos carregam, o julgamento aprova e reprova pelos motivos certos, e um
caso inteiro roda com um modelo de mentira, sem tocar a casa da pessoa.
"""
import os

from sentury.evals import aprendizado as bancada
from tests.test_descoberta_multilingue import _Nativo

CHAVES = {"nada", "alguma", "memoria", "skill", "skill_contem", "sobra_uma_de"}


def test_os_casos_carregam_e_declaram_o_que_esperam():
    casos = bancada.carregar()
    assert len(casos) >= 8
    assert len({c["nome"] for c in casos}) == len(casos)
    for caso in casos:
        assert set(caso.get("espera") or {}) <= CHAVES, caso["nome"]
        assert caso.get("espera") or caso.get("nao_pode"), caso["nome"]
        # A pausa roda depois do turno: a conversa termina com a resposta.
        assert caso["conversa"][-1]["role"] == "assistant", caso["nome"]


def _caso(nome):
    return next(c for c in bancada.carregar() if c["nome"] == nome)


def test_julgamento_aprova_e_reprova_pelos_motivos_certos():
    memoria = {"tipo": "memoria", "nome": "respostas-curtas", "texto": "prefere no máximo 5 linhas"}
    assert bancada.julgar(_caso("correcao_de_formato"), [memoria])["ok"]
    assert not bancada.julgar(_caso("correcao_de_formato"), [])["ok"]
    assert bancada.julgar(_caso("conversa_comum"), [])["ok"]
    assert not bancada.julgar(_caso("conversa_comum"), [memoria])["ok"]
    lixo = {"tipo": "skill", "nome": "video", "texto": "o ffmpeg não funciona nesta máquina"}
    julgado = bancada.julgar(_caso("falha_de_ambiente"), [lixo])
    assert not julgado["ok"] and "não podia" in julgado["motivos"][0]
    assert bancada.julgar(_caso("falha_de_ambiente"), [])["ok"]


async def test_um_caso_inteiro_roda_numa_casa_temporaria():
    casa_antes = os.environ.get("SENTURY_HOME")
    modelo = _Nativo([
        ("memoria", {"acao": "salvar", "fato": "prefere respostas de no máximo 5 linhas: lê no celular",
                     "tipo": "pessoa"}),
        "Guardei a preferência de respostas curtas.",
    ])
    resultado = await bancada.rodar_caso(modelo, _caso("correcao_de_formato"))
    assert resultado["ok"], resultado
    assert resultado["ferramentas"] == ["memoria"]
    assert [e["tipo"] for e in resultado["escritas"]] == ["memoria"]
    assert os.environ.get("SENTURY_HOME") == casa_antes
