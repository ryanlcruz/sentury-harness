"""Agentes residentes: manifesto, fila, orçamento, worker, escopo e a API da HQ."""
import asyncio
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentury.residentes import api as _api
from sentury.residentes import escopo, hq, identidade, orcamento, registro, tarefas, worker
from sentury.residentes import aparencia
from sentury.residentes import manifesto as _m

ATLAS = {"nome": "atlas", "papel": "agente de infraestrutura da VPS",
         "objetivo": "manter a VPS de pé e avisar quando algo sair do normal",
         "ferramentas": ["ler_arquivo", "executar_comando"]}


@pytest.fixture(autouse=True)
def casa_limpa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    worker.configurar(None)
    yield
    worker.configurar(None)


class TestManifesto:
    def test_valido_ganha_orcamento_padrao(self):
        agente = _m.validar(ATLAS)
        assert agente.nome == "atlas" and agente.estado == _m.DORMINDO
        assert agente.orcamento == _m.ORCAMENTO_PADRAO

    @pytest.mark.parametrize("mudanca, trecho", [
        ({"nome": "Atlas!"}, "nome"),
        ({"ferramentas": []}, "vazio"),
        ({"ferramentas": ["inventada"]}, "não existem"),
        ({"ferramentas": ["computador"]}, "não recebe"),
        ({"canais": ["whatsapp"]}, "canais"),
        ({"orcamento": {"usd_por_dia": 0}}, "maior que zero"),
        ({"objetivo": ""}, "obrigatório"),
    ])
    def test_recusa_com_motivo(self, mudanca, trecho):
        with pytest.raises(_m.ManifestoInvalido, match=trecho):
            _m.validar({**ATLAS, **mudanca})


class TestRegistro:
    def test_criar_monta_a_pasta_e_recusa_repetido(self):
        registro.criar(ATLAS, criado_por="ryan")
        assert registro.workspace_do("atlas").is_dir()
        assert [a.nome for a in registro.listar()] == ["atlas"]
        with pytest.raises(_m.ManifestoInvalido, match="já existe"):
            registro.criar(ATLAS)

    def test_aposentado_sai_da_lista_e_libera_o_nome(self):
        registro.criar(ATLAS)
        registro.aposentar("atlas")
        assert registro.listar() == []
        registro.criar(ATLAS)
        assert registro.carregar("atlas").estado == _m.DORMINDO

    def test_memoria_tem_teto(self, monkeypatch):
        registro.criar(ATLAS)
        monkeypatch.setattr(registro, "TETO_DA_MEMORIA", 120)
        for i in range(20):
            registro.anotar_memoria("atlas", f"nota número {i}")
        memoria = registro.ler_memoria("atlas")
        assert len(memoria) <= 121 and "nota número 19" in memoria and "nota número 0\n" not in memoria

    def test_nota_que_substitui_troca_a_do_mesmo_assunto(self):
        """O assunto reaberto e fechado de novo deixa uma nota só na memória."""
        registro.criar(ATLAS)
        registro.anotar_memoria("atlas", "Mesa, 'Corte': não cortar agora", substitui="Mesa, 'Corte':")
        registro.anotar_memoria("atlas", "outra coisa")
        registro.anotar_memoria("atlas", "Mesa, 'Corte': cortar um", substitui="Mesa, 'Corte':")
        memoria = registro.ler_memoria("atlas")
        assert memoria.count("Mesa, 'Corte'") == 1 and "cortar um" in memoria and "outra coisa" in memoria


class TestFila:
    def test_uma_de_cada_vez_por_agente(self):
        primeira = tarefas.enfileirar("atlas", "olhe o disco")
        tarefas.enfileirar("atlas", "olhe a memória")
        assert tarefas.proxima("atlas").id == primeira.id
        tarefas.comecar(primeira.id)
        assert tarefas.proxima("atlas") is None

    def test_tarefa_lida_da_memoria_e_relida_quando_muda(self):
        """A fila é lida a cada consulta da tela: a tarefa fica na memória, mas quem lê
        recebe uma cópia, e a mudança gravada no disco aparece na leitura seguinte."""
        tarefa = tarefas.enfileirar("atlas", "olhe o disco")
        primeira = tarefas.carregar(tarefa.id)
        primeira.pedido = "alterado sem gravar"
        assert tarefas.carregar(tarefa.id).pedido == "olhe o disco"
        tarefas.comecar(tarefa.id)
        assert tarefas.carregar(tarefa.id).estado == tarefas.RODANDO
        assert [t.id for t in tarefas.listar("atlas", (tarefas.RODANDO,))] == [tarefa.id]

    def test_gravacao_no_mesmo_instante_e_tamanho_nao_volta_a_versao_antiga(self, monkeypatch):
        """Duas gravações no mesmo tique do relógio, com o mesmo tamanho, têm a mesma data
        e o mesmo tamanho no disco; a leitura seguinte ainda precisa ver a última."""
        monkeypatch.setattr(tarefas.time, "time", lambda: 1000.0)
        tarefa = tarefas.enfileirar("atlas", "custo")
        tarefas.registrar_custo(tarefa.id, 0.01)
        assert tarefas.carregar(tarefa.id).custo_usd == 0.01
        arquivo = tarefas._pasta() / f"{tarefa.id}.json"
        antes = arquivo.stat()
        tarefas.registrar_custo(tarefa.id, 0.01)
        assert arquivo.stat().st_size == antes.st_size
        os.utime(arquivo, ns=(antes.st_atime_ns, antes.st_mtime_ns))
        assert tarefas.carregar(tarefa.id).custo_usd == 0.02

    def test_mesa_anda_enquanto_o_trabalho_roda(self):
        """O trabalho e a Mesa são faixas separadas: uma pesquisa longa rodando não
        segura a vez dele na conversa, e cada faixa segue uma tarefa por vez."""
        longa = tarefas.enfileirar("atlas", "pesquise o mercado")
        tarefas.comecar(longa.id)
        tarefas.enfileirar("atlas", "olhe a memória")
        vez = tarefas.enfileirar("atlas", "É a sua vez", "mesa:m1")
        assert tarefas.proxima("atlas", mesa=True).id == vez.id
        assert tarefas.proxima("atlas", mesa=False) is None
        tarefas.comecar(vez.id)
        assert tarefas.proxima("atlas", mesa=True) is None

    def test_falha_volta_para_a_fila_ate_o_limite(self):
        tarefa = tarefas.enfileirar("atlas", "olhe o disco")
        for _ in range(tarefas.MAX_TENTATIVAS - 1):
            tarefas.comecar(tarefa.id)
            assert tarefas.falhar(tarefa.id, "provedor fora").estado == tarefas.NA_FILA
        tarefas.comecar(tarefa.id)
        assert tarefas.falhar(tarefa.id, "provedor fora").estado == tarefas.FALHOU

    def test_recuperar_devolve_o_que_caiu_no_meio(self):
        tarefa = tarefas.enfileirar("atlas", "olhe o disco")
        tarefas.comecar(tarefa.id)
        assert tarefas.recuperar() == 1
        assert tarefas.carregar(tarefa.id).estado == tarefas.NA_FILA

    def test_continuacao_leva_a_resposta_da_pessoa(self):
        tarefa = tarefas.enfileirar("atlas", "reinicie o nginx")
        assert tarefas.mensagem_do_turno(tarefa) == "reinicie o nginx"
        tarefas.comecar(tarefa.id)
        tarefas.esperar(tarefa.id, "precisa da sua autorização: systemctl restart", pendente="systemctl restart")
        liberada = tarefas.devolver_a_fila(tarefa.id, "pode")
        mensagem = tarefas.mensagem_do_turno(liberada)
        assert "A pessoa respondeu: pode" in mensagem and "reinicie o nginx" in mensagem


