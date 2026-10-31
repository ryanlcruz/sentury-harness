"""Trabalho lateral (compactar, título, resumo de página) vai para quem a pessoa
escolheu: o modelo da conversa ou um auxiliar. E não perde dados quando falha."""
import copy
from types import SimpleNamespace

import pytest

from sentury.llm import auxiliar
from sentury.harness.context_budget import ContextBudgetManager, Contextualizer
from sentury.harness.state import AnalysisState
from sentury.tools import web


@pytest.fixture(autouse=True)
def _casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))


class Modelo:
    def __init__(self, resposta):
        self.resposta = resposta
        self.pedidos = []

    async def complete(self, messages, **kwargs):
        self.pedidos.append((messages, kwargs))
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


def test_main_liga_compactacao_a_rota_auxiliar():
    from sentury import main

    assert main.ctx_budget.contextualizer.llm is main.auxiliar_llm
    assert main.auxiliar_llm is not main.responder_llm


async def test_motor_monta_rota_pelo_nome_e_reconstroi_apos_atualizar(monkeypatch):
    chamadas = []
    modelo = Modelo("resultado")

    def montar(config, nome, settings):
        chamadas.append((config, nome))
        return modelo

    monkeypatch.setattr(auxiliar, "build_route", montar)
    motor = auxiliar.MotorAuxiliar("config", SimpleNamespace(SENTURY_AUXILIARY_ROUTE="leve"))
    for _ in range(2):
        assert await motor.complete([{"role": "user", "content": "resuma"}]) == "resultado"
    assert chamadas == [("config", "leve")]
    assert modelo.pedidos[0][1]["reasoning_effort"] == "low"
    motor.invalidar()
    await motor.complete([])
    assert len(chamadas) == 2


async def test_motor_recusa_aviso_de_fallback(monkeypatch):
    modelo = Modelo("Nenhum provedor respondeu")
    modelo.last_provider = "aviso"
    modelo.providers = [SimpleNamespace(name="aviso", e_aviso=True)]
    monkeypatch.setattr(auxiliar, "build_route", lambda *a: modelo)
    motor = auxiliar.MotorAuxiliar(None, SimpleNamespace(SENTURY_AUXILIARY_ROUTE="auxiliar"))
    with pytest.raises(auxiliar.AuxiliarIndisponivel, match="aviso"):
        await motor.complete([])


async def test_compactacao_falha_sem_apagar_o_historico(monkeypatch, tmp_path):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    state = AnalysisState.new("compactacao-auxiliar", "usuario")
    state.history = [{"role": "user" if n % 2 == 0 else "assistant", "content": f"Conteúdo {n}"} for n in range(8)]
    antes = copy.deepcopy(state.history)
    estado_antes = copy.deepcopy(state.conversation_state)
    modelo = Modelo(auxiliar.AuxiliarIndisponivel("indisponível"))
    manager = ContextBudgetManager(Contextualizer(modelo), limit_messages=2, keep_last_n=2)
    assert await manager.manage(state) is False
    assert state.history == antes
    assert state.conversation_state == estado_antes


async def test_compactacao_do_app_chama_auxiliar_sem_usar_principal(monkeypatch, tmp_path):
    """Com o auxiliar escolhido, o modelo da conversa não compacta."""
    from sentury import main

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    leve = Modelo('{"human_summary":"Resumo pela rota auxiliar","conversation_state":{}}')
    principal = Modelo(AssertionError("o principal não compacta o histórico"))
    auxiliar.definir_modelo_lateral(auxiliar.AUXILIAR)
    monkeypatch.setattr(auxiliar, "build_route", lambda *a: leve)
    monkeypatch.setattr(main.auxiliar_llm, "rota_declarada", lambda: True)
    monkeypatch.setattr(main.auxiliar_llm, "atual", principal)
    main.auxiliar_llm.invalidar()
    state = AnalysisState.new("compactacao-real-do-app", "usuario")
    state.history = [{"role": "user" if n % 2 == 0 else "assistant", "content": f"Mensagem {n}"} for n in range(32)]
    assert await main.ctx_budget.manage(state) is True
    assert state.conversation_state.human_summary == "Resumo pela rota auxiliar"
    assert len(leve.pedidos) == 1 and principal.pedidos == []


async def test_titulo_usa_auxiliar_e_nao_chama_o_principal(monkeypatch):
    from sentury import main
    from sentury.memory.session_index import SessionIndex
    from sentury.memory.session_store import InMemorySessionStore

    store = InMemorySessionStore()
    index = SessionIndex(store)
    state = AnalysisState.new("titulo-auxiliar", "usuario")
    state.history = [{"role": "user", "content": "Organize meu projeto"},
                     {"role": "assistant", "content": "Vamos organizar"}]
    await index.remember(state)
    leve = Modelo("Organização do meu projeto")
    principal = Modelo(AssertionError("o principal não participa do título"))
    monkeypatch.setattr(main, "session_index", index)
    monkeypatch.setattr(main, "auxiliar_llm", leve)
    monkeypatch.setattr(main, "responder_llm", principal)
    await main._auto_title_session(state.session_id, state.user_id, "pedido", "resposta")
    meta = await index.get_meta(state.user_id, state.session_id)
    assert meta["title"] == "Organização do meu projeto" and meta["title_source"] == "ai"
    assert len(leve.pedidos) == 1 and principal.pedidos == []


