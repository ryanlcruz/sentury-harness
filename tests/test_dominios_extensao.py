"""Pacote de setor com codigo proprio: o modelo de mod.

YAML declara o que o setor E; para o que ele FAZ de especifico nao ha
declaracao que baste. Quem ja tem uma API interna precisa de codigo.
"""
import asyncio

import pytest

from sentury.domains import extensao


@pytest.fixture(autouse=True)
def _limpo():
    extensao.esquecer()
    yield
    extensao.esquecer()


def _pacote(tmp_path, corpo, nome="teste"):
    pasta = tmp_path / nome
    pasta.mkdir(exist_ok=True)
    (pasta / "tools.py").write_text(corpo, encoding="utf-8")
    return pasta


BOM = '''
def registrar(api):
    def agora(argumentos):
        return {"ok": True, "recebeu": argumentos.get("x")}

    api.ferramenta("agora", agora, descricao="Diz a hora do sistema interno.")
'''


def test_pacote_publica_ferramenta_propria(tmp_path):
    publicadas = extensao.carregar(_pacote(tmp_path, BOM), "teste")
    assert publicadas == ["teste.agora"]
    saida = asyncio.run(extensao.executar("teste.agora", {"x": 1}))
    assert saida == {"ok": True, "recebeu": 1}


def test_nome_ganha_prefixo_do_setor(tmp_path):
    """Dois pacotes podem chamar a mesma coisa de `status`; sem o prefixo o
    segundo apagaria o primeiro em silencio."""
    extensao.carregar(_pacote(tmp_path, BOM, "um"), "um")
    extensao.carregar(_pacote(tmp_path, BOM, "dois"), "dois")
    assert set(extensao.publicadas()) == {"um.agora", "dois.agora"}


def test_ferramenta_sem_descricao_e_recusada(tmp_path):
    """E pela descricao que o modelo escolhe: sem ela a ferramenta existe e
    nunca e usada."""
    corpo = '''
def registrar(api):
    api.ferramenta("x", lambda a: None, descricao="  ")
'''
    assert extensao.carregar(_pacote(tmp_path, corpo), "teste") == []


def test_categoria_desconhecida_e_recusada(tmp_path):
    corpo = '''
def registrar(api):
    api.ferramenta("x", lambda a: None, descricao="algo", categoria="inventada")
'''
    assert extensao.carregar(_pacote(tmp_path, corpo), "teste") == []


def test_pacote_que_falha_no_meio_nao_deixa_meia_ferramenta(tmp_path):
    """Meia ferramenta e pior que nenhuma: o agente veria a primeira e
    concluiria que o pacote esta de pe."""
    corpo = '''
def registrar(api):
    api.ferramenta("boa", lambda a: {"ok": True}, descricao="essa funciona")
    raise RuntimeError("estourou no meio")
'''
    assert extensao.carregar(_pacote(tmp_path, corpo), "teste") == []
    assert extensao.publicadas() == {}


def test_codigo_quebrado_nao_derruba_o_agente(tmp_path):
    assert extensao.carregar(_pacote(tmp_path, "isto nao e python ((("), "teste") == []


def test_sem_funcao_registrar_nada_acontece(tmp_path):
    assert extensao.carregar(_pacote(tmp_path, "X = 1\n"), "teste") == []


def test_erro_da_ferramenta_vira_resposta(tmp_path):
    """O turno continua e o agente le o que aconteceu, em vez de morrer."""
    corpo = '''
def registrar(api):
    def explode(argumentos):
        raise ValueError("a API interna caiu")

    api.ferramenta("explode", explode, descricao="serve pra falhar")
'''
    extensao.carregar(_pacote(tmp_path, corpo), "teste")
    saida = asyncio.run(extensao.executar("teste.explode"))
    assert not saida["ok"] and "API interna caiu" in saida["erro"]


def test_ferramenta_de_setor_entra_no_harness(tmp_path):
    """Sem entrar no gate elas existiriam e o Harness recusaria todas."""
    import importlib

    extensao.carregar(_pacote(tmp_path, BOM), "teste")
    from sentury.harness import policy

    importlib.reload(policy)
    assert "teste.agora" in policy.KNOWN_TOOLS
    assert "teste.agora" in policy.READ_TOOLS