class TestOrcamento:
    def test_corta_no_teto_de_custo(self):
        agente = registro.criar({**ATLAS, "orcamento": {"usd_por_dia": 0.5}})
        tarefa = tarefas.enfileirar("atlas", "x")
        tarefas.comecar(tarefa.id)
        tarefas.concluir(tarefa.id, "ok", custo_usd=0.6)
        assert "orçamento de hoje acabou" in orcamento.corte(agente)

    def test_ontem_nao_conta(self):
        agente = registro.criar({**ATLAS, "orcamento": {"usd_por_dia": 0.5}})
        tarefa = tarefas.enfileirar("atlas", "x")
        tarefas.comecar(tarefa.id)
        tarefas.concluir(tarefa.id, "ok", custo_usd=0.6)
        amanha = time.time() + 86_400
        assert orcamento.corte(agente, agora=amanha) is None


def _rodar(respostas):
    vistos = []

    async def rodar(agente, tarefa):
        vistos.append((agente.nome, tarefas.mensagem_do_turno(tarefa), escopo.agente_do_turno()))
        return respostas.pop(0)

    return rodar, vistos


async def _esperar_dormir(nome):
    for _ in range(200):
        if not worker.acordado(nome):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("o worker não dormiu")


class TestWorker:
    def test_roda_a_fila_e_volta_a_dormir(self):
        registro.criar(ATLAS)
        rodar, vistos = _rodar([{"message": "disco em 40%", "telemetry": {"custo_usd": 0.01}},
                                {"message": "memória ok"}])
        worker.configurar(rodar)
        terminadas = []
        worker.observar(terminadas.append)

        async def cenario():
            hq.pedir("atlas", "olhe o disco")
            hq.pedir("atlas", "olhe a memória")
            await _esperar_dormir("atlas")

        asyncio.run(cenario())
        feitas = tarefas.listar("atlas", (tarefas.FEITA,))
        assert [t.resposta for t in feitas] == ["disco em 40%", "memória ok"]
        assert feitas[0].custo_usd == 0.01
        assert registro.carregar("atlas").estado == _m.DORMINDO
        assert [v[1] for v in vistos] == ["olhe o disco", "olhe a memória"]
        # Fora do turno o contextvar não vaza; dentro, o agente estava vestido.
        assert vistos[0][2] is None and escopo.agente_do_turno() is None
        assert {t.id for t in terminadas} >= {t.id for t in feitas}

    def test_permissao_para_a_tarefa_e_a_resposta_retoma(self):
        registro.criar(ATLAS)
        rodar, vistos = _rodar([
            {"message": "preciso reiniciar", "permissao": {"comando": "systemctl restart"}},
            {"message": "reiniciado"},
        ])
        worker.configurar(rodar)

        async def cenario():
            tarefa = hq.pedir("atlas", "reinicie o nginx")
            await _esperar_dormir("atlas")
            esperando = tarefas.carregar(tarefa["id"])
            assert esperando.estado == tarefas.ESPERANDO and esperando.pendente == "systemctl restart"
            hq.responder(tarefa["id"], "uma_vez")
            await _esperar_dormir("atlas")
            return tarefa["id"]

        tarefa_id = asyncio.run(cenario())
        assert tarefas.carregar(tarefa_id).estado == tarefas.FEITA
        assert "A pessoa respondeu" in vistos[1][1]

    def test_pausado_nao_acorda(self):
        registro.criar(ATLAS)
        registro.pausar("atlas")
        rodar, vistos = _rodar([{"message": "x"}])
        worker.configurar(rodar)

        async def cenario():
            resposta = hq.pedir("atlas", "olhe o disco")
            await _esperar_dormir("atlas")
            return resposta

        assert "pausado" in asyncio.run(cenario())["aviso"]
        assert vistos == []


class TestEscopo:
    def test_schemas_e_policy_fecham_nas_ferramentas_do_agente(self):
        from sentury.harness.policy import SenturyHarness
        from sentury.harness.state import AnalysisState
        from sentury.llm.tool_schemas import build_tool_schemas

        agente = _m.validar(ATLAS)
        state = AnalysisState(session_id="agente:atlas", user_id="hq")
        fora = {e["function"]["name"] for e in build_tool_schemas() if "function" in e}
        assert "memoria_do_agente" not in fora
        assert not SenturyHarness().evaluate(state, "memoria_do_agente", "", {"acao": "ler"}).allowed
        with escopo.vestido(agente):
            dentro = {e["function"]["name"] for e in build_tool_schemas() if "function" in e}
            assert {"ler_arquivo", "executar_comando", "memoria_do_agente"} <= dentro
            assert "escrever_arquivo" not in dentro and "criar_agente" not in dentro
            recusa = SenturyHarness().evaluate(state, "escrever_arquivo", "", {"caminho": "a.txt"})
            assert not recusa.allowed and "atlas" in recusa.reason

    def test_shell_do_nucleo_so_vem_pelo_manifesto(self):
        from sentury.harness.policy import SenturyHarness
        from sentury.harness.state import AnalysisState
        from sentury.llm.tool_schemas import build_tool_schemas

        agente = _m.validar({**ATLAS, "ferramentas": ["memoria_do_agente"]})
        state = AnalysisState(session_id="agente:atlas", user_id="hq")
        with escopo.vestido(agente):
            dentro = {e["function"]["name"] for e in build_tool_schemas(set()) if "function" in e}
            assert "executar_comando" not in dentro and "executar_skill" not in dentro
            assert {"search_tools", "perguntar_usuario", "pedir_ferramenta"} <= dentro
            recusa = SenturyHarness().evaluate(state, "executar_comando", "", {"comando": "dir"})
            assert not recusa.allowed

    def test_vestir_troca_a_identidade_anterior(self):
        from sentury.harness.state import AnalysisState

        state = AnalysisState(session_id="agente:atlas", user_id="hq")
        agente = _m.validar(ATLAS)
        identidade.vestir(state, agente)
        identidade.vestir(state, agente, memoria="- o disco enche às sextas")
        marcadas = [m for m in state.history if m.get(identidade.MARCA)]
        assert len(marcadas) == 1 and "enche às sextas" in marcadas[0]["content"]

    def test_skills_do_manifesto_entram_carregadas_e_a_citada_so_no_turno(self):
        """O residente não carrega skill sozinho: as do manifesto entram em todo turno,
        logo depois da identidade, e a citada com /nome só no turno que a citou."""
        from sentury.harness.state import AnalysisState
        from sentury.residentes import skills

        with pytest.raises(_m.ManifestoInvalido, match="não estão instaladas"):
            _m.validar({**ATLAS, "skills": ["inventada"]})
        agente = _m.validar({**ATLAS, "skills": ["/Grafico"]})
        assert agente.skills == ["grafico"]
        state = AnalysisState(session_id="agente:atlas", user_id="hq")
        identidade.vestir(state, agente, mensagem="monte o deck com /apresentacao")
        assert state.history[0].get(identidade.MARCA) and "Suas skills" in state.history[0]["content"]
        carregadas = [m["content"] for m in state.history if m.get(skills.MARCA)]
        assert ["=== SKILL: grafico ===" in carregadas[0], "=== SKILL: apresentacao ===" in carregadas[1]] == [True, True]
        identidade.vestir(state, agente, mensagem="só o gráfico")
        carregadas = [m["content"] for m in state.history if m.get(skills.MARCA)]
        assert len(carregadas) == 1 and "=== SKILL: grafico ===" in carregadas[0]


