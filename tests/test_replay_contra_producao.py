"""O replay repete o turno gravado e bate com o que a PRODUCAO produziu.

Comparar replay com replay prova so que o replay e estavel: duas rodadas
consumindo a mesma fila de respostas podem errar igual e ainda dar
`mudou: false`. A prova de que ele serve de regua e repetir e bater com o que o
turno de fato produziu quando aconteceu.

E a regua so mede o que enxerga. A gravacao e o replay tiravam a lista de
ferramentas de `harness.events`, que e a lista do CLASSIFICADOR: todo traco saia
com `ferramentas: []`. A mutacao que fizesse o agente parar de chamar uma
ferramenta passava como `mudou: false` sempre que a frase final saisse igual:
e com as respostas do modelo gravadas, ela sai igual.
"""
import json

import pytest

from tests.fixtures.setor_teste.dados import StoreTeste
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.policy import SenturyHarness
from sentury.harness.state import AnalysisState
from sentury.mutation import replay


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_TRACOS_DIR", str(tmp_path / "tracos"))
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    from sentury.config import settings

    monkeypatch.setattr(settings, "SENTURY_GRAVAR_TRACOS", True, raising=False)
    yield


_CLASSIFICACAO = json.dumps({
    "intent": "TOOL_USE", "complexity": "SIMPLE", "priority": "NORMAL",
    "confidence": 0.95, "events": ["NEED_PLANNER"],
})


class LlmNativo:
    """Responde o combinado como um provedor com tool calling nativo: a chamada
    vem no canal lateral (`last_tool_calls`), nao no texto. E anota a resposta
    como a cadeia anotaria, para a gravacao guardar."""

    supports_tools = True

    def __init__(self, respostas):
        self._fila = list(respostas)
        self.last_model = "teste:nativo"
        self.last_provider = "teste"
        self.last_usage = None
        self.last_tool_calls = None
        self.last_reasoning_summary = None

    async def complete(self, messages, *args, **kwargs):
        item = self._fila.pop(0) if self._fila else "pronto"
        texto, chamadas = (item, None) if isinstance(item, str) else (item["texto"], item["tool_calls"])
        self.last_tool_calls = chamadas
        from robinbandit.chain import anotar_resposta

        anotar_resposta(texto=texto, tool_calls=chamadas, modelo=self.last_model,
                        provedor=self.last_provider, ms=1)
        return texto


def _chamando(nome, argumentos, texto=""):
    return {"texto": texto, "tool_calls": [{
        "id": "c1", "type": "function",
        "function": {"name": nome, "arguments": json.dumps(argumentos)},
    }]}


def _orquestrador(planner, responder):
    return SenturyOrchestrator(
        planner=planner, responder=responder,
        store=StoreTeste(),
    )


async def _turno_que_lista_arquivos(mensagem_final="Aqui estao os arquivos: nenhum."):
    llm = LlmNativo([
        _chamando("listar_arquivos", {"caminho": "."}, "vou listar"),
        mensagem_final,
    ])
    return await _orquestrador(llm, llm).handle_message(
        AnalysisState.new("sessao-real", "dono"), "lista os arquivos daqui")


class TestAGravacaoEnxergaFerramenta:
    async def test_o_harness_diz_o_que_rodou(self):
        resultado = await _turno_que_lista_arquivos()
        assert resultado["harness"]["ferramentas"] == ["listar_arquivos"]

    async def test_o_traco_guarda_a_ferramenta_da_producao(self):
        await _turno_que_lista_arquivos()
        observado = replay.listar()[0].resultado_observado
        assert observado["ferramentas"] == ["listar_arquivos"]

    async def test_o_caminho_do_planner_em_texto_tambem(self):
        """A gravação enxerga a ferramenta também no protocolo textual."""
        class LlmDeTexto(LlmNativo):
            supports_tools = False

        llm = LlmDeTexto([
            json.dumps({"action": "tool_call", "tool": "listar_arquivos", "arguments": {"caminho": "."}}),
            json.dumps({"action": "respond", "message": "listei"}),
        ])
        await _orquestrador(llm, llm).handle_message(AnalysisState.new("s", "u"), "lista os arquivos daqui")
        assert replay.listar()[0].resultado_observado["ferramentas"] == ["listar_arquivos"]

    async def test_so_o_nome_vai_para_o_harness(self):
        """A saida de permissao espalha o `decision_log` na resposta: resultado
        de ferramenta ali seria dado pesado indo para a tela."""
        resultado = await _turno_que_lista_arquivos()
        assert all(isinstance(n, str) for n in resultado["harness"]["ferramentas"])


