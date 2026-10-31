"""O trabalho pela metade volta sozinho para o turno.

O plano já morava em disco com o que falta e o que falhou; faltava alguém ler
isso quando a conversa recomeça. A lição de `retomada.py` vale aqui: instrução
não é garantia, então o que entra no histórico é ESTADO: qual plano, qual a
próxima tarefa, o que já falhou nela.
"""
import time
from types import SimpleNamespace

import pytest

from sentury.harness import plano_aberto
from sentury.memory import plano as _plano


@pytest.fixture
def trabalho(tmp_path, monkeypatch):
    """Planos numa pasta própria: o teste não lê o trabalho real de ninguém."""
    monkeypatch.setattr(_plano, "raiz_dos_planos", lambda *_a, **_k: tmp_path / "planos")
    monkeypatch.setattr(_plano, "_arquivo_de_estado",
                        lambda nome: tmp_path / "planos" / nome / "estado.json")
    return None


def _estado():
    return SimpleNamespace(history=[])


class TestSemPlano:
    def test_sem_nada_em_disco_nao_diz_nada(self, trabalho):
        assert plano_aberto.linha_de_contexto() is None

    def test_plano_fechado_nao_volta(self, trabalho):
        _plano.criar("fechado", "Tudo pronto", ["Unica tarefa"])
        _plano.marcar("fechado", "1", "feito")
        assert plano_aberto.planos_em_aberto() == []
        assert plano_aberto.linha_de_contexto() is None


class TestComPlanoAberto:
    @pytest.fixture
    def aberto(self, trabalho):
        _plano.criar(
            "queda-de-nps", "Investigar a queda",
            ["Separar por filial", "Provar a causa", "Montar o resumo"],
            contexto="O NPS do Sul caiu 8 pontos.",
        )
        _plano.marcar("queda-de-nps", "1", "feito")
        return "queda-de-nps"

    def test_diz_qual_plano_e_quanto_falta(self, aberto):
        linha = plano_aberto.linha_de_contexto()
        assert "queda-de-nps" in linha
        assert "1 de 3" in linha

    def test_aponta_a_proxima_tarefa_pelo_id(self, aberto):
        linha = plano_aberto.linha_de_contexto()
        assert "2 — Provar a causa" in linha

    def test_conta_a_tentativa_que_falhou(self, aberto):
        # Tentativa falha é evidência: sem ela o modelo repete o caminho que já
        # não deu certo e gasta o turno redescobrindo o mesmo.
        _plano.marcar(aberto, "2", "falhou", nota="o sandbox barrou o import")
        linha = plano_aberto.linha_de_contexto()
        assert "Tentativas registradas: 1" in linha and "ver_plano" in linha

    def test_entra_no_historico_uma_vez_so(self, aberto):
        estado = _estado()
        assert plano_aberto.aplicar_no_turno(estado) is True
        assert plano_aberto.aplicar_no_turno(estado) is False
        assert len(estado.history) == 1
        assert estado.history[0]["priority"] == "NORMAL"

    def test_manda_ignorar_quando_o_assunto_for_outro(self, aberto):
        """Contexto que se impõe vira sequestro de turno: quem pergunta outra
        coisa tem que receber outra coisa."""
        assert "A relação com o pedido atual não foi determinada" in plano_aberto.linha_de_contexto()

    def test_nao_e_ordem_de_continuar(self, aberto):
        """`retomada.py` aprendeu isso do jeito caro: instrução o modelo
        esquece, estado ele usa."""
        linha = plano_aberto.linha_de_contexto().lower()
        assert "lembre-se" not in linha and "você deve" not in linha


class TestPlanoVelho:
    def test_plano_parado_ha_semanas_nao_volta(self, trabalho, monkeypatch):
        """Plano de um mês atrás é arqueologia: citá-lo empurra o turno para a
        tarefa errada."""
        _plano.criar("antigo", "Coisa velha", ["Tarefa que ficou"])
        velho = time.time() - (plano_aberto.DIAS_DE_VALIDADE + 5) * 86400
        monkeypatch.setattr(plano_aberto, "_mexido_em", lambda *_a, **_k: velho)
        assert plano_aberto.linha_de_contexto() is None