class TestApi:
    def _cliente(self):
        app = FastAPI()
        _api.montar(app)
        return TestClient(app)

    def test_sem_token_a_hq_fica_desligada(self, monkeypatch):
        monkeypatch.delenv("SENTURY_HQ_TOKEN", raising=False)
        assert self._cliente().get("/hq/agents").status_code == 503

    def test_token_errado_nao_entra(self, monkeypatch):
        monkeypatch.setenv("SENTURY_HQ_TOKEN", "segredo")
        resposta = self._cliente().get("/hq/agents", headers={"Authorization": "Bearer outro"})
        assert resposta.status_code == 401

    def test_criar_pedir_e_acompanhar(self, monkeypatch):
        monkeypatch.setenv("SENTURY_HQ_TOKEN", "segredo")
        cliente = self._cliente()
        cabecalho = {"Authorization": "Bearer segredo"}
        criado = cliente.post("/hq/agents", json={"manifesto": ATLAS}, headers=cabecalho)
        assert criado.status_code == 201 and criado.json()["nome"] == "atlas"
        assert cliente.post("/hq/agents", json={"manifesto": ATLAS}, headers=cabecalho).status_code == 422
        tarefa = cliente.post("/hq/agents/atlas/tasks", json={"pedido": "olhe o disco"}, headers=cabecalho)
        assert tarefa.status_code == 201 and tarefa.json()["estado"] == tarefas.NA_FILA
        visto = cliente.get(f"/hq/tasks/{tarefa.json()['id']}", headers=cabecalho)
        assert visto.json()["pedido"] == "olhe o disco"
        assert cliente.post("/hq/agents/atlas/pausar", headers=cabecalho).json()["estado"] == _m.PAUSADO
        assert cliente.get("/hq/agents/fantasma", headers=cabecalho).status_code == 404

    def test_pedido_pela_api_acorda_o_residente(self, monkeypatch):
        """Acordar o residente cria a tarefa assíncrona dele no laço do servidor.
        Rota síncrona roda numa thread sem laço: a tarefa entrava na fila, a
        resposta era 500 e ninguém acordava para fazê-la."""
        monkeypatch.setenv("SENTURY_HQ_TOKEN", "segredo")
        rodar, _ = _rodar([{"message": "disco em 40%"}])
        worker.configurar(rodar)
        cabecalho = {"Authorization": "Bearer segredo"}
        with self._cliente() as cliente:
            cliente.post("/hq/agents", json={"manifesto": ATLAS}, headers=cabecalho)
            tarefa = cliente.post("/hq/agents/atlas/tasks", json={"pedido": "olhe o disco"}, headers=cabecalho)
            assert tarefa.status_code == 201
            for _ in range(300):
                if tarefas.listar("atlas", (tarefas.FEITA,)):
                    break
                time.sleep(0.01)
        assert [t.resposta for t in tarefas.listar("atlas", (tarefas.FEITA,))] == ["disco em 40%"]


class TestCriarAgente:
    def test_pede_o_cartao_mesmo_com_permitir_tudo(self):
        from sentury.harness.state import AnalysisState
        from sentury.residentes.ferramentas import executar
        from sentury.tools import permissoes

        permissoes.definir_permitir_tudo(True)
        state = AnalysisState(session_id="s1", user_id="ryan")
        pedido = asyncio.run(executar("criar_agente", dict(ATLAS), state))
        assert pedido["precisa_permissao"] and pedido["so_desta_vez"]
        assert "atlas" in pedido["motivo"] and registro.carregar("atlas") is None

        permissoes.responder("criar_agente atlas", "uma_vez", "s1")
        criado = asyncio.run(executar("criar_agente", dict(ATLAS), state))
        assert criado["ok"] and criado["hq"] == "local"
        assert registro.carregar("atlas").criado_por == "ryan"

    def test_manifesto_ruim_volta_o_erro_sem_cartao(self):
        from sentury.harness.state import AnalysisState
        from sentury.residentes.ferramentas import executar

        state = AnalysisState(session_id="s1", user_id="ryan")
        erro = asyncio.run(executar("criar_agente", {**ATLAS, "ferramentas": ["computador"]}, state))
        assert not erro["ok"] and "não recebe" in erro["erro"]


class TestAparencia:
    def test_familia_da_o_simbolo_e_o_nome_da_o_resto(self):
        agente = _m.validar({**ATLAS, "familia": "infraestrutura"})
        assert agente.aparencia["acessorios"]["cabeca"] == "capacete"
        assert agente.aparencia["sugeridos"] == agente.aparencia["acessorios"]
        assert agente.aparencia == aparencia.montar("atlas", "infraestrutura")

    def test_mesma_familia_nao_da_coruja_igual(self):
        vigia = aparencia.montar("vigia", "infraestrutura")
        atlas = aparencia.montar("atlas", "infraestrutura")
        assert (vigia["plumagem"], vigia["acessorios"]) != (atlas["plumagem"], atlas["acessorios"])

    def test_extra_nunca_e_o_simbolo_de_outra_familia(self):
        simbolos = {p for f in aparencia.familias().values() for p in f["simbolo"].values()}
        for nome in ["lume", "nina", "bento", "kai", "vera", "sol", "luz", "ivo", "ana", "teo"]:
            sugeridos = aparencia.montar(nome, "pesquisa")["sugeridos"]
            assert sugeridos["asa"] == "lupa"
            assert not (set(sugeridos.values()) - {"lupa"}) & simbolos

    def test_sem_familia_a_plumagem_sai_do_nome_e_nao_muda(self):
        uma = _m.validar(ATLAS).aparencia
        outra = _m.validar(ATLAS).aparencia
        assert uma["familia"] == "geral" and uma == outra

    def test_plumagem_de_fora_nao_entra(self):
        guardada = {"familia": "infraestrutura", "plumagem": "coral", "acessorios": {}}
        esperada = aparencia.montar("atlas", "infraestrutura")["plumagem"]
        assert esperada != "coral" and _m.validar({**ATLAS, "aparencia": guardada}).aparencia["plumagem"] == esperada

    @pytest.mark.parametrize("acessorios, trecho", [
        ({"cauda": "laco"}, "encaixe"),
        ({"cabeca": "lupa"}, "não cabe"),
    ])
    def test_acessorio_fora_do_catalogo(self, acessorios, trecho):
        with pytest.raises(_m.ManifestoInvalido, match=trecho):
            _m.validar({**ATLAS, "familia": "pesquisa", "acessorios": acessorios})

    def test_trocar_acessorios_mantem_familia_e_plumagem(self):
        registro.criar({**ATLAS, "familia": "infraestrutura"})
        trocado = registro.trocar_acessorios("atlas", {"rosto": "escuros", "asa": "caneca"})
        original = aparencia.montar("atlas", "infraestrutura")
        assert trocado.aparencia == {**original, "acessorios": {"rosto": "escuros", "asa": "caneca"}}
        assert registro.carregar("atlas").aparencia["acessorios"] == {"rosto": "escuros", "asa": "caneca"}

    def test_a_ficha_leva_as_cores(self):
        registro.criar({**ATLAS, "familia": "infraestrutura"})
        plumagem = aparencia.montar("atlas", "infraestrutura")["plumagem"]
        assert hq.listar()[0]["cores"]["penas"] == aparencia.catalogo()["plumagens"][plumagem]["penas"]


