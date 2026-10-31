"""A revisão do aprendizado sabe o que não aprender.

O caso mais perigoso: afirmação negativa sobre ferramenta ("consultar_sql não
funciona") endurece numa recusa que o agente cita contra si mesmo muito depois
de o problema ter sido resolvido.
"""
from sentury.harness.aprendizado import pergunta
from sentury.skills.escrita import nome_de_classe


def _norm(t):
    import unicodedata
    return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode("ascii")


def test_proibe_aprender_que_ferramenta_nao_funciona():
    p = _norm(pergunta())
    assert "ferramenta nao funciona" in p
    assert "contra si mesmo" in p and "meses" in p


def test_proibe_falha_de_ambiente_e_erro_transitorio():
    p = _norm(pergunta())
    assert "falha de ambiente" in p
    assert "transitorio" in p


def test_separa_skill_de_memoria_de_usuario():
    """Skill responde 'como se faz'; memória responde 'quem é a pessoa'."""
    p = _norm(pergunta())
    assert "memoria responde" in p and "skill responde" in p


def test_correcao_e_frustracao_sao_o_sinal_mais_forte():
    p = _norm(pergunta())
    assert "frustracao sao o sinal mais forte" in p
    assert "nao faca assim" in p


def test_nada_a_guardar_e_resposta_boa():
    """A revisão que empurra a agir enche as skills de lixo; o padrão é não salvar."""
    assert "nada a guardar" in _norm(pergunta())


def test_nome_de_artefato_do_dia_continua_barrado():
    assert not nome_de_classe("relatorio-julho")
    assert not nome_de_classe("fix-erro-sql")
    assert not nome_de_classe("caso-12345")
    assert nome_de_classe("analise-de-churn")
    assert nome_de_classe("auditoria-sla")
