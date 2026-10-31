"""'Nesta conversa' num script vale para os próximos scripts da conversa.

Cada script tem conteúdo novo, e a aprovação presa ao conteúdo virava uma
pergunta por passo: criar um conversor com testes parava seis vezes. Quem
escolhe "nesta conversa" aprova os scripts daquela conversa na pasta de
trabalho; o que apaga arquivo continua perguntando um a um.
"""
import pytest

from sentury.tools import permissoes as pm


@pytest.fixture
def scripts(tmp_path, monkeypatch):
    trabalho = tmp_path / "trabalho"
    trabalho.mkdir()
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_WORKSPACE", str(trabalho))
    # O caso é o computador pessoal: num servidor, código arbitrário pergunta
    # toda vez (ver test_acoes_criticas.py), e o CI roda num servidor Linux.
    from sentury.exec import criticas

    monkeypatch.setattr(criticas, "remoto", lambda: False)
    criados = {}
    for nome, corpo in (("cria.py", "open('a.txt', 'w').write('oi')\n"),
                        ("testa.py", "print('2 passed')\n"),
                        ("limpa.py", "import os\nos.remove('a.txt')\n")):
        (trabalho / nome).write_text(corpo, encoding="utf-8")
        criados[nome] = f'python "{trabalho / nome}"'
    for sessao in ("conversa-a", "conversa-b"):
        pm.limpar_sessao(sessao)
    yield criados
    for sessao in ("conversa-a", "conversa-b"):
        pm.limpar_sessao(sessao)


def test_o_cartao_diz_que_nesta_conversa_cobre_os_scripts(scripts):
    decisao = pm.avaliar(scripts["cria.py"], "conversa-a")
    assert decisao["precisa_perguntar"] and decisao.get("nesta_conversa") == "scripts"


def test_nesta_conversa_libera_o_proximo_script_da_mesma_conversa(scripts):
    pm.responder(scripts["cria.py"], "sessao", "conversa-a")
    assert pm.avaliar(scripts["testa.py"], "conversa-a")["permitido"]
    # Outra conversa continua perguntando.
    assert pm.avaliar(scripts["testa.py"], "conversa-b")["precisa_perguntar"]


def test_script_que_apaga_continua_perguntando(scripts):
    pm.responder(scripts["cria.py"], "sessao", "conversa-a")
    decisao = pm.avaliar(scripts["limpa.py"], "conversa-a")
    assert decisao["precisa_perguntar"]
    assert "nesta_conversa" not in decisao


def test_so_desta_vez_nao_libera_os_outros(scripts):
    pm.responder(scripts["cria.py"], "uma_vez", "conversa-a")
    assert pm.avaliar(scripts["testa.py"], "conversa-a")["precisa_perguntar"]