class TestCerebro:
    def test_provedor_e_modelo_fixos(self):
        agente = _m.validar({**ATLAS, "cerebro": {"provedor": "openrouter", "modelo": "deepseek/deepseek-v4-flash"}})
        assert agente.cerebro == {"provedor": "openrouter", "modelo": "deepseek/deepseek-v4-flash", "se_cair": "parar"}

    @pytest.mark.parametrize("cerebro, trecho", [
        ({"provedor": "inventado", "modelo": "x"}, "não existe"),
        ({"provedor": "openrouter"}, "precisa"),
        ({"provedor": "openrouter", "modelo": "x", "se_cair": "rezar"}, "se_cair"),
    ])
    def test_cerebro_invalido(self, cerebro, trecho):
        with pytest.raises(_m.ManifestoInvalido, match=trecho):
            _m.validar({**ATLAS, "cerebro": cerebro})

    def test_se_cair_decide_se_volta_ao_router(self):
        from sentury.residentes.cerebro import _config, provedor_do_turno

        config = _config()
        parar = provedor_do_turno({"provedor": "openrouter", "modelo": "m", "se_cair": "parar"}, config)
        seguir = provedor_do_turno({"provedor": "openrouter", "modelo": "m", "se_cair": "robinbandit"}, config)
        assert parar.name == "ultra_max" and seguir.name == "ultra"
        assert provedor_do_turno({}, config) is None

    def test_resposta_do_ultimo_recurso_e_falha_e_nao_resposta(self):
        """Quando só o último recurso do roteador respondeu, o texto é aviso de falha: a tarefa
        falha com ele como motivo, e na Mesa a vez passa em vez de o aviso virar fala."""
        from types import SimpleNamespace

        from robinbandit.chain import anotar_resposta

        from sentury.residentes.cerebro import ouvir_respostas, respondeu_so_o_ultimo_recurso

        config = SimpleNamespace(last_resort="fallback")
        ouvir_respostas()
        anotar_resposta(texto="ok", provedor="chatgpt_codex")
        assert not respondeu_so_o_ultimo_recurso(config)
        anotar_resposta(texto="Nenhum provedor respondeu", provedor="fallback")
        assert respondeu_so_o_ultimo_recurso(config)
        assert not respondeu_so_o_ultimo_recurso(SimpleNamespace(last_resort=None))

    def test_na_mesa_a_queda_do_provedor_cai_no_router(self):
        """Uma vez parada trava a conversa de todos: na Mesa, "parar" vira seguir pelo Router."""
        from sentury.residentes.cerebro import _config, provedor_do_turno

        cerebro = {"provedor": "openrouter", "modelo": "m", "se_cair": "parar"}
        assert provedor_do_turno(cerebro, _config(), na_mesa=True).name == "ultra"


def test_api_troca_acessorios_e_serve_o_catalogo(monkeypatch):
    monkeypatch.setenv("SENTURY_HQ_TOKEN", "segredo")
    app = FastAPI()
    _api.montar(app)
    cliente = TestClient(app)
    cabecalho = {"Authorization": "Bearer segredo"}
    cliente.post("/hq/agents", json={"manifesto": {**ATLAS, "familia": "infraestrutura"}}, headers=cabecalho)
    trocado = cliente.put("/hq/agents/atlas/acessorios", json={"acessorios": {"cabeca": "gorro"}}, headers=cabecalho)
    assert trocado.json()["aparencia"]["acessorios"] == {"cabeca": "gorro"}
    assert cliente.put("/hq/agents/atlas/acessorios", json={"acessorios": {"cabeca": "escudo"}},
                       headers=cabecalho).status_code == 422
    assert "infraestrutura" in cliente.get("/hq/aparencia", headers=cabecalho).json()["familias"]


def test_rotas_da_tela_passam_pelo_cliente_local(monkeypatch):
    from sentury.residentes.api_local import router as rotas

    monkeypatch.delenv("SENTURY_HQ_URL", raising=False)
    app = FastAPI()
    app.include_router(rotas)
    cliente = TestClient(app)
    registro.criar({**ATLAS, "familia": "infraestrutura"})
    lista = cliente.get("/sentury/residentes").json()
    assert lista["hq"] == "local" and lista["agentes"][0]["cores"]["penas"].startswith("#")
    assert "encaixes" in cliente.get("/sentury/residentes/_aparencia").json()
    tarefa = cliente.post("/sentury/residentes/atlas/tarefas", json={"pedido": "olhe o disco"}).json()
    assert cliente.get(f"/sentury/residentes/_tarefas/{tarefa['id']}").json()["origem"] == "tela"
    assert cliente.put("/sentury/residentes/atlas/acessorios",
                       json={"acessorios": {"cabeca": "gorro"}}).json()["aparencia"]["acessorios"] == {"cabeca": "gorro"}
    assert cliente.post("/sentury/residentes/atlas/pausar").json()["estado"] == _m.PAUSADO
    assert cliente.get("/sentury/residentes/_esperando").json() == {"tarefas": []}


def test_contexto_do_residente_mostra_o_que_o_turno_monta(monkeypatch):
    """A aba Contexto lê a mesma identidade que o turno veste, com a memória e as decisões dele."""
    from sentury.memory import decisoes
    from sentury.residentes.api_local import router as rotas

    monkeypatch.delenv("SENTURY_HQ_URL", raising=False)
    app = FastAPI()
    app.include_router(rotas)
    cliente = TestClient(app)
    registro.criar(ATLAS)
    registro.anotar_memoria("atlas", "o disco enche às sextas")
    decisoes.registrar("mesa:m1", "Backup", "Backup diário às 3h.", ["atlas"])
    blocos = cliente.get("/sentury/residentes/atlas/contexto").json()["blocos"]
    assert blocos[0]["titulo"] == "Identidade" and "o disco enche às sextas" in blocos[0]["texto"]
    assert any("Backup diário" in b["texto"] for b in blocos[1:])
    assert cliente.get("/sentury/residentes/ninguem/contexto").status_code == 404