class TestFalhaNaoDerrubaOTurno:
    def test_disco_ilegivel_nao_quebra_a_conversa(self, monkeypatch):
        monkeypatch.setattr(_plano, "listar", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disco")))
        assert plano_aberto.planos_em_aberto() == []
        assert plano_aberto.aplicar_no_turno(_estado()) is False


class TestOPortaoChegaNoTurno:
    """O portão era só dado. A retomada dizia "a próxima é 2: Você aprova
    subir?" como se fosse tarefa a executar, e o modelo executava."""

    def _com(self, tmp_path, linhas):
        pasta = tmp_path / ".sentury" / "planos" / "obra"
        pasta.mkdir(parents=True)
        (pasta / "tarefas.md").write_text(linhas, encoding="utf-8")
        from sentury.memory import plano
        plano._arquivo_de_estado("obra").unlink(missing_ok=True)
        return plano_aberto.linha_de_contexto(tmp_path)

    def test_diz_que_travou_e_manda_perguntar(self, tmp_path):
        linha = self._com(tmp_path, "- [x] 1. levantar\n- [ ]! 2. Você aprova subir?\n")
        assert "Portão pendente" in linha and "Próxima: 2" in linha
        assert "etapas posteriores aguardam aprovação" in linha

    def test_leva_as_opcoes_junto(self, tmp_path):
        linha = self._com(tmp_path, (
            "- [x] 1. levantar\n"
            "- [ ]! 2. Você aprova subir?\n"
            "  - opção: sim, pode subir\n"
            "  - opção: não, revisar antes\n"
        ))
        assert "sim, pode subir" in linha and "não, revisar antes" in linha

    def test_tarefa_comum_continua_sendo_a_proxima(self, tmp_path):
        linha = self._com(tmp_path, "- [x] 1. feita\n- [ ] 2. seguir\n")
        assert "Próxima: 2" in linha and "Portão pendente" not in linha

    def test_passo_recorrente_manda_agendar(self, tmp_path):
        """Sem isso ele roda uma vez e vira tarefa comum: a recorrência morre
        na primeira execução."""
        linha = self._com(tmp_path, "- [ ] 1. Resumo semanal\n  _Agenda: 0 8 * * 1_\n")
        assert "Agenda registrada: 0 8 * * 1" in linha
        assert "schedule_task" not in linha



class TestEstadoSemRoteamentoPorPalavra:
    @pytest.mark.parametrize("pedido", ["continua", "oi", "use the earlier plan", "继续", "Qual é a previsão?"])
    def test_estado_nao_depende_da_palavra(self, pedido, trabalho):
        _plano.criar("aberto", "Um plano", ["Uma tarefa"])
        estado = _estado()
        assert plano_aberto.aplicar_no_turno(estado, pedido) is True
        assert len(estado.history) == 1
        assert "A relação com o pedido atual não foi determinada" in estado.history[0]["content"]

    def test_plano_atualizado_substitui_o_estado_antigo(self, trabalho):
        _plano.criar("aberto", "Um plano", ["Uma", "Duas"])
        estado = _estado()
        assert plano_aberto.aplicar_no_turno(estado)
        _plano.marcar("aberto", "1", "feito")
        assert plano_aberto.aplicar_no_turno(estado)
        assert len(estado.history) == 1
        assert "1 de 2" in estado.history[0]["content"]
        _plano.marcar("aberto", "2", "feito")
        assert plano_aberto.aplicar_no_turno(estado) is False
        assert estado.history == []

    def test_fato_curto_mesmo_com_titulo_longo(self, trabalho):
        _plano.criar("aberto", "Um plano", ["título " * 1000])
        assert len(plano_aberto.linha_de_contexto()) <= 900