class TestORepetidoBateComAProducao:
    @pytest.mark.parametrize("arquivo_presente", [False, True])
    async def test_escrita_seguida_de_leitura_independe_do_disco(
        self, tmp_path, monkeypatch, arquivo_presente,
    ):
        from sentury.tools import catalog, permissoes

        monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
        permissoes.definir_permitir_tudo(True)
        conteudo = "O arquivo foi escrito e conferido."
        llm = LlmNativo([
            _chamando("escrever_arquivo", {"caminho": "nota.txt", "conteudo": conteudo}),
            _chamando("ler_arquivo", {"caminho": "nota.txt"}),
            conteudo,
        ])
        await _orquestrador(llm, llm).handle_message(
            AnalysisState.new("escrita-e-leitura", "dono"),
            "Escreva nota.txt e leia o arquivo para conferir.",
        )
        destino = tmp_path / "nota.txt"
        assert destino.read_text(encoding="utf-8") == conteudo
        traco = replay.listar()[0]
        assert traco.resultado_observado["ferramentas"] == ["escrever_arquivo", "ler_arquivo"]
        assert [r["tool"] for r in traco.resultados_ferramentas] == ["escrever_arquivo", "ler_arquivo"]
        assert traco.resultados_ferramentas[1]["resultado"]["conteudo"] == conteudo
        if arquivo_presente:
            destino.write_text("Conteúdo alterado depois do turno.", encoding="utf-8")
        else:
            destino.unlink()

        async def nao_executar(*args, **kwargs):
            pytest.fail("O replay tentou executar uma ferramenta contra o disco atual.")

        monkeypatch.setattr(catalog, "_executar_ferramenta", nao_executar)
        repetido = await replay.repetir(traco, _orquestrador)
        assert repetido["ok"], repetido
        assert repetido["ferramentas_servidas"] == 2
        assert repetido["resultados_sobraram"] == 0
        assert replay.comparar(replay.producao(traco), repetido)["mudou"] is False
        if arquivo_presente:
            assert destino.read_text(encoding="utf-8") == "Conteúdo alterado depois do turno."
        else:
            assert not destino.exists()

    async def test_listagem_usa_o_conteudo_gravado_da_pasta(self, tmp_path, monkeypatch):
        from sentury.tools import catalog

        monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        assert traco.resultados_ferramentas[0]["tool"] == "listar_arquivos"
        assert "novo.txt" not in str(traco.resultados_ferramentas[0]["resultado"])
        (tmp_path / "novo.txt").write_text("Depois do turno.", encoding="utf-8")

        async def nao_executar(*args, **kwargs):
            pytest.fail("O replay tentou listar a pasta atual.")

        monkeypatch.setattr(catalog, "_executar_ferramenta", nao_executar)
        repetido = await replay.repetir(traco, _orquestrador)
        assert repetido["ok"] and repetido["ferramentas_servidas"] == 1
        assert repetido["resultados_sobraram"] == 0
        assert replay.comparar(replay.producao(traco), repetido)["mudou"] is False

    async def test_mudou_false_contra_a_propria_producao(self):
        await _turno_que_lista_arquivos()
        diferenca = await replay.contra_producao(replay.listar()[0], _orquestrador)

        assert diferenca["comparavel"], diferenca
        assert diferenca["ferramentas_baseline"] == ["listar_arquivos"]
        assert diferenca["ferramentas_iguais"] and diferenca["mensagem_igual"]
        assert diferenca["mudou"] is False

    async def test_candidata_que_para_de_chamar_a_ferramenta_e_vista(self, monkeypatch):
        """A frase final sai igual: as respostas do modelo estao gravadas. Com a
        lista de ferramentas cega, esta mutacao passava como `mudou: false`."""
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]

        original = SenturyHarness.evaluate

        def recusa_a_listagem(self, state, tool, *args, **kwargs):
            decisao = original(self, state, tool, *args, **kwargs)
            if tool == "listar_arquivos":
                decisao.allowed, decisao.reason = False, "candidata recusa"
            return decisao

        monkeypatch.setattr(SenturyHarness, "evaluate", recusa_a_listagem)
        diferenca = await replay.contra_producao(traco, _orquestrador)

        assert diferenca["mensagem_igual"], "o caso so prova algo se a frase sair igual"
        assert diferenca["ferramentas_candidata"] == []
        assert diferenca["mudou"] is True

    async def test_resposta_gravada_que_sobra_e_mudanca(self):
        """Mensagem igual com menos chamadas ao modelo: o caminho nao foi o
        mesmo, e isso tambem e o que a mutacao precisa ver."""
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        traco.respostas_llm = traco.respostas_llm + [{"texto": "resposta que ninguem pediu"}]

        diferenca = await replay.contra_producao(traco, _orquestrador)
        assert diferenca["mudou"] is True
        assert diferenca["respostas_sobraram"] == 1

    async def test_resposta_que_faltou_e_mudanca_com_motivo(self):
        """O orquestrador engole a falha do dublê e responde a frase de erro: sem
        a marca, a bateria so veria "mensagem diferente" e mandaria olhar texto."""
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        traco.respostas_llm = traco.respostas_llm[:-1]

        diferenca = await replay.contra_producao(traco, _orquestrador)
        assert diferenca["mudou"] is True
        assert diferenca["respostas_faltaram"] is True
        assert diferenca["motivos"] == ["o replay pediu uma resposta do modelo que não está gravada"]

    async def test_erro_igual_sem_chamada_gravada_nao_prova_fidelidade(self):
        """A mesma frase de erro não prova que a falha da produção foi repetida."""
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        traco.respostas_llm = []
        traco.resultado_observado = {**traco.resultado_observado, "ferramentas": []}
        traco.resultados_ferramentas = []
        sem_modelo = await replay.repetir(traco, _orquestrador)
        traco.resultado_observado["mensagem"] = sem_modelo["mensagem"]

        diferenca = await replay.contra_producao(traco, _orquestrador)
        assert diferenca["respostas_faltaram"] is True
        assert diferenca["mensagem_igual"] is True
        assert diferenca["mudou"] is True
        assert diferenca["motivos"] == ["o replay pediu uma resposta do modelo que não está gravada"]

        replay.salvar(traco)
        bateria = await replay.bateria(_orquestrador)
        assert bateria["fiel"] is False and bateria["iguais"] == 0
        assert bateria["mudaram"][0]["respostas_faltaram"] is True

    async def test_traco_antigo_nao_acusa_ferramenta_que_so_a_gravacao_nao_via(self):
        """Traco de formato antigo nao lista as ferramentas. Contra o replay de
        agora, que enxerga, todo traco com ferramenta daria `mudou`: falso
        alarme, e em massa."""
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        traco.ambiente.pop("formato_do_observado")
        traco.resultado_observado["ferramentas"] = []

        diferenca = await replay.contra_producao(traco, _orquestrador)
        assert diferenca["ferramentas_iguais"] is None
        assert diferenca["mudou"] is False

    def test_traco_escrito_a_mao_nao_tem_producao(self):
        traco = replay.gravar(mensagem="oi", respostas_llm=["ola"])
        assert replay.producao(traco)["ok"] is False


