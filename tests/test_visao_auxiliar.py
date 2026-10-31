"""O print descrito por quem enxerga quando o provedor da frente não enxerga."""
import pytest

from sentury.config import settings
from sentury.harness import visao_auxiliar


class Provedor:
    def __init__(self, name):
        self.name = name


class Router:
    def __init__(self, enxergam, ordem=None):
        self.enxergam = set(enxergam)
        self.ordem = ordem

    def _capabilities(self, nome):
        return {"vision"} if nome in self.enxergam else set()

    def order(self, provedores):
        return self.ordem if self.ordem is not None else list(provedores)


class Cadeia:
    def __init__(self, nomes, enxergam, resposta="Tela do portal: botão Entrar em (700, 400).", falha=False):
        self.providers = [Provedor(n) for n in nomes]
        self.router = Router(enxergam)
        self.resposta, self.falha, self.pedidos = resposta, falha, []

    # A assinatura da cadeia de verdade, sem `**kwargs`: um argumento que ela
    # não aceita tem de quebrar aqui, não virar um except silencioso.
    async def complete(self, mensagens, temperature=0.2, complexity=None, profile=None, tools=None):
        self.pedidos.append(mensagens)
        if self.falha:
            raise RuntimeError("fora")
        return self.resposta

    async def descrever_com_quem_ve(self, pedido, urls, complexity=None):
        self.por_fora = (pedido, urls)
        return "Descrito pelo Router."


