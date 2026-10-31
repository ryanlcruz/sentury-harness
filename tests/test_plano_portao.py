"""O plano ganha fase: um passo pode TRAVAR o que vem depois.

Sem isso o plano era uma lista, e lista não tem fase: o agente seguia para o
item 5 com a aprovação do item 4 ainda pendente. O portão é `- [ ]! 4. ...`, no
mesmo formato do opcional (`*`), porque o checklist continua sendo Markdown
para uma pessoa ler e editar.
"""
from pathlib import Path

from sentury.memory import plano


def _plano(tmp_path: Path, linhas: str) -> Path:
    """Um plano novo, com o checklist E o histórico zerados.

    O `tmp_path` isola o Markdown, mas o estado de execução mora fora do
    trabalho de propósito (`SENTURY_HOME`, isolado uma vez por rodada no
    conftest) e é indexado por NOME. Sem limpar, todos os testes que usam
    "obra" herdam as tentativas uns dos outros, foi o que aconteceu: uma
    tarefa com duas falhas aparecia com seis.
    """
    pasta = tmp_path / ".sentury" / "planos" / "obra"
    pasta.mkdir(parents=True)
    (pasta / "tarefas.md").write_text(linhas, encoding="utf-8")
    plano._arquivo_de_estado("obra").unlink(missing_ok=True)
    return tmp_path


class TestOFormato:
    def test_portao_e_lido_do_markdown(self, tmp_path):
        raiz = _plano(tmp_path, "- [ ]! 1. Você aprova subir?\n")
        t = plano.ler("obra", raiz)[0]
        assert t.gate is True and t.opcional is False

    def test_portao_nao_e_opcional(self, tmp_path):
        """Os dois sinais ocupam a mesma casa: confundi-los inverteria o
        sentido: o opcional pode ser pulado, o portão existe para não ser."""
        raiz = _plano(tmp_path, "- [ ]* 1. Se der tempo\n")
        t = plano.ler("obra", raiz)[0]
        assert t.opcional is True and t.gate is False

    def test_o_sinal_volta_igual_ao_reescrever(self, tmp_path):
        raiz = _plano(tmp_path, "- [ ]! 1. Aprovar\n- [ ]* 2. Talvez\n")
        lidas = plano.ler("obra", raiz)
        assert lidas[0].como_linha().startswith("- [ ]! ")
        assert lidas[1].como_linha().startswith("- [ ]* ")


class TestOCiclo:
    def _tarefas(self, **marcas):
        t = [
            plano.Tarefa(id="1", titulo="levantar"),
            plano.Tarefa(id="2", titulo="Você aprova?", gate=True),
            plano.Tarefa(id="3", titulo="executar"),
        ]
        for i, feito in marcas.items():
            t[int(i)].feito = feito
        return t

    def test_trava_no_portao_pendente(self, ):
        c = plano.ciclo(self._tarefas(**{"0": True}))
        assert c["estado"] == "travado"
        assert c["travado_por"]["titulo"] == "Você aprova?"

    def test_resolvido_o_portao_o_plano_anda(self):
        c = plano.ciclo(self._tarefas(**{"0": True, "1": True}))
        assert c["estado"] == "aberto" and c["travado_por"] is None

    def test_fecha_quando_nao_falta_obrigatoria(self):
        c = plano.ciclo(self._tarefas(**{"0": True, "1": True, "2": True}))
        assert c["estado"] == "fechado"

    def test_opcional_pendente_nao_segura_o_fechamento(self):
        t = [plano.Tarefa(id="1", titulo="a", feito=True),
             plano.Tarefa(id="2", titulo="b", opcional=True)]
        assert plano.ciclo(t)["estado"] == "fechado"

    def test_portao_ainda_longe_nao_trava_agora(self):
        """Só trava quando o portão é a PRÓXIMA obrigatória. Travar antes
        pararia o trabalho que existe justamente para chegar nele."""
        t = [plano.Tarefa(id="1", titulo="levantar"),
             plano.Tarefa(id="2", titulo="Aprova?", gate=True)]
        assert plano.ciclo(t)["estado"] == "aberto"


def test_o_resumo_conta_que_travou(tmp_path):
    raiz = _plano(tmp_path, "- [x] 1. levantar\n- [ ]! 2. Você aprova?\n- [ ] 3. subir\n")
    r = plano.resumo("obra", raiz)
    assert r["estado"] == "travado"
    assert r["travado_por"]["id"] == "2"
    # A proxima e o PORTAO, nao o passo depois dele: apontar o 3 seria convidar
    # a pular a decisao que existe para nao ser pulada.
    assert r["proxima"]["id"] == "2"


class TestOPortaoComoObjeto:
    """Portão sem opção é pergunta aberta no meio da execução, e quem responde
    tem que adivinhar o que vale."""

    def test_opcoes_saem_das_linhas_sob_o_portao(self, tmp_path):
        raiz = _plano(tmp_path, (
            "- [ ]! 1. Você aprova subir para produção?\n"
            "  - opção: sim, pode subir\n"
            "  - opção: não, revisar antes\n"
        ))
        t = plano.ler("obra", raiz)[0]
        assert t.opcoes == ["sim, pode subir", "não, revisar antes"]

    def test_opcao_sem_recuo_nao_conta(self, tmp_path):
        """Linha na margem é prosa do documento, não opção do item acima."""
        raiz = _plano(tmp_path, "- [ ]! 1. Aprova?\n- opção: solta\n")
        assert plano.ler("obra", raiz)[0].opcoes == []

    def test_campo_vazio_nao_polui_o_publico(self, tmp_path):
        raiz = _plano(tmp_path, "- [ ] 1. Só uma tarefa\n")
        assert "opcoes" not in plano.ler("obra", raiz)[0].publico()