class TestBateria:
    async def test_o_conjunto_de_desenvolvimento_inteiro_bate(self):
        await _turno_que_lista_arquivos("primeira")
        await _turno_que_lista_arquivos("segunda")

        resultado = await replay.bateria(_orquestrador)
        assert resultado["tracos"] == 2
        assert resultado["iguais"] == 2
        assert resultado["fiel"] is True

    async def test_conjunto_vazio_nao_e_fiel(self):
        """Nenhum traco nao prova nada: `fiel` vazio seria verde por omissao."""
        resultado = await replay.bateria(_orquestrador)
        assert resultado["tracos"] == 0 and resultado["fiel"] is False

    async def test_traco_nao_determinista_fica_fora(self):
        """Turno que passou por rede ou relogio nao repete igual por natureza."""
        await _turno_que_lista_arquivos()
        replay.gravar(mensagem="busca", respostas_llm=["x"], conjunto="desenvolvimento",
                      determinista=False, resultado_observado={"mensagem": "x"})

        resultado = await replay.bateria(_orquestrador)
        assert resultado["tracos"] == resultado["repetidos"] == 1
        assert resultado["selecionados"] == 2
        assert resultado["fora_da_bateria"][0]["motivo"] == "não determinista"

    async def test_formato_antigo_fica_fora_com_motivo(self):
        """Sem o despacho, o replay não sabe se o turno foi nativo, e a gravação
        dessa época nem sempre guardava todas as respostas: repetir mede o
        palpite. Fica fora, contado, em vez de virar "mudou"."""
        traco = replay.gravar(mensagem="oi", conjunto="desenvolvimento", respostas_llm=["Olá."],
                              resultado_observado={"mensagem": "Olá.", "ferramentas": []})
        resultado = await replay.bateria(_orquestrador)
        assert resultado["fora_da_bateria"] == [{"traco": traco.id, "motivo": replay.FORMATO_ANTIGO}]
        assert resultado["repetidos"] == 0 and resultado["fiel"] is False

    async def test_sem_observacao_fica_fora_com_motivo(self):
        traco = replay.gravar(mensagem="oi", conjunto="desenvolvimento", respostas_llm=["Olá."])
        resultado = await replay.bateria(_orquestrador)
        assert resultado["selecionados"] == 1 and resultado["repetidos"] == 0
        assert resultado["fora_da_bateria"] == [{"traco": traco.id, "motivo": "sem resultado observado"}]
        assert resultado["fiel"] is False

    async def test_todos_pulados_durante_execucao_nao_da_verde(self, monkeypatch):
        from sentury.tools import catalog

        estado = AnalysisState.new("gravacao-antiga", "teste")
        estado.funcoes_ativas = ["computador"]
        traco = replay.gravar(
            mensagem="olhe a tela", conjunto="desenvolvimento",
            estado_inicial=estado.to_dict(),
            respostas_llm=[_chamando("computador", {"acao": "snapshot"})],
            resultado_observado={"mensagem": "Olhei.", "ferramentas": []},            ambiente={"despacho": "passo_unico"},
        )

        async def nao_executar(*args, **kwargs):
            pytest.fail("A bateria tentou executar no computador atual.")

        monkeypatch.setattr(catalog, "_executar_ferramenta", nao_executar)
        resultado = await replay.bateria(_orquestrador)
        assert resultado["tracos"] == 1 and resultado["repetidos"] == 0
        assert resultado["pulados"] == [{"traco": traco.id, "ferramentas": ["computador"]}]
        assert resultado["fiel"] is False

    async def test_traco_que_agiu_no_mundo_e_pulado_e_nao_falha(self):
        """A marca antiga de determinista so olhava rede e relogio: um turno com
        `computador` passava. Contar como falha esconderia as falhas de verdade."""
        await _turno_que_lista_arquivos()
        replay.gravar(mensagem="abre o app", respostas_llm=["x"], conjunto="desenvolvimento",
                      determinista=True, resultado_observado={"mensagem": "x", "ferramentas": ["computador"]},
                      ambiente={"despacho": "texto"})

        resultado = await replay.bateria(_orquestrador)
        assert resultado["tracos"] == 1 and resultado["falharam"] == []
        assert [p["ferramentas"] for p in resultado["pulados"]] == [["computador"]]
        assert resultado["fiel"] is True