@pytest.fixture(autouse=True)
def limpa(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_COMPUTADOR_VISAO", "auto")
    yield
    visao_auxiliar.registrar(None)


def test_auto_descreve_quando_o_da_frente_nao_enxerga():
    visao_auxiliar.registrar(Cadeia(["deepseek", "gemini"], enxergam={"gemini"}))
    assert visao_auxiliar.modo() == "descricao"


def test_auto_fica_na_imagem_quando_o_da_frente_enxerga_ou_ninguem_enxerga():
    visao_auxiliar.registrar(Cadeia(["gemini", "deepseek"], enxergam={"gemini"}))
    assert visao_auxiliar.modo() == "imagem"
    visao_auxiliar.registrar(Cadeia(["deepseek", "groq"], enxergam=set()))
    assert visao_auxiliar.modo() == "imagem"


def test_pelo_gateway_do_robin_que_guarda_o_roteador_dentro():
    cadeia = Cadeia(["deepseek", "gemini"], enxergam={"gemini"})

    class Gateway:
        def __init__(self, router):
            self.router = router

        def order(self, provedores):
            return self.router.order(provedores)

    cadeia.router = Gateway(cadeia.router)
    visao_auxiliar.registrar(cadeia)
    assert visao_auxiliar.modo() == "descricao"


def test_a_configuracao_manda(monkeypatch):
    visao_auxiliar.registrar(Cadeia(["gemini"], enxergam={"gemini"}))
    monkeypatch.setattr(settings, "SENTURY_COMPUTADOR_VISAO", "descricao")
    assert visao_auxiliar.modo() == "descricao"
    monkeypatch.setattr(settings, "SENTURY_COMPUTADOR_VISAO", "imagem")
    visao_auxiliar.registrar(Cadeia(["deepseek", "gemini"], enxergam={"gemini"}))
    assert visao_auxiliar.modo() == "imagem"


async def test_descrever_manda_a_imagem_e_os_elementos():
    cadeia = Cadeia(["deepseek", "gemini"], enxergam={"gemini"})
    visao_auxiliar.registrar(cadeia)
    texto = await visao_auxiliar.descrever("data:image/png;base64,AAAA", 1456, 819, "1. botão «Entrar» em (700, 400)")
    assert texto.startswith("Tela do portal")
    mensagens = cadeia.pedidos[0]
    assert mensagens[0]["imagens"][0]["data_url"] == "data:image/png;base64,AAAA"
    assert "1456 x 819" in mensagens[0]["content"] and "«Entrar»" in mensagens[0]["content"]


class TestContaEscolhida:
    """Reforçado e Dedicado: a conta escolhida é a da frente."""

    @pytest.fixture
    def conta(self):
        from robinbandit.sentury import clear_ultra_provider, use_ultra_provider

        def usar(capacidades, nome="ultra_max"):
            prov = Provedor(nome)
            prov.capabilities = capacidades
            self.token = use_ultra_provider(prov)

        self.token = None
        yield usar
        if self.token is not None:
            clear_ultra_provider(self.token)

    def test_conta_que_enxerga_recebe_a_imagem(self, conta):
        conta(["vision"])
        visao_auxiliar.registrar(Cadeia(["deepseek", "gemini"], enxergam={"gemini"}))
        assert visao_auxiliar.modo() == "imagem"

    async def test_conta_que_nao_enxerga_recebe_a_descricao_do_router(self, conta):
        conta([])
        cadeia = Cadeia(["gemini", "deepseek"], enxergam={"gemini"})
        visao_auxiliar.registrar(cadeia)
        assert visao_auxiliar.modo() == "descricao", "o gemini na frente do Router não conta: a conta é a da frente"
        assert await visao_auxiliar.descrever("data:image/png;base64,AAAA", 10, 10) == "Descrito pelo Router."
        assert cadeia.pedidos == [] and cadeia.por_fora[1] == ["data:image/png;base64,AAAA"]


async def test_falha_devolve_nada_e_quem_chama_volta_para_a_imagem():
    visao_auxiliar.registrar(Cadeia(["deepseek", "gemini"], enxergam={"gemini"}, falha=True))
    assert await visao_auxiliar.descrever("data:image/png;base64,AAAA", 10, 10) is None


async def test_o_ver_entrega_a_descricao_e_nao_a_imagem(monkeypatch):
    from sentury.tools import computador
    from tests.test_computador import _no_turno, _state
    from tests.test_computador_elementos import ComElementos

    monkeypatch.setattr(computador, "_ESPERA_DEPOIS_DO_GESTO", 0)
    visao_auxiliar.registrar(Cadeia(["deepseek", "gemini"], enxergam={"gemini"}))
    computador.usar_backend(ComElementos())
    try:
        state = _state()
        r = await _no_turno(computador.executar({"acao": "ver"}, state))
        assert r["descricao"].startswith("Tela do portal") and getattr(state, "print_da_tela", None) is None
    finally:
        computador._limpar_para_testes()
        computador.usar_backend(None)


class TestContaPrimeiroRouterDepois:
    """O print vai à conta escolhida; se ela falhar com a imagem, o Router
    descreve e a mesma chamada é refeita em texto."""

    URL = "data:image/png;base64,iVBORw0KGgo="

    def _state(self):
        class State:
            print_da_tela = {"data_url": TestContaPrimeiroRouterDepois.URL, "largura": 800, "altura": 600}
        return State()

    async def test_conta_que_responde_fica_com_a_imagem(self):
        from sentury.harness.print_da_tela import anexar_print, chamar_com_print

        state, recebidas = self._state(), []

        async def chamar(msgs):
            recebidas.append(msgs)
            return "ok"

        msgs = anexar_print(state, [{"role": "user", "content": "abra o app"}])
        assert await chamar_com_print(state, msgs, chamar) == "ok"
        assert len(recebidas) == 1 and recebidas[0][-1]["imagens"]

    async def test_conta_que_falha_com_a_imagem_recebe_a_descricao_do_router(self, monkeypatch):
        from sentury.harness.print_da_tela import anexar_print, chamar_com_print

        cadeia = Cadeia(["claude_code", "gemini"], enxergam={"claude_code", "gemini"})
        monkeypatch.setattr(visao_auxiliar, "_llm", cadeia)
        monkeypatch.setattr(visao_auxiliar, "_escolhida_enxerga", lambda: True)
        state, recebidas = self._state(), []

        async def chamar(msgs):
            recebidas.append(msgs)
            if msgs[-1].get("imagens"):
                raise RuntimeError("a conta recusou a imagem")
            return "ok"

        msgs = anexar_print(state, [{"role": "user", "content": "abra o app"}])
        assert await chamar_com_print(state, msgs, chamar) == "ok"
        assert cadeia.por_fora[1] == [self.URL], "quem descreve é o Router, fora da conta"
        assert "imagens" not in recebidas[-1][-1] and "descrito em texto" in recebidas[-1][-1]["content"]
        assert state.print_da_tela is None, "o resto do turno segue com a descrição"

    async def test_sem_descricao_a_falha_sobe(self, monkeypatch):
        from sentury.harness.print_da_tela import anexar_print, chamar_com_print

        monkeypatch.setattr(visao_auxiliar, "_llm", None)
        state = self._state()

        async def chamar(msgs):
            raise RuntimeError("fora")

        with pytest.raises(RuntimeError):
            await chamar_com_print(state, anexar_print(state, [{"role": "user", "content": "x"}]), chamar)
