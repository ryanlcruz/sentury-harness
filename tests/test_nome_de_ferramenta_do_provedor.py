"""O provedor cola um prefixo no nome da ferramenta; a gente tira, sem gastar turno.

Alguns provedores emitem `default_api_listar_arquivos` quando as declarações vão
sem namespace. Consertar aqui é local e de graça; pedir ao modelo que refaça
custaria uma chamada.

O mesmo arquivo cobre o erro de pasta: a mensagem diz onde procurou, porque
caminho relativo resolve contra a pasta de trabalho e não contra o projeto.
"""
from sentury.harness.chamada_da_volta import ler_payload, payload_para_plano
from sentury.llm.tool_schemas import parse_native_tool_calls
from sentury.tools import arquivos


def _chamada(nome, args=None):
    return [{"function": {"name": nome, "arguments": args or {}}}]


# --------------------------------------------- o prefixo do provedor

def test_prefixo_do_gemini_cai_fora():
    saida = parse_native_tool_calls(_chamada("default_api_listar_arquivos"))
    assert saida[0]["tool"] == "listar_arquivos"


def test_prefixo_com_ponto_tambem():
    assert parse_native_tool_calls(_chamada("default_api.consultar_sql"))[0]["tool"] == "consultar_sql"


def test_prefixo_de_openai_tambem():
    assert parse_native_tool_calls(_chamada("functions.executar_python"))[0]["tool"] == "executar_python"


def test_nome_limpo_passa_intacto():
    assert parse_native_tool_calls(_chamada("listar_arquivos"))[0]["tool"] == "listar_arquivos"


def test_nao_come_pedaco_de_nome_parecido():
    """A regressão a evitar: cortar por `startswith` em nome legítimo."""
    saida = parse_native_tool_calls(_chamada("default_api_coisa_qualquer"))
    assert saida[0]["tool"] == "coisa_qualquer"
    intacto = parse_native_tool_calls(_chamada("defaults_do_setor"))
    assert intacto[0]["tool"] == "defaults_do_setor"


def test_os_argumentos_atravessam_a_limpeza():
    saida = parse_native_tool_calls(_chamada("default_api_listar_arquivos", {"caminho": "x"}))
    assert saida[0]["arguments"] == {"caminho": "x"}


# --------------------------------------------- e no caminho de TEXTO

# O conserto acima roda em `parse_native_tool_calls`, que só atende o canal
# nativo. Quando o modelo escreve o plano como texto, quem lê é o
# `payload_para_plano`; sem limpar o prefixo ali também, o turno termina em
# "ferramenta desconhecida: default_api:listar_arquivos".


def _do_texto(bruto):
    dados, contrato = ler_payload(bruto)
    assert contrato == "ok", contrato
    return payload_para_plano(dados)


def test_prefixo_cai_fora_no_json_em_texto():
    passos = _do_texto('{"action":"tool_call","tool":"default_api:listar_arquivos","arguments":{"caminho":"."}}')
    assert passos == [{"tool": "listar_arquivos", "arguments": {"caminho": "."}}]


def test_os_tres_separadores_no_caminho_de_texto():
    for bruto in ("default_api:ler_arquivo", "default_api.ler_arquivo", "default_api_ler_arquivo"):
        passos = _do_texto('{"plan":[{"tool":"%s","arguments":{}}]}' % bruto)
        assert passos[0]["tool"] == "ler_arquivo", bruto


def test_nome_legitimo_atravessa_o_texto_intacto():
    assert _do_texto('{"action":"tool_call","tool":"listar_arquivos","arguments":{}}')[0]["tool"] == "listar_arquivos"


def test_resposta_normal_nao_vira_chamada():
    """A regressão a evitar: mexer no leitor e transformar prosa em ferramenta."""
    assert _do_texto('{"action":"respond","message":"oi"}') == []


# --------------------------------------------- o erro que dá para consertar

def test_pasta_inexistente_diz_onde_procurou():
    erro = str(arquivos.listar("pasta_que_nao_existe_xyz").get("erro") or "")
    assert "procurei em" in erro, erro
    assert str(arquivos.raiz_de_trabalho()) in erro, erro
