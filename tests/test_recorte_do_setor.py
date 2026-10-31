"""Os filtros que a conversa guarda saem das dimensões do setor ativo: o motor
não sabe que existe região, filial ou grupo."""
import inspect

from sentury.domains.escopo import usar_setor
from sentury.harness import execucao_do_passo
from sentury.harness.artefato_do_turno import chaves_de_recorte


def test_o_setor_declara_os_recortes(setor_teste):
    assert chaves_de_recorte() == ("grupo", "periodo_inicio", "periodo_fim")


def test_sem_setor_so_o_periodo():
    with usar_setor("generalista"):
        assert chaves_de_recorte() == ("periodo_inicio", "periodo_fim")


def test_o_passo_nao_crava_dimensao_de_setor():
    fonte = inspect.getsource(execucao_do_passo)
    assert "chaves_de_recorte()" in fonte and '"regiao"' not in fonte