@pytest.mark.parametrize("manual", [False, True])
async def test_titulo_existente_nao_e_perdido_quando_rota_falha(monkeypatch, manual):
    from sentury import main
    from sentury.memory.session_index import SessionIndex
    from sentury.memory.session_store import InMemorySessionStore

    index = SessionIndex(InMemorySessionStore())
    state = AnalysisState.new("titulo-falha", "usuario")
    state.history = [{"role": "user", "content": "Pedido original"}]
    anterior = await index.remember(state, title="Meu título" if manual else None,
                                   title_source="manual" if manual else None)
    leve = Modelo(auxiliar.AuxiliarIndisponivel("indisponível"))
    monkeypatch.setattr(main, "session_index", index)
    monkeypatch.setattr(main, "auxiliar_llm", leve)
    await main._auto_title_session(state.session_id, state.user_id, "pedido", "resposta")
    atual = await index.get_meta(state.user_id, state.session_id)
    assert atual["title"] == anterior["title"] and atual["title_source"] == anterior["title_source"]
    assert len(leve.pedidos) == (0 if manual else 1)


@pytest.mark.parametrize("falha", [False, True])
async def test_pesquisa_resume_so_pagina_longa_e_preserva_original(monkeypatch, falha):
    original = "Conteúdo importante 17. " * 900
    urls = ["https://exemplo.invalid/longo", "https://exemplo.invalid/curto"]
    dados = {urls[0]: {"ok": True, "url": urls[0], "titulo": "Longa", "texto": original, "links": [], "truncado": False},
             urls[1]: {"ok": True, "url": urls[1], "titulo": "Curta", "texto": "curto", "links": [], "truncado": False}}

    async def buscar(*a, **k):
        return {"ok": True, "resultados": [{"url": u, "titulo": "Página"} for u in urls]}

    async def ler(url, *a):
        return dados[url]

    leve = Modelo(auxiliar.AuxiliarIndisponivel("indisponível") if falha else "Resumo com o valor 17.")
    monkeypatch.setattr(web, "buscar", buscar)
    monkeypatch.setattr(web, "_ler_inteira", ler)
    monkeypatch.setattr(web, "_auxiliar", leve)
    monkeypatch.setattr(web, "_LIDAS", {})
    saida = await web.pesquisar("qual o valor?", None, paginas=2)
    longa, curta = saida["paginas"]
    assert len(leve.pedidos) == 1
    assert "<conteudo_de_terceiros>" in leve.pedidos[0][0][1]["content"]
    assert curta["texto"] == "curto" and curta["url"] == urls[1]
    assert longa["url"] == urls[0] and longa["titulo"] == "Longa"
    if falha:
        assert longa["texto"] == original[:web.MAX_TEXTO_POR_FONTE]
        assert "resumido" not in longa
    else:
        assert longa["texto"] == "Resumo com o valor 17." and longa["resumido"]
        assert web._LIDAS[urls[0]][1]["texto"] == original
        lida = await web.ler_pagina(urls[0])
        assert lida["texto"].startswith("Conteúdo importante 17.")


def test_padrao_e_o_modelo_da_conversa():
    """Sem escolha, quem resume é o modelo que responde: não depende de rota
    declarada e entende a conversa como ela foi."""
    assert auxiliar.modelo_lateral() == auxiliar.ATUAL


async def test_modelo_atual_compacta_pelo_principal(monkeypatch):
    principal = Modelo("resumo pelo principal")
    monkeypatch.setattr(auxiliar, "build_route", lambda *a: pytest.fail("a rota auxiliar não entra"))
    motor = auxiliar.MotorAuxiliar(SimpleNamespace(routes={}), SimpleNamespace(SENTURY_AUXILIARY_ROUTE="auxiliar"),
                                   atual=principal)
    assert await motor.complete([{"role": "user", "content": "resuma"}]) == "resumo pelo principal"