class TestAgendaNoPasso:
    """A ferramenta de agendar já existia; faltava o PLANO saber: senão
    'toda segunda às 8' vira chamada solta que a retomada não encontra."""

    def test_agenda_e_lida(self, tmp_path):
        raiz = _plano(tmp_path, "- [ ] 1. Resumo semanal\n  _Agenda: 0 8 * * 1_\n")
        t = plano.ler("obra", raiz)[0]
        assert t.agenda == "0 8 * * 1"
        assert t.publico()["agenda"] == "0 8 * * 1"

    def test_agenda_nao_atrapalha_o_requisito(self, tmp_path):
        raiz = _plano(tmp_path, (
            "- [ ] 1. Resumo semanal\n"
            "  _Agenda: 0 8 * * 1_\n"
            "  _Requisito: o gestor lê na segunda_\n"
        ))
        t = plano.ler("obra", raiz)[0]
        assert t.agenda == "0 8 * * 1"
        assert t.requisitos == "o gestor lê na segunda"


class TestReaberto:
    def test_plano_que_fechou_e_voltou_a_ter_trabalho(self):
        t = [plano.Tarefa(id="1", titulo="a", feito=True),
             plano.Tarefa(id="2", titulo="nova")]
        assert plano.ciclo(t, ja_fechou=True)["estado"] == "reaberto"

    def test_sem_ter_fechado_antes_e_so_aberto(self):
        t = [plano.Tarefa(id="1", titulo="a")]
        assert plano.ciclo(t, ja_fechou=False)["estado"] == "aberto"

    def test_reaberto_nao_atropela_o_travado(self):
        """Saber que o escopo cresceu não é mais urgente que o portão."""
        t = [plano.Tarefa(id="1", titulo="Aprova?", gate=True)]
        assert plano.ciclo(t, ja_fechou=True)["estado"] == "travado"


def test_fechar_e_ganhar_tarefa_nova_vira_reaberto(tmp_path):
    """De ponta a ponta: o Markdown conta o que falta, e só o estado guardado
    conta que um dia não faltava nada."""
    raiz = _plano(tmp_path, "- [ ] 1. única\n")
    plano.marcar("obra", "1", "feito", trabalho=raiz)
    assert plano.resumo("obra", raiz)["estado"] == "fechado"

    alvo = raiz / ".sentury" / "planos" / "obra" / "tarefas.md"
    alvo.write_text(alvo.read_text(encoding="utf-8") + "- [ ] 2. apareceu depois\n",
                    encoding="utf-8")
    assert plano.resumo("obra", raiz)["estado"] == "reaberto"


class TestTelemetriaDoPlano:
    """`loop_stats` mede o turno; um workflow atravessa vários e ninguém media.

    A pergunta que decide se vale continuar é: há tarefa queimando tentativa
    sem sair do lugar? Quatro falhas na mesma tarefa em três sessões não
    apareciam em lugar nenhum: cada turno via só a sua.
    """

    def test_conta_sessoes_e_tentativas_do_historico(self, tmp_path):
        raiz = _plano(tmp_path, "- [ ] 1. uma\n- [ ] 2. outra\n")
        plano.marcar("obra", "1", "falhou", session_id="s1", trabalho=raiz)
        plano.marcar("obra", "1", "feito", session_id="s2", trabalho=raiz)
        plano.marcar("obra", "2", "fazendo", session_id="s2", trabalho=raiz)
        t = plano.telemetria("obra", raiz)
        assert t["tentativas"] == 3 and t["sessoes"] == 2

    def test_tarefa_que_queima_tentativa_aparece(self, tmp_path):
        raiz = _plano(tmp_path, "- [ ] 1. teimosa\n")
        for i in range(plano.EMPERRADA_A_PARTIR_DE):
            plano.marcar("obra", "1", "falhou", session_id=f"s{i}", trabalho=raiz)
        emperradas = plano.telemetria("obra", raiz)["emperradas"]
        assert len(emperradas) == 1 and emperradas[0]["falhas"] == 3

    def test_duas_falhas_ainda_nao_e_sinal(self, tmp_path):
        """As duas primeiras são normais; a terceira é que deixa de ser
        persistência e vira teimosia."""
        raiz = _plano(tmp_path, "- [ ] 1. quase\n")
        plano.marcar("obra", "1", "falhou", trabalho=raiz)
        plano.marcar("obra", "1", "falhou", trabalho=raiz)
        assert plano.telemetria("obra", raiz)["emperradas"] == []

    def test_carrega_o_estado_do_ciclo_junto(self, tmp_path):
        raiz = _plano(tmp_path, "- [x] 1. feita\n- [ ]! 2. Aprova?\n")
        t = plano.telemetria("obra", raiz)
        assert t["estado"] == "travado" and t["travado_por"]["id"] == "2"

    def test_plano_inexistente_nao_quebra(self, tmp_path):
        assert plano.telemetria("nao-existe", tmp_path)["ok"] is False