class TestMencao:
    @pytest.fixture
    def http(self, monkeypatch):
        import sentury.main as main

        monkeypatch.delenv("SENTURY_HQ_URL", raising=False)
        main.app.dependency_overrides[main.verify_api_token] = lambda: None
        try:
            yield TestClient(main.app), main
        finally:
            main.app.dependency_overrides.clear()

    def test_mencao_enfileira_e_grava_na_conversa(self, http):
        cliente, main = http
        registro.criar({**ATLAS, "familia": "infraestrutura"})
        corpo = cliente.post("/sentury/residentes/atlas/mencao",
                             json={"session_id": "s-mencao", "user_id": "ryan", "texto": "olhe o disco"}).json()
        assert corpo["tarefa"]["origem"] == "conversa:ryan:s-mencao"
        _, state = asyncio.run(main._load_state("s-mencao", "ryan"))
        assert [m["content"] for m in state.history[-2:]] == ["@atlas olhe o disco", corpo["mensagem"]]

    def test_varios_residentes_numa_troca_so(self, http):
        """A fala da pessoa entra uma vez com todos os nomes; cada residente ganha a
        própria tarefa, e quem não pode receber aparece na confirmação sem
        derrubar a entrega aos outros."""
        cliente, main = http
        registro.criar(ATLAS)
        registro.criar({**ATLAS, "nome": "nina"})
        corpo = cliente.post("/sentury/residentes/_mencao", json={
            "session_id": "s-varios", "user_id": "ryan", "texto": "revisem o deploy",
            "nomes": ["atlas", "Nina", "zeca"]}).json()
        assert [t["agente"] for t in corpo["tarefas"]] == ["atlas", "nina"]
        assert "Atlas e Nina" in corpo["mensagem"] and "Zeca não recebeu" in corpo["mensagem"]
        _, state = asyncio.run(main._load_state("s-varios", "ryan"))
        fala, confirmacao = state.history[-2:]
        assert fala["content"] == "@atlas @nina revisem o deploy" and fala["mencoes"] == ["atlas", "nina"]
        assert confirmacao["mencoes"] == ["atlas", "nina"] and len(confirmacao["tarefas_residentes"]) == 2
        assert len(state.history) == 2

    def test_levar_a_mesa_abre_o_assunto_e_o_resumo_volta_a_conversa(self, http):
        """Com vários no chip, a fala pode virar um assunto da Mesa; falar de novo vai
        para o mesmo assunto, e ao fechar o resumo volta para a conversa de origem."""
        from sentury.residentes import mesa

        cliente, main = http
        registro.criar(ATLAS)
        registro.criar({**ATLAS, "nome": "nina"})
        corpo = cliente.post("/sentury/residentes/_levar_a_mesa", json={
            "session_id": "s-mesa", "user_id": "ryan", "texto": "qual servidor desligar?",
            "nomes": ["atlas", "nina"]}).json()
        assunto = mesa.carregar(corpo["assunto"]["id"])
        assert assunto.titulo == "qual servidor desligar?" and assunto.participantes == ["atlas", "nina"]
        assert assunto.canal == "conversa:ryan:s-mesa" and "Abri na Mesa" in corpo["mensagem"]
        segunda = cliente.post("/sentury/residentes/_levar_a_mesa", json={
            "session_id": "s-mesa", "user_id": "ryan", "texto": "@nina e o backup?",
            "assunto_id": assunto.id}).json()
        assert "Falei na Mesa" in segunda["mensagem"]
        assert mesa.carregar(assunto.id).falas[-1] == {**mesa.carregar(assunto.id).falas[-1],
                                                       "de": "pessoa", "texto": "@nina e o backup?"}
        fechado = mesa.fechar(assunto.id, "desliga o antigo depois do backup", por="atlas")
        asyncio.run(main._resumo_da_mesa_na_conversa(fechado))
        _, state = asyncio.run(main._load_state("s-mesa", "ryan"))
        assert [m.get("mesa", {}).get("id") for m in state.history] == [assunto.id] * 5
        assert state.history[-1]["mesa"]["resumo"] is True
        assert state.history[-1]["content"] == "desliga o antigo depois do backup"

    def test_a_resposta_volta_para_a_conversa(self, http):
        cliente, main = http
        registro.criar(ATLAS)
        tarefa = tarefas.enfileirar("atlas", "olhe o disco", "conversa:ryan:s-volta")
        tarefas.comecar(tarefa.id)
        feita = tarefas.concluir(tarefa.id, "Disco em 41%.")
        asyncio.run(main._resposta_do_residente_na_conversa(feita))
        _, state = asyncio.run(main._load_state("s-volta", "ryan"))
        assert state.history[-1]["content"].endswith("Disco em 41%.") and state.history[-1]["residente"] == "atlas"

    def test_pausar_nao_colide_com_a_mencao(self, http):
        cliente, _ = http
        registro.criar(ATLAS)
        assert cliente.post("/sentury/residentes/atlas/pausar").json()["estado"] == _m.PAUSADO


class TestEdicao:
    def test_editar_manifesto_mantem_quem_criou(self):
        registro.criar(ATLAS, criado_por="ryan")
        editado = registro.editar("atlas", {"objetivo": "vigiar a VPS", "orcamento": {"usd_por_dia": 2}})
        assert editado.objetivo == "vigiar a VPS" and editado.orcamento["usd_por_dia"] == 2
        assert editado.criado_por == "ryan" and editado.ferramentas == sorted(ATLAS["ferramentas"])

    def test_ferramenta_nao_se_edita_por_aqui(self):
        registro.criar(ATLAS)
        with pytest.raises(_m.ManifestoInvalido, match="ferramentas"):
            registro.editar("atlas", {"ferramentas": ["escrever_arquivo"]})

    def test_proposta_ajustada_muda_o_que_a_retomada_executa(self, monkeypatch):
        import sentury.main as main

        main.app.dependency_overrides[main.verify_api_token] = lambda: None
        try:
            cliente = TestClient(main.app)
            _, state = asyncio.run(main._load_state("s-prop", "ryan"))
            state.tarefa_pendente = {"pedido": "crie o atlas", "ferramenta": "criar_agente",
                                     "argumentos": dict(ATLAS), "alvo": "criar_agente atlas"}
            asyncio.run(main._persist_state(state))
            ok = cliente.put("/sentury/residentes/_proposta", json={
                "session_id": "s-prop", "user_id": "ryan",
                "argumentos": {"cerebro": {"provedor": "openrouter", "modelo": "deepseek/deepseek-v4-pro"}}})
            assert ok.status_code == 200
            _, state = asyncio.run(main._load_state("s-prop", "ryan"))
            assert state.tarefa_pendente["argumentos"]["cerebro"]["modelo"] == "deepseek/deepseek-v4-pro"
            ruim = cliente.put("/sentury/residentes/_proposta", json={
                "session_id": "s-prop", "user_id": "ryan", "argumentos": {"ferramentas": ["computador"]}})
            assert ruim.status_code == 422
        finally:
            main.app.dependency_overrides.clear()


def test_familia_inventada_vira_geral_em_vez_de_travar():
    agente = _m.validar({**ATLAS, "familia": "monitoramento"})
    assert agente.aparencia["familia"] == "geral" and agente.aparencia["plumagem"]


def test_custo_desconhecido_nao_vira_gratis():
    registro.criar(ATLAS)
    tarefa = tarefas.enfileirar("atlas", "olhe o disco")
    tarefas.comecar(tarefa.id)
    feita = tarefas.concluir(tarefa.id, "ok", custo_usd=None)
    assert feita.custo_usd == 0 and feita.turnos_sem_custo == 1
    assert orcamento.uso_de_hoje("atlas")["turnos_sem_custo"] == 1
    assert worker._custo({"message": "ok"}) is None and worker._custo({"telemetry": {"custo_usd": 0.02}}) == 0.02


class TestTelegram:
    def test_mencao_vira_tarefa_com_origem_no_chat(self, monkeypatch):
        from sentury.residentes import telegram as tg

        monkeypatch.delenv("SENTURY_HQ_URL", raising=False)
        registro.criar(ATLAS)
        assert tg.ler_mencao("@atlas olhe o disco") == ("atlas", "olhe o disco")
        assert tg.ler_mencao("oi atlas") is None
        resposta = asyncio.run(tg.encaminhar(555, "atlas", "olhe o disco"))
        assert "Mandei para Atlas" in resposta
        assert tarefas.listar("atlas")[0].origem == "telegram:555"
        assert asyncio.run(tg.encaminhar(555, "fantasma", "oi")) is None

    def test_mencao_responde_a_pergunta_que_esperava(self, monkeypatch):
        from sentury.residentes import telegram as tg

        monkeypatch.delenv("SENTURY_HQ_URL", raising=False)
        registro.criar(ATLAS)
        tarefa = tarefas.enfileirar("atlas", "olhe os logs", "telegram:555")
        tarefas.comecar(tarefa.id)
        tarefas.esperar(tarefa.id, "o agente fez uma pergunta", "Qual pasta?")
        resposta = asyncio.run(tg.encaminhar(555, "atlas", "/var/log/nginx"))
        assert "Repassei" in resposta
        liberada = tarefas.carregar(tarefa.id)
        assert liberada.estado == tarefas.NA_FILA and liberada.retorno == "/var/log/nginx"
        assert len(tarefas.listar("atlas")) == 1

    def test_destinos_e_aviso_com_botoes(self):
        from sentury.residentes import telegram as tg

        tarefa = tarefas.enfileirar("atlas", "reinicie o nginx", "tela")
        tarefas.comecar(tarefa.id)
        esperando = tarefas.esperar(tarefa.id, "precisa da sua autorização: systemctl restart nginx",
                                    pendente="systemctl restart nginx")
        assert tg.destinos(esperando, ["telegram"], [42]) == [42]
        assert tg.destinos(esperando, [], [42]) == []
        texto, botoes = tg.aviso(esperando)
        assert "systemctl restart nginx" in texto
        dados = botoes["inline_keyboard"][0][0]["callback_data"]
        assert tg.ler_botao(dados) == (tarefa.id, "uma_vez", "Autorizar desta vez")
        do_chat = tarefas.enfileirar("atlas", "x", "telegram:-100")
        assert tg.destinos(do_chat, [], []) == [-100]