async def test_auxiliar_sem_rota_declarada_usa_o_router_sem_dedicado(monkeypatch):
    """Escolher o auxiliar sem declarar a rota não desliga a compactação: ela vai
    ao Router, e a conta do Reforçado e do Dedicado fica de fora."""
    from robinbandit.sentury import _suppress_ultra_ctx

    vistos = []

    class Principal(Modelo):
        async def complete(self, messages, **kwargs):
            vistos.append(_suppress_ultra_ctx.get())
            return "resumo pelo router"

    auxiliar.definir_modelo_lateral(auxiliar.AUXILIAR)
    monkeypatch.setattr(auxiliar, "build_route", lambda *a: pytest.fail("rota não declarada não se monta"))
    motor = auxiliar.MotorAuxiliar(SimpleNamespace(routes={}), SimpleNamespace(SENTURY_AUXILIARY_ROUTE="auxiliar"),
                                   atual=Principal(None))
    assert await motor.complete([]) == "resumo pelo router"
    assert vistos == [True]


async def test_trocar_a_escolha_vale_sem_reiniciar(monkeypatch):
    principal, leve = Modelo("principal"), Modelo("leve")
    monkeypatch.setattr(auxiliar, "build_route", lambda *a: leve)
    motor = auxiliar.MotorAuxiliar(SimpleNamespace(routes={"auxiliar": {}}),
                                   SimpleNamespace(SENTURY_AUXILIARY_ROUTE="auxiliar"), atual=principal)
    assert await motor.complete([]) == "principal"
    auxiliar.definir_modelo_lateral(auxiliar.AUXILIAR)
    assert await motor.complete([]) == "leve"


def test_escolha_invalida_e_recusada():
    with pytest.raises(ValueError):
        auxiliar.definir_modelo_lateral("qualquer")
    assert auxiliar.modelo_lateral() == auxiliar.ATUAL


def test_api_le_e_grava_a_escolha():
    from fastapi.testclient import TestClient
    from sentury import main

    cliente = TestClient(main.app)
    cabecalho = {"Authorization": f"Bearer {main.settings.SENTURY_API_TOKEN}"} if main.settings.SENTURY_API_TOKEN else {}
    assert cliente.get("/sentury/tarefas-laterais", headers=cabecalho).json()["modelo"] == "atual"
    gravado = cliente.put("/sentury/tarefas-laterais", json={"modelo": "auxiliar"}, headers=cabecalho)
    assert gravado.status_code == 200 and gravado.json()["modelo"] == "auxiliar"
    assert cliente.put("/sentury/tarefas-laterais", json={"modelo": "outro"}, headers=cabecalho).status_code == 422


async def test_cadeia_sem_esforco_recebe_o_pedido_sem_ele(monkeypatch):
    """A cadeia da conversa não aceita `reasoning_effort`; passar o argumento
    derrubava título, rascunho e resumo, que caíam no plano B sem aviso."""
    class Estrita:
        def __init__(self):
            self.pedidos = []

        async def complete(self, messages, temperature=0.2, complexity=None, tools=None):
            self.pedidos.append(messages)
            return "Título certo"

    estrita = Estrita()
    motor = auxiliar.MotorAuxiliar(SimpleNamespace(routes={}), SimpleNamespace(SENTURY_AUXILIARY_ROUTE=""), atual=estrita)
    assert await motor.complete([{"role": "user", "content": "oi"}]) == "Título certo"
    assert len(estrita.pedidos) == 1


async def test_cadeia_que_aceita_esforco_recebe_o_baixo():
    modelo = Modelo("ok")
    motor = auxiliar.MotorAuxiliar(SimpleNamespace(routes={}), SimpleNamespace(SENTURY_AUXILIARY_ROUTE=""), atual=modelo)
    await motor.complete([{"role": "user", "content": "oi"}])
    assert modelo.pedidos[0][1]["reasoning_effort"] == "low"


async def test_titulo_depois_da_resposta_usa_o_modo_da_conversa(monkeypatch):
    """O título roda depois da resposta, com o modo do turno já desligado. Sem
    religar a conta do modo, ele cairia no roteamento automático, que pode não
    estar configurado, e toda conversa ficaria com o começo da mensagem."""
    from robinbandit.sentury import active_ultra_tier
    from sentury import main
    from sentury.memory.session_index import SessionIndex
    from sentury.memory.session_store import InMemorySessionStore

    index = SessionIndex(InMemorySessionStore())
    state = AnalysisState.new("titulo-modo", "usuario")
    state.history = [{"role": "user", "content": "Organize meu projeto"},
                     {"role": "assistant", "content": "Vamos organizar"}]
    await index.remember(state)
    vistos = []

    class Leve(Modelo):
        async def complete(self, messages, **kwargs):
            vistos.append(active_ultra_tier())
            return await super().complete(messages, **kwargs)

    monkeypatch.setattr(main, "session_index", index)
    monkeypatch.setattr(main, "auxiliar_llm", Leve("Organização do projeto"))
    await main._auto_title_session(state.session_id, state.user_id, "pedido", "resposta",
                                   SimpleNamespace(name="ultra"))
    meta = await index.get_meta(state.user_id, state.session_id)
    assert vistos == ["ultra"] and meta["title_source"] == "ai"
    assert active_ultra_tier() is None
