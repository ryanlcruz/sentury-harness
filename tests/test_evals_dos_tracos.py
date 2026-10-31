"""Evals de casos reais: o traço rotulado repete e confere o que precisa provar."""
import pytest

from sentury.evals import dos_tracos
from sentury.mutation import replay
from tests.test_replay_contra_producao import _orquestrador, _turno_que_lista_arquivos


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_TRACOS_DIR", str(tmp_path / "tracos"))
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    from sentury.config import settings

    monkeypatch.setattr(settings, "SENTURY_GRAVAR_TRACOS", True, raising=False)


class TestPromover:
    @pytest.mark.parametrize("esperado", [
        {}, {"sem_ferramenta": "false"}, {"falha_esperada": 1},
        {"mensagem_contem": "pronto"}, {"mensagem_contem": [""]},
        {"mensagem_contem": [1]}, {"ferramentas_excluem": ["ferramenta_inexistente"]},
        {"sem_ferramenta": True, "ferramentas_incluem": ["ler_arquivo"]},
        {"ferramentas_incluem": ["ler_arquivo"], "ferramentas_excluem": ["ler_arquivo"]},
    ])
    async def test_rotulo_invalido_nao_altera_o_corpus(self, esperado):
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        with pytest.raises(ValueError):
            dos_tracos.promover(traco.id, "leitura", **esperado)
        guardado = replay.carregar(traco.id)
        assert guardado.conjunto == "desenvolvimento"
        assert guardado.resultado_esperado == {}

    async def test_holdout_nao_pode_ser_reutilizado_para_avaliacao(self):
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        traco.conjunto = "holdout"
        replay.salvar(traco)
        with pytest.raises(ValueError, match="holdout"):
            dos_tracos.promover(traco.id, "leitura", ferramentas_incluem=["listar_arquivos"])
        assert replay.carregar(traco.id).conjunto == "holdout"

    async def test_o_traco_vai_para_avaliacao_com_o_rotulo(self):
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        dos_tracos.promover(traco.id, "leitura", ferramentas_incluem=["listar_arquivos"])

        guardado = replay.carregar(traco.id)
        assert guardado.conjunto == "avaliacao"
        assert guardado.resultado_esperado == {"capacidade": "leitura", "ferramentas_incluem": ["listar_arquivos"]}

    async def test_expectativa_com_nome_errado_e_recusada(self):
        """Uma chave que ninguém confere passaria sempre."""
        await _turno_que_lista_arquivos()
        with pytest.raises(ValueError, match="expectativa desconhecida"):
            dos_tracos.promover(replay.listar()[0].id, "leitura", ferramenta_inclui=["x"])

    def test_turno_em_que_o_modelo_falhou_nao_vira_caso(self):
        traco = replay.gravar(mensagem="oi", respostas_llm=[], conjunto="desenvolvimento",
                              resultado_observado={"mensagem": "Desculpe, tive um problema ao processar a resposta."})
        with pytest.raises(ValueError, match="frase de erro"):
            dos_tracos.promover(traco.id, "conversa")


class TestConferir:
    def test_frase_de_erro_reprova_mesmo_sem_expectativa(self):
        falhas = dos_tracos.conferir({}, {"mensagem": "Desculpe, tive um problema ao processar a resposta."})
        assert falhas == ["o turno terminou na frase de erro"]

    def test_cada_expectativa_e_conferida(self):
        esperado = {"sem_ferramenta": True, "ferramentas_incluem": ["ler_arquivo"],
                    "mensagem_contem": ["pronto"], "mensagem_nao_contem": ["json"]}
        falhas = dos_tracos.conferir(esperado, {"mensagem": "aqui o json", "ferramentas": ["listar_arquivos"]})
        assert len(falhas) == 4

    def test_falha_esperada_precisa_acontecer(self):
        assert dos_tracos.conferir({"falha_esperada": True}, {"mensagem": "Pronto."}) == [
            "o turno não apresentou a falha esperada",
        ]

    def test_falha_gravada_esperada_passa(self):
        assert dos_tracos.conferir({"falha_esperada": True}, {
            "mensagem": "Desculpe, tive um problema ao processar a resposta.",
        }) == []

    def test_resposta_nao_gravada_reprova_mesmo_se_a_falha_era_esperada(self):
        assert dos_tracos.conferir({"falha_esperada": True}, {
            "mensagem": "Desculpe, tive um problema ao processar a resposta.",
            "respostas_faltaram": True,
        }) == ["o replay pediu ao modelo uma resposta que não foi gravada"]