class TestReplayNaoRepeteEfeitos:
    def test_gravador_nao_chama_escrita_de_deterministica(self):
        from sentury.harness.gravacao_do_turno import _nao_deterministas

        nao_repetiveis = _nao_deterministas()
        assert "escrever_arquivo" in nao_repetiveis
        assert "executar_python" in nao_repetiveis
        assert "usar_mcp" in nao_repetiveis
        assert "listar_arquivos" in nao_repetiveis
        assert "ler_arquivo" in nao_repetiveis
        assert "consultar_medida" not in nao_repetiveis

    @pytest.mark.parametrize("tool", ["escrever_arquivo", "ler_arquivo", "listar_arquivos"])
    async def test_traco_sem_resultado_recusa_antes_de_construir_runtime(self, tool):
        traco = replay.gravar(
            mensagem="grave um arquivo", determinista=True,
            resultado_observado={"mensagem": "feito", "ferramentas": [tool]},
        )

        def nao_deve_construir(*_args):
            pytest.fail("runtime foi construido para um traco mutante")

        saida = await replay.repetir(traco, nao_deve_construir)
        assert saida["ok"] is False
        assert saida["ferramentas_bloqueadas"] == [tool]

    async def test_ferramenta_mutante_surpresa_falha_mesmo_se_agente_captura(self, tmp_path):
        from sentury.tools.catalog import execute_tool

        destino = tmp_path / "nao-criar.txt"

        class AgenteQueCapturaErro:
            async def handle_message(self, estado, _mensagem):
                try:
                    await execute_tool(None, estado, "escrever_arquivo", {
                        "caminho": str(destino), "conteudo": "efeito proibido",
                    })
                except RuntimeError:
                    pass
                return {"message": "feito", "harness": {"ferramentas": []}}

        traco = replay.gravar(mensagem="leitura que mudou de caminho",
                             respostas_llm=["resposta gravada"])
        saida = await replay.repetir(traco, lambda *_args: AgenteQueCapturaErro())

        assert saida["ok"] is False
        assert saida["ferramentas_bloqueadas"] == ["escrever_arquivo"]
        assert not destino.exists()