def test_no_turno_do_residente_quem_fala_e_ele():
    from sentury.harness.passo_unico import base_do_passo

    agente = _m.validar({**ATLAS, "personalidade": "direto e calmo"})
    contrato = "Seu objetivo é gerar um plano X ### Ferramentas Disponíveis e seus Argumentos: Y"
    assert base_do_passo(contrato).startswith("Você é o Sentury.")
    with escopo.vestido(agente):
        assert base_do_passo(contrato).startswith("Você é Atlas, agente de infraestrutura da VPS")
    texto = identidade.identidade(agente)
    assert "Onde as regras gerais dizem" in texto and "direto e calmo" in texto


class TestEventos:
    def test_feed_traz_o_mais_novo_primeiro_com_agente_e_pedido(self, monkeypatch):
        relogio = iter(range(1000, 1100))
        monkeypatch.setattr(tarefas.time, "time", lambda: float(next(relogio)))
        primeira = tarefas.enfileirar("atlas", "olhe o disco", origem="telegram:42")
        tarefas.comecar(primeira.id)
        tarefas.esperar(primeira.id, "precisa da sua autorização", pendente="df -h")
        tarefas.enfileirar("iris", "confira a tabela")
        feed = tarefas.eventos_recentes()
        assert [e["tipo"] for e in feed] == ["enfileirada", tarefas.ESPERANDO, "comecou", "enfileirada"]
        assert feed[0]["agente"] == "iris" and feed[0]["pedido"] == "confira a tabela"
        assert feed[1]["pendente"] == "df -h" and feed[1]["origem"] == "telegram:42"
        assert feed[2]["pendente"] == ""

    def test_desde_e_limite_cortam_o_feed(self, monkeypatch):
        relogio = iter(range(1000, 1100))
        monkeypatch.setattr(tarefas.time, "time", lambda: float(next(relogio)))
        velha = tarefas.enfileirar("atlas", "olhe o disco")
        corte = tarefas.carregar(velha.id).eventos[-1]["em"]
        nova = tarefas.enfileirar("atlas", "olhe a memória")
        tarefas.comecar(nova.id)
        assert [e["tarefa"] for e in tarefas.eventos_recentes(desde=corte)] == [nova.id, nova.id]
        assert len(tarefas.eventos_recentes(limite=1)) == 1

    def test_rota_da_tela_e_da_hq_servem_o_feed(self, monkeypatch):
        from sentury.residentes.api_local import router as rotas

        monkeypatch.delenv("SENTURY_HQ_URL", raising=False)
        monkeypatch.setenv("SENTURY_HQ_TOKEN", "segredo")
        app = FastAPI()
        app.include_router(rotas)
        _api.montar(app)
        cliente = TestClient(app)
        registro.criar(ATLAS)
        cliente.post("/sentury/residentes/atlas/tarefas", json={"pedido": "olhe o disco"})
        tela = cliente.get("/sentury/residentes/_eventos").json()["eventos"]
        assert tela[0]["tipo"] == "enfileirada" and tela[0]["origem"] == "tela"
        hq_feed = cliente.get("/hq/events", headers={"Authorization": "Bearer segredo"}).json()["eventos"]
        assert hq_feed == tela
        assert cliente.get(f"/sentury/residentes/_eventos?desde={tela[0]['em']}").json() == {"eventos": []}


FORGE = {"nome": "forge", "papel": "construtor", "objetivo": "rodar e conferir scripts",
         "ferramentas": ["ler_arquivo"]}
NOX = {"nome": "nox", "papel": "pesquisador", "objetivo": "achar fontes", "ferramentas": ["ler_arquivo"]}


async def _esperar_todos_dormirem(*nomes):
    for _ in range(300):
        if not any(worker.acordado(n) for n in nomes):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("algum worker não dormiu")


