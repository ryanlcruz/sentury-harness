"""O menu de skills mostra todos os grupos, sem emoji.

As skills do nucleo declaram o grupo sem emoji ('Diagnostico', 'Entrega') e a
ordem fixa tinha emoji ('📊 Diagnostico'): no generalista, o grupo nao casava
e as skills sumiam do menu em silencio.
"""
from sentury.harness.comando_de_barra import _format_skills_pretty, _grupo


def test_grupo_com_ou_sem_simbolo_e_o_mesmo():
    assert _grupo("📊 Diagnóstico") == _grupo("Diagnóstico") == "Diagnóstico"


def test_grupo_fora_da_ordem_aparece_e_nada_tem_emoji():
    texto = _format_skills_pretty([("dmaic", ""), ("plano-de-acao", ""), ("nova", "aprendida agora")])
    for skill in ("dmaic", "plano-de-acao", "nova"):
        assert skill in texto
    assert not any(ord(c) > 0x2600 for c in texto if c not in "—•")
