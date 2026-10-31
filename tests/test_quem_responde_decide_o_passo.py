"""O passo único liga pelo provedor que vai RESPONDER, não pela cadeia.

Medido no benchmark, só no Claude (Dedicado, claude-haiku-4-5): o `complete`
da cadeia sempre tem `tools=`, então `passo_unico.ativo()` dizia sim. O Claude
Code não devolve chamada estruturada: escreveu o plano em JSON como texto, o
passo único tratou esse texto como a resposta final, o detector de truncamento
viu a cerca ```json e mandou replanejar. Seis voltas, zero ferramentas, e a
resposta entregue ao usuário foi uma cerca ```json vazia.

A outra metade: o provedor do Claude Code tem `**_ignorado` no `complete`, e
`**kwargs` era lido como "aceita tools=".
"""
from sentury.harness import passo_unico
from sentury.config import settings
from robinbandit.providers import ReinforcedProvider
from robinbandit.providers.claude_code_provider import ClaudeCodeProvider
from robinbandit.routing.chain import suporta_ferramentas
from robinbandit.routing.sentury import (
    ChainProvider, clear_ultra_provider, use_ultra_provider,
)


class _ComFerramentas:
    name = "nativo"
    models = ["m"]

    async def complete(self, messages, temperature=0.2, tools=None):
        return ""


class _SoKwargs:
    name = "engole"
    models = ["m"]

    async def complete(self, messages, temperature=0.2, **_ignorado):
        return ""


def _cadeia():
    return ChainProvider([_ComFerramentas()])


def test_kwargs_nao_prova_suporte():
    assert not suporta_ferramentas(_SoKwargs())
    assert suporta_ferramentas(_ComFerramentas())


def test_claude_code_entra_na_mesa_quando_ha_ferramenta():
    """Declarar `False` tirava o provedor da lista sempre que o turno mandava
    `tools=`: e o Dedicado NÃO tem fallback, então o modo ficava sem ninguém.

    O que mudou não foi a declaração: foi o provedor. `_chamadas_do_texto`
    traduz o JSON que ele escreve para o formato de `tool_calls`, que é o que
    faltava desde o começo. A causa da falha antiga era não devolver chamada
    estruturada; agora devolve.
    """
    assert ClaudeCodeProvider.supports_tools is True
    assert suporta_ferramentas(ReinforcedProvider([ClaudeCodeProvider()], name="ultra_max"))


def test_o_plano_em_texto_vira_chamada_e_nao_resposta():
    """A regressão que os testes antigos guardavam: o passo único tratava a
    cerca ```json como resposta final, o detector de truncamento mandava
    replanejar, e o usuário recebia uma cerca vazia depois de seis voltas.

    O que impede isso de voltar não é desligar o passo único: é o plano em
    texto ser reconhecido como plano.
    """
    from robinbandit.providers.claude_code_provider import _chamadas_do_texto

    resposta = (
        "Vou listar a pasta primeiro.\n\n"
        '```json\n{"plan":[{"tool":"listar_arquivos","arguments":{}}]}\n```'
    )
    chamadas = _chamadas_do_texto(resposta)
    assert chamadas and chamadas[0]["function"]["name"] == "listar_arquivos"


def test_no_dedicado_com_conta_nativa_o_passo_unico_liga(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    cadeia = _cadeia()
    token = use_ultra_provider(ReinforcedProvider([_ComFerramentas()], name="ultra_max"))
    try:
        assert passo_unico.ativo(cadeia)
    finally:
        clear_ultra_provider(token)


async def test_dedicado_so_com_conta_sem_ferramenta_ainda_responde():
    """Pular a conta sem ferramenta so faz sentido se outra do grupo tiver.
    Sozinha, ela e chamada sem `tools=`: senao ninguem responde o turno."""
    recebeu = {}

    class _Cli:
        name = "cli"
        models = ["m"]
        supports_tools = False

        async def complete(self, messages, temperature=0.2, **kwargs):
            recebeu.update(kwargs)
            return '{"plan": []}'

    grupo = ReinforcedProvider([_Cli()], name="ultra_max")
    resposta = await grupo.complete(
        [{"role": "user", "content": "oi"}],
        tools=[{"type": "function", "function": {"name": "x"}}],
    )
    assert resposta == '{"plan": []}'
    assert "tools" not in recebeu