class TestColegas:
    def _roteiro(self, passos):
        """Cada agente tem a lista dos seus turnos; um passo pode ser função que
        roda vestida, como no turno de verdade."""
        vistos = []

        async def rodar(agente, tarefa):
            vistos.append((agente.nome, tarefas.mensagem_do_turno(tarefa), tarefas.resultado_dos_colegas(tarefa)))
            passo = passos[agente.nome].pop(0)
            with escopo.vestido(agente, tarefa):
                return await passo(agente, tarefa) if callable(passo) else passo

        return rodar, vistos

    def test_quem_pede_espera_o_colega_e_volta_com_a_resposta(self):
        from sentury.harness.state import AnalysisState
        from sentury.residentes.ferramentas import executar

        registro.criar(ATLAS)
        registro.criar(FORGE)

        async def atlas_pede(agente, tarefa):
            state = AnalysisState(session_id=hq.sessao_do("atlas"), user_id="hq")
            r = await executar("pedir_ao_agente", {"acao": "pedir", "agente": "forge",
                                                   "pedido": "confira o script de backup"}, state)
            assert r["ok"] and "termine o turno" in r["proximo_passo"]
            return {"message": "pedi ao Forge para conferir o backup"}

        rodar, vistos = self._roteiro({"atlas": [atlas_pede, {"message": "backup ok, fechado"}],
                                       "forge": [{"message": "o script roda e grava 2 GB"}]})
        worker.configurar(rodar)
        avisadas = []
        worker.observar(avisadas.append)

        async def cenario():
            pedido = hq.pedir("atlas", "garanta o backup")
            for _ in range(5):
                await _esperar_todos_dormirem("atlas", "forge")
                await asyncio.sleep(0.02)
            return pedido["id"]

        atlas_id = asyncio.run(cenario())
        atlas = tarefas.carregar(atlas_id)
        forge = tarefas.filhos(atlas_id)[0]
        assert atlas.estado == tarefas.FEITA and atlas.resposta == "backup ok, fechado"
        assert forge.origem == "agente:atlas" and forge.profundidade == 1 and forge.entregue
        assert vistos[1][:2] == ("forge", "Atlas, outro residente, te pediu:\nconfira o script de backup")
        _, volta, devolvido = vistos[2]
        # A resposta do colega volta como resultado do pedir_ao_agente, sem se repetir na mensagem.
        assert devolvido == ('RESULTADO DA FERRAMENTA "pedir_ao_agente" (já executada):\n'
                             "Forge respondeu:\no script roda e grava 2 GB")
        assert "pedir_ao_agente" in volta and "garanta o backup" in volta and "2 GB" not in volta
        espera = next(e for e in atlas.eventos if e["tipo"] == tarefas.ESPERANDO)
        assert espera["aguardando"] == ["forge"] and espera["motivo"] == "aguardando Forge"
        # A pessoa só ouve do pedido dela; a espera e o pedido entre colegas ficam no feed.
        assert [t.id for t in avisadas] == [atlas_id]

    def test_espera_de_colega_nao_e_da_pessoa(self):
        registro.criar(ATLAS)
        registro.criar(FORGE)
        pai = tarefas.enfileirar("atlas", "garanta o backup")
        tarefas.comecar(pai.id)
        filho = tarefas.enfileirar("forge", "confira", "agente:atlas", pai.id)
        tarefas.esperar(pai.id, "aguardando Forge", aguardando=[filho.id])
        assert hq.esperando() == []
        with pytest.raises(tarefas.TarefaInvalida):
            hq.responder(pai.id, "uma_vez")
        hq.cancelar(filho.id)
        liberada = tarefas.carregar(pai.id)
        assert liberada.estado == tarefas.NA_FILA
        assert "A tarefa de Forge foi cancelada" in tarefas.resultado_dos_colegas(liberada)

    def test_valor_calculado_pelo_colega_tem_lastro(self):
        """O total que o colega calculou volta como resultado do pedir_ao_agente:
        quem pediu cita o número sem ganhar aviso de valor sem lastro."""
        from sentury.harness.guardrails import currency_guardrail
        from sentury.harness.state import AnalysisState

        registro.criar(ATLAS)
        registro.criar(FORGE)
        pai = tarefas.enfileirar("atlas", "feche o orçamento")
        tarefas.comecar(pai.id)
        filho = tarefas.enfileirar("forge", "some os custos", "agente:atlas", pai.id)
        tarefas.esperar(pai.id, "aguardando Forge", aguardando=[filho.id])
        tarefas.comecar(filho.id)
        tarefas.concluir(filho.id, "Somei tudo: o total é R$ 5.490,00.")
        liberada = tarefas.liberar_se_os_colegas_terminaram(pai.id)
        state = AnalysisState(session_id="atlas", user_id="hq")
        state.history = [{"role": "system", "content": tarefas.resultado_dos_colegas(liberada)},
                         {"role": "user", "content": tarefas.mensagem_do_turno(liberada)}]
        assert currency_guardrail(state, "O orçamento fecha em R$ 5.490,00.").aviso is None

    def test_laco_e_profundidade_sao_recusados(self):
        for dados in (ATLAS, FORGE, NOX):
            registro.criar(dados)
        raiz = tarefas.enfileirar("atlas", "plano da semana")
        with pytest.raises(tarefas.TarefaInvalida, match="a si mesmo"):
            tarefas.enfileirar("atlas", "x", "agente:atlas", raiz.id)
        um = tarefas.enfileirar("forge", "rode", "agente:atlas", raiz.id)
        with pytest.raises(tarefas.TarefaInvalida, match="laço"):
            tarefas.enfileirar("atlas", "x", "agente:forge", um.id)
        dois = tarefas.enfileirar("nox", "ache a fonte", "agente:forge", um.id)
        assert dois.profundidade == tarefas.MAX_PROFUNDIDADE
        registro.criar({**NOX, "nome": "iris"})
        with pytest.raises(tarefas.TarefaInvalida, match="níveis"):
            tarefas.enfileirar("iris", "x", "agente:nox", dois.id)

    def test_so_a_autorizacao_da_pessoa_retoma_o_passo_guardado(self):
        registro.criar(ATLAS)
        nova = tarefas.enfileirar("atlas", "olhe o disco")
        assert not tarefas.retoma_passo_autorizado(nova)
        for dados, retoma in (({}, True), ({"por": "colegas"}, False),
                              ({"negado": "ferramenta_nova x"}, False)):
            t = tarefas.enfileirar("atlas", "x")
            tarefas.comecar(t.id)
            tarefas.esperar(t.id, "espera")
            assert tarefas.retoma_passo_autorizado(tarefas.devolver_a_fila(t.id, "ok", **dados)) is retoma
            tarefas.cancelar(t.id)

    def test_identidade_lista_os_colegas_e_o_sentury_nao_e_colega(self):
        from sentury.harness.state import AnalysisState
        from sentury.residentes.ferramentas import executar

        atlas = registro.criar(ATLAS)
        registro.criar(FORGE)
        state = AnalysisState(session_id=hq.sessao_do("atlas"), user_id="hq")
        identidade.vestir(state, atlas)
        assert "- forge: construtor" in state.history[0]["content"]
        assert "- atlas:" not in state.history[0]["content"]
        with escopo.vestido(atlas, tarefas.enfileirar("atlas", "x")):
            r = asyncio.run(executar("pedir_ao_agente", {"acao": "pedir", "agente": "Sentury",
                                                         "pedido": "leia o arquivo"}, state))
        assert not r["ok"] and "pedir_ferramenta" in r["erro"]

    def test_pedido_repetido_e_acompanhar_aberto_dizem_para_terminar_o_turno(self):
        from sentury.harness.state import AnalysisState
        from sentury.residentes.ferramentas import executar

        atlas = registro.criar(ATLAS)
        registro.criar(FORGE)
        minha = tarefas.enfileirar("atlas", "garanta o backup")
        state = AnalysisState(session_id=hq.sessao_do("atlas"), user_id="hq")
        pedir = {"acao": "pedir", "agente": "forge", "pedido": "leia o requirements"}
        with escopo.vestido(atlas, minha):
            primeiro = asyncio.run(executar("pedir_ao_agente", pedir, state))
            filho = primeiro["tarefa"]["id"]
            tarefas.comecar(filho)
            tarefas.esperar(filho, "espera", pendente="acessar_pasta C:/projeto")
            segundo = asyncio.run(executar("pedir_ao_agente", {**pedir, "pedido": "autorização concedida, leia"}, state))
            olhada = asyncio.run(executar("pedir_ao_agente", {"acao": "acompanhar", "tarefa_id": filho}, state))
        assert not segundo["ok"] and "Termine o turno" in segundo["erro"]
        assert len(tarefas.filhos(minha.id)) == 1
        assert "só ela dá" in olhada["proximo_passo"] and "acessar_pasta" in olhada["proximo_passo"]

    def test_residente_recebe_pedir_ao_agente_sem_estar_no_manifesto(self):
        agente = _m.validar(FORGE)
        with escopo.vestido(agente):
            assert escopo.pode_usar("pedir_ao_agente") and escopo.pode_usar("pedir_ferramenta")


class TestPedirFerramenta:
    def _pedir(self, agente, tarefa, motivo="preciso gravar o relatório"):
        from sentury.harness.state import AnalysisState
        from sentury.residentes.ferramentas import executar

        state = AnalysisState(session_id=hq.sessao_do(agente.nome), user_id="hq")
        with escopo.vestido(agente, tarefa):
            return asyncio.run(executar("pedir_ferramenta",
                                        {"ferramenta": "escrever_arquivo", "motivo": motivo}, state))

    def test_cartao_na_hora_e_a_liberada_vale_no_mesmo_turno(self):
        from sentury.tools import permissoes

        permissoes.definir_permitir_tudo(True)
        agente = registro.criar(FORGE)
        tarefa = tarefas.enfileirar("forge", "gere o relatório")
        pedido = self._pedir(agente, tarefa)
        assert pedido["precisa_permissao"] and pedido["so_desta_vez"]
        assert pedido["comando"] == "ferramenta_nova escrever_arquivo"
        assert "escrever_arquivo" not in registro.carregar("forge").ferramentas

        permissoes.responder(pedido["comando"], "uma_vez", hq.sessao_do("forge"))
        liberada = self._pedir(agente, tarefa)
        assert liberada["ok"] and "escrever_arquivo" in agente.ferramentas
        assert "escrever_arquivo" in registro.carregar("forge").ferramentas

    def test_negada_segue_a_tarefa_sem_pedir_de_novo(self):
        agente = registro.criar(FORGE)
        tarefa = tarefas.enfileirar("forge", "gere o relatório")
        tarefas.comecar(tarefa.id)
        tarefas.esperar(tarefa.id, "pediu a ferramenta escrever_arquivo",
                        pendente="ferramenta_nova escrever_arquivo")
        hq.responder(tarefa.id, "negar")
        voltou = tarefas.carregar(tarefa.id)
        assert voltou.estado == tarefas.NA_FILA
        assert "siga sem ela" in tarefas.mensagem_do_turno(voltou)
        negado = self._pedir(agente, voltou)
        assert negado["negado"] and not negado.get("precisa_permissao")

    def test_ferramenta_proibida_ou_inexistente(self):
        from sentury.harness.state import AnalysisState
        from sentury.residentes.ferramentas import executar

        agente = registro.criar(FORGE)
        state = AnalysisState(session_id=hq.sessao_do("forge"), user_id="hq")
        with escopo.vestido(agente):
            for nome, trecho in (("computador", "não é dada"), ("teletransporte", "não existe")):
                r = asyncio.run(executar("pedir_ferramenta", {"ferramenta": nome, "motivo": "x"}, state))
                assert not r["ok"] and trecho in r["erro"]