class TestFalhaGravada:
    async def test_o_duble_repete_a_falha_com_os_tipos(self):
        from robinbandit.chain import FalhaDaCadeia

        duble = replay.LlmGravado([{"texto": "", "erro": "413", "tipos": ["request_too_large"]}])
        with pytest.raises(FalhaDaCadeia) as erro:
            await duble.complete([])
        assert erro.value.tipos == ["request_too_large"]

    async def test_turno_em_que_o_modelo_falhou_repete_igual_e_sem_faltar_resposta(self):
        from robinbandit.chain import FalhaDaCadeia, anotar_resposta

        class LlmQueFalha(LlmNativo):
            async def complete(self, messages, *args, **kwargs):
                anotar_resposta(texto="", erro="503 Service Unavailable", tipos=["transient"])
                raise FalhaDaCadeia("Todos os provedores de LLM falharam: 503", ["transient"])

        llm = LlmQueFalha([])
        await _orquestrador(llm, llm).handle_message(AnalysisState.new("s", "u"), "oi, tudo bem?")
        traco = replay.listar()[0]
        assert any(r.get("erro") for r in traco.respostas_llm)

        diferenca = await replay.contra_producao(traco, _orquestrador)
        assert diferenca["mudou"] is False
        assert not diferenca.get("respostas_faltaram")
