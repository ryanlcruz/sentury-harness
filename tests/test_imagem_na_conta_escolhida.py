"""Imagem anexada com Reforçado ou Dedicado: a conta escolhida que enxerga
recebe a imagem; a do Dedicado que não enxerga recebe a descrição de quem
enxerga no Router, e a resposta continua sendo dela."""
import pytest

from robinbandit import RobinConfig, RobinGateway
from robinbandit.providers import ReinforcedProvider
from robinbandit.sentury import ChainProvider, clear_ultra_provider, use_ultra_provider

IMAGEM = "data:image/png;base64,AAAA"


class Prov:
    def __init__(self, name, resposta, capabilities=None):
        self.name = name
        self.last_model = f"{name}-modelo"
        self.resposta = resposta
        self.pedidos = []
        if capabilities is not None:
            self.capabilities = capabilities

    async def complete(self, messages, temperature=0.2, complexity=None):
        self.pedidos.append(messages)
        return self.resposta


def _tem_imagem(mensagens):
    return any(isinstance(m.get("content"), list)
               and any(str(p.get("type", "")).startswith("image") for p in m["content"])
               for m in mensagens)


def _cadeia(*provedores):
    config = RobinConfig.from_mapping({"providers": {
        "gemini": {"capabilities": ["vision"]}, "deepseek": {}}})
    return ChainProvider(list(provedores), router=RobinGateway(config))


@pytest.fixture
def escolhida():
    tokens = []

    def usar(*contas, nome="ultra_max"):
        grupo = ReinforcedProvider(list(contas), name=nome)
        tokens.append(use_ultra_provider(grupo))
        return grupo

    yield usar
    for token in reversed(tokens):
        clear_ultra_provider(token)


def _pedido():
    return [{"role": "user", "content": "o que diz este print?", "imagens": [{"nome": "a.png", "data_url": IMAGEM}]}]


@pytest.fixture(autouse=True)
def sem_cache():
    from robinbandit.routing import sentury

    sentury._DESCRICOES.clear()
    yield
    sentury._DESCRICOES.clear()


async def test_dedicado_que_enxerga_recebe_a_imagem(escolhida):
    conta = Prov("minha-conta", "resposta da conta", capabilities=["vision"])
    gemini = Prov("gemini", "descrição")
    escolhida(conta)
    assert await _cadeia(gemini, Prov("deepseek", "x")).complete(_pedido()) == "resposta da conta"
    assert _tem_imagem(conta.pedidos[0]) and gemini.pedidos == []


async def test_dedicado_que_nao_enxerga_recebe_a_descricao_e_responde(escolhida):
    conta = Prov("minha-conta", "resposta da conta", capabilities=[])
    gemini = Prov("gemini", "Um print do terminal com o erro ModuleNotFoundError: pydantic.")
    deepseek = Prov("deepseek", "não devia responder")
    escolhida(conta)
    cadeia = _cadeia(gemini, deepseek)
    assert await cadeia.complete(_pedido()) == "resposta da conta", "a resposta é da conta do Dedicado"
    assert _tem_imagem(gemini.pedidos[0]) and deepseek.pedidos == []
    recebido = conta.pedidos[0][-1]["content"]
    assert not _tem_imagem(conta.pedidos[0])
    assert "o que diz este print?" in recebido and "ModuleNotFoundError: pydantic" in recebido
    assert "gemini-modelo descreveu" in recebido
    # A segunda chamada do mesmo turno não descreve de novo.
    await cadeia.complete(_pedido())
    assert len(gemini.pedidos) == 1


async def test_dedicado_sem_ninguem_que_enxergue_diz_o_porque(escolhida):
    escolhida(Prov("minha-conta", "resposta", capabilities=[]))
    with pytest.raises(RuntimeError, match="Dedicado não lê imagem"):
        await _cadeia(Prov("deepseek", "x")).complete(_pedido())


async def test_reforcado_que_enxerga_fica_com_a_imagem(escolhida):
    conta = Prov("minha-conta", "resposta da conta", capabilities=["vision"])
    escolhida(conta, nome="ultra")
    gemini = Prov("gemini", "do router")
    assert await _cadeia(gemini).complete(_pedido()) == "resposta da conta"
    assert gemini.pedidos == []


async def test_reforcado_que_nao_enxerga_cai_no_router_com_a_imagem(escolhida):
    conta = Prov("minha-conta", "resposta da conta", capabilities=[])
    escolhida(conta, nome="ultra")
    gemini = Prov("gemini", "do router")
    assert await _cadeia(gemini).complete(_pedido()) == "do router"
    assert conta.pedidos == [] and _tem_imagem(gemini.pedidos[0])


async def test_no_grupo_so_a_conta_que_enxerga_recebe_a_imagem(escolhida):
    cega = Prov("conta-texto", "da cega", capabilities=[])
    ve = Prov("conta-visao", "da que vê", capabilities=["vision"])
    escolhida(cega, ve)
    assert await _cadeia(Prov("gemini", "x")).complete(_pedido()) == "da que vê"
    assert cega.pedidos == []


def test_o_grupo_declara_o_que_as_contas_fazem_e_o_router_le():
    grupo = ReinforcedProvider([Prov("a", "", capabilities=["vision"]), Prov("b", "")])
    assert grupo.capabilities == {"vision"}
    assert "vision" in RobinGateway(RobinConfig.from_mapping({"providers": {}})).capabilities_of(grupo)