def test_cada_plumagem_tem_cor_de_olho():
    for nome, plumagem in aparencia.catalogo()["plumagens"].items():
        assert plumagem.get("olho", "").startswith("#"), nome


def test_ferramenta_inventada_vem_com_as_reais_mais_parecidas():
    """O modelo costuma inventar perto do nome real; o erro já diz qual existe,
    e a correção sai na volta seguinte em vez de passar por uma busca."""
    import pytest

    from sentury.residentes.manifesto import ManifestoInvalido, validar

    with pytest.raises(ManifestoInvalido) as erro:
        validar({"nome": "nina", "papel": "organizadora", "objetivo": "tarefas em dia",
                 "ferramentas": ["rb_agenda", "rb_memoria"]})
    assert "rb_agenda" in str(erro.value) and "agenda" in str(erro.value).split("parecem:")[-1]


def test_resposta_longa_do_colega_volta_inteira():
    """O cronograma de uma semana passa de 3 mil caracteres: cortado, quem pediu
    ficava sem o fim e, com razão, não fechava o trabalho."""
    registro.criar(ATLAS)
    registro.criar({"nome": "forge", "papel": "construtor", "objetivo": "rodar scripts",
                    "ferramentas": ["ler_arquivo"]})
    pai = tarefas.enfileirar("atlas", "monte a semana")
    tarefas.comecar(pai.id)
    filho = tarefas.enfileirar("forge", "faça o cronograma", "agente:atlas", pai.id)
    tarefas.esperar(pai.id, "aguardando Forge", aguardando=[filho.id])
    tarefas.comecar(filho.id)
    cronograma = "\n".join(f"- dia {d}, {h}h: etapa {d}.{h} com responsável e entrega" for d in range(1, 8)
                           for h in range(7, 22))
    assert len(cronograma) > 3_000
    tarefas.concluir(filho.id, cronograma)
    liberada = tarefas.liberar_se_os_colegas_terminaram(pai.id)
    assert tarefas.resultado_dos_colegas(liberada).endswith(cronograma)


class TestColegaInativo:
    """Quem pede a um colega não fica esperando calado quem não vai andar hoje."""

    @staticmethod
    def _sem_orcamento(monkeypatch, nome):
        monkeypatch.setattr(orcamento, "corte",
                            lambda agente, agora=None: "o orçamento de hoje acabou" if agente.nome == nome else None)

    def test_colega_pausado_ou_sem_orcamento_recusa_na_hora(self, monkeypatch):
        registro.criar(ATLAS)
        registro.criar(FORGE)
        pai = tarefas.enfileirar("atlas", "garanta o backup")
        registro.pausar("forge")
        with pytest.raises(_m.ManifestoInvalido, match="pausado"):
            hq.pedir("forge", "confira o script", "agente:atlas", pai.id)
        registro.retomar("forge")
        self._sem_orcamento(monkeypatch, "forge")
        with pytest.raises(_m.ManifestoInvalido, match="orçamento"):
            hq.pedir("forge", "confira o script", "agente:atlas", pai.id)
        # O pedido da pessoa segue para a fila: quem decide esperar é ela.
        assert hq.pedir("forge", "confira o script", "pessoa")["estado"] == tarefas.NA_FILA

    def test_pedido_na_fila_volta_quando_o_colega_fica_sem_orcamento(self, monkeypatch):
        registro.criar(ATLAS)
        registro.criar(FORGE)
        pai = tarefas.enfileirar("atlas", "garanta o backup")
        tarefas.comecar(pai.id)
        filho = tarefas.enfileirar("forge", "confira o script", "agente:atlas", pai.id)
        tarefas.esperar(pai.id, "aguardando Forge", aguardando=[filho.id])
        self._sem_orcamento(monkeypatch, "forge")
        rodar, vistos = _rodar([{"message": "segui sem o Forge"}])
        worker.configurar(rodar)

        async def cenario():
            worker.acordar("forge")
            for _ in range(5):
                await _esperar_dormir("forge")
                await _esperar_dormir("atlas")
                await asyncio.sleep(0.02)

        asyncio.run(cenario())
        assert tarefas.carregar(filho.id).estado == tarefas.CANCELADA
        assert [v[0] for v in vistos] == ["atlas"]
        voltou = tarefas.carregar(pai.id)
        assert voltou.estado == tarefas.FEITA and voltou.resposta == "segui sem o Forge"
        assert "o orçamento de hoje acabou" in tarefas.resultado_dos_colegas(voltou)

    def test_pausar_devolve_o_pedido_de_colega_e_guarda_o_da_pessoa(self):
        registro.criar(ATLAS)
        registro.criar(FORGE)
        pai = tarefas.enfileirar("atlas", "garanta o backup")
        tarefas.comecar(pai.id)
        filho = tarefas.enfileirar("forge", "confira o script", "agente:atlas", pai.id)
        tarefas.esperar(pai.id, "aguardando Forge", aguardando=[filho.id])
        da_pessoa = tarefas.enfileirar("forge", "limpe o disco", "pessoa")
        hq.mudar("forge", "pausar")
        assert tarefas.carregar(filho.id).estado == tarefas.CANCELADA
        assert tarefas.carregar(da_pessoa.id).estado == tarefas.NA_FILA
        assert "Forge foi pausado" in tarefas.resultado_dos_colegas(tarefas.carregar(pai.id))


def test_esforco_do_residente_e_validado_no_cerebro(monkeypatch):
    from sentury.residentes import cerebro

    monkeypatch.setattr(cerebro, "provedores_conhecidos", lambda: {"groq"})
    assert cerebro.validar({"provedor": "groq", "modelo": "m", "esforco": "low"})["esforco"] == "low"
    assert "esforco" not in cerebro.validar({"provedor": "groq", "modelo": "m"})
    with pytest.raises(cerebro.CerebroInvalido):
        cerebro.validar({"provedor": "groq", "modelo": "m", "esforco": "turbo"})


class TestRetratoDaEquipe:
    """O Sentury principal sabe o que a equipe faz sem precisar perguntar."""

    def test_retrato_diz_quem_trabalha_e_quem_espera_a_pessoa(self):
        registro.criar(ATLAS)
        registro.criar(FORGE)
        tarefa = tarefas.enfileirar("atlas", "olhe o disco da VPS")
        tarefas.comecar(tarefa.id)
        espera = tarefas.enfileirar("forge", "rode o backup")
        tarefas.comecar(espera.id)
        tarefas.esperar(espera.id, "precisa da sua autorização: executar_comando")
        retrato = hq.retrato_para_o_sentury()
        assert retrato.startswith("### EQUIPE DE RESIDENTES")
        assert 'Atlas (agente de infraestrutura da VPS): trabalhando em "olhe o disco da VPS"' in retrato
        assert "Forge (construtor): espera você: precisa da sua autorização" in retrato

    def test_retrato_vai_so_ao_sentury_e_some_sem_equipe(self):
        from sentury.harness.contexto_do_mundo import equipe
        from sentury.harness.state import AnalysisState

        state = AnalysisState(session_id="s", user_id="u")
        assert equipe(state) is None
        registro.criar(ATLAS)
        assert "Atlas" in equipe(state)
        with escopo.vestido(registro.carregar("atlas"), None):
            assert equipe(state) is None