class TestRodar:
    async def test_o_caso_que_cumpre_passa_e_o_que_nao_cumpre_diz_por_que(self):
        await _turno_que_lista_arquivos("primeira")
        await _turno_que_lista_arquivos("segunda")
        bom, ruim = replay.listar()
        dos_tracos.promover(bom.id, "leitura", ferramentas_incluem=["listar_arquivos"])
        dos_tracos.promover(ruim.id, "conversa", sem_ferramenta=True)

        resultados = {r.nome.split(":")[0]: r for r in await dos_tracos.rodar(_orquestrador)}
        assert resultados["leitura"].ok
        assert not resultados["conversa"].ok
        assert "chamou ferramenta: listar_arquivos" in resultados["conversa"].detalhe

    @pytest.mark.parametrize("sobra", ["modelo", "ferramenta"])
    async def test_resposta_correta_com_gravacao_nao_consumida_reprova(self, sobra):
        await _turno_que_lista_arquivos("conferi")
        traco = dos_tracos.promover(
            replay.listar()[0].id, "leitura", ferramentas_incluem=["listar_arquivos"],
        )
        if sobra == "modelo":
            traco.respostas_llm.append({"texto": "Resposta que não foi pedida."})
        else:
            traco.resultados_ferramentas.append({
                "tool": "ler_arquivo", "argumentos": {"caminho": "outro.txt"},
                "resultado": {"ok": True, "conteudo": "outro"},
            })
        replay.salvar(traco)
        [resultado] = await dos_tracos.rodar(_orquestrador)
        assert not resultado.ok
        assert "sobr" in resultado.detalhe and sobra in resultado.detalhe

    async def test_caso_nao_rotulado_nao_passa_por_omissao(self):
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        traco.conjunto = "avaliacao"
        replay.salvar(traco)
        [resultado] = await dos_tracos.rodar(_orquestrador)
        assert not resultado.ok
        assert "capacidade" in resultado.detalhe

    async def test_caso_marca_nao_determinista_nao_vira_verde(self):
        await _turno_que_lista_arquivos()
        traco = dos_tracos.promover(replay.listar()[0].id, "leitura", ferramentas_incluem=["listar_arquivos"])
        traco.determinista = False
        replay.salvar(traco)
        [resultado] = await dos_tracos.rodar(_orquestrador)
        assert not resultado.ok
        assert "determinista" in resultado.detalhe


class TestCandidatos:
    async def test_leitura_do_disco_com_resultado_gravado_pode_ser_rotulada(self):
        await _turno_que_lista_arquivos()
        traco = replay.listar()[0]
        candidatos = dos_tracos.candidatos()
        assert [c["traco"] for c in candidatos] == [traco.id]
        assert candidatos[0]["ferramentas"] == ["listar_arquivos"]

    @pytest.mark.parametrize("tool", ["ler_arquivo", "listar_arquivos"])
    async def test_leitura_antiga_sem_resultado_fica_fora_da_bateria(self, tool):
        replay.gravar(
            mensagem="Confira os arquivos", respostas_llm=["conferi"],
            conjunto="desenvolvimento",
            resultado_observado={"mensagem": "conferi", "ferramentas": [tool]},
            ambiente={"despacho": "texto"},
        )
        assert dos_tracos.candidatos() == []

        resultado = await replay.bateria(_orquestrador)
        assert [p["ferramentas"] for p in resultado["pulados"]] == [[tool]]
        assert resultado["tracos"] == 0
        assert resultado["fiel"] is False
        assert resultado["falharam"] == []

    def test_leitura_variavel_nao_vira_candidato(self):
        replay.gravar(
            mensagem="Veja os processos", respostas_llm=["conferi"],
            conjunto="desenvolvimento", determinista=False,
            resultado_observado={"mensagem": "conferi", "ferramentas": ["inspecionar_ambiente"]},
        )
        assert dos_tracos.candidatos() == []


class TestCobertura:
    async def test_conta_as_capacidades_e_explicita_o_que_falta(self):
        await _turno_que_lista_arquivos()
        traco = dos_tracos.promover(replay.listar()[0].id, "leitura", ferramentas_incluem=["listar_arquivos"])
        resultado = dos_tracos.cobertura(capacidades=["leitura", "retomada", "retomada"])
        assert resultado["tracos"] == resultado["repetiveis"] == 1
        assert resultado["capacidades"] == {"leitura": {"casos": 1, "repetiveis": 1}}
        assert resultado["capacidades_sem_casos"] == ["retomada"]
        assert resultado["ferramentas"] == ["listar_arquivos"]
        assert resultado["invalidos"] == []
        assert replay.carregar(traco.id).resultado_esperado == traco.resultado_esperado

    async def test_caso_incompleto_nao_conta_como_capacidade_coberta(self):
        await _turno_que_lista_arquivos()
        traco = dos_tracos.promover(replay.listar()[0].id, "leitura", ferramentas_incluem=["listar_arquivos"])
        traco.resultados_ferramentas = []
        replay.salvar(traco)
        resultado = dos_tracos.cobertura(capacidades=["leitura"])
        assert resultado["repetiveis"] == 0
        assert resultado["capacidades"] == {"leitura": {"casos": 1, "repetiveis": 0}}
        assert resultado["capacidades_sem_casos"] == ["leitura"]
        assert "listar_arquivos" in resultado["invalidos"][0]["motivos"][0]

    async def test_rotulos_em_outro_idioma_nao_precisam_de_traducao(self):
        await _turno_que_lista_arquivos()
        dos_tracos.promover(replay.listar()[0].id, "文件读取", ferramentas_incluem=["listar_arquivos"])
        resultado = dos_tracos.cobertura(capacidades=["文件读取", "承認"])
        assert resultado["capacidades"] == {"文件读取": {"casos": 1, "repetiveis": 1}}
        assert resultado["capacidades_sem_casos"] == ["承認"]

    def test_conjunto_vazio_nao_vira_verde_no_comando(self, capsys):
        assert dos_tracos._main(["cobertura"]) == 1
        assert '"repetiveis": 0' in capsys.readouterr().out


def test_comando_de_avaliacao_usa_o_processo_isolado(monkeypatch):
    import subprocess
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    chamadas = []

    def rodar(argumentos, **opcoes):
        chamadas.append((argumentos, opcoes))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(subprocess, "run", rodar)
    assert dos_tracos._main(["rodar"]) == 7
    argumentos, opcoes = chamadas[0]
    assert argumentos[0] == sys.executable
    assert Path(argumentos[1]).name == "replay_bateria.py"
    assert argumentos[2:] == ["--avaliar"]
    assert opcoes == {"check": False}
