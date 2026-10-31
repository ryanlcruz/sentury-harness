"""Ele diz o que vai fazer antes de fazer.

O texto sempre existiu: quando o modelo devolve `tool_calls` nativos, ele
escreve o motivo junto. O orquestrador montava o plano só dos calls e jogava o
texto fora, então a ferramenta rodava sem motivo na tela.
"""
import pytest

from sentury.harness.narracao import Narrador, TETO, limpar
from sentury.harness.turno import Turno


class TestLimpeza:
    def test_frase_normal_passa(self):
        assert limpar("Vou olhar a pasta primeiro.") == "Vou olhar a pasta primeiro."

    def test_tira_o_bloco_de_codigo(self):
        bruto = 'Vou contar as tabelas.\n```json\n{"plan": []}\n```'
        assert limpar(bruto) == "Vou contar as tabelas."

    def test_so_json_nao_e_narracao(self):
        assert limpar('```json\n{"plan": []}\n```') is None

    def test_vazio_e_none(self):
        assert limpar("") is None and limpar(None) is None

    def test_pontuacao_solta_nao_vira_fala(self):
        assert limpar("  :  ") is None

    def test_texto_longo_e_resposta_antecipada_nao_narracao(self):
        """Mostrar a resposta no meio do turno entrega algo que a resposta
        final ainda vai contradizer."""
        assert limpar("a" * (TETO + 1)) is None
        assert limpar("a" * TETO) is not None


class TestNarrador:
    def test_nao_repete_a_mesma_fala(self):
        n = Narrador()
        assert n.proxima("Vou ler o arquivo.") == "Vou ler o arquivo."
        assert n.proxima("Vou ler o arquivo.") is None

    def test_diferenca_so_de_espaco_e_caixa_conta_como_repeticao(self):
        n = Narrador()
        n.proxima("Vou ler o arquivo.")
        assert n.proxima("  VOU   ler o arquivo.  ") is None

    def test_fala_nova_passa(self):
        n = Narrador()
        n.proxima("Vou ler o arquivo.")
        assert n.proxima("Agora conto as linhas.") == "Agora conto as linhas."

    def test_cada_turno_tem_seu_narrador(self):
        """O narrador é do turno: a mesma frase no turno seguinte vale de novo."""
        assert Narrador().proxima("Vou ler o arquivo.") is not None


class TestFalaGrudaNoPasso:
    """Emitida solta, a fala ia para o topo e as voltas empilhavam em cima:
    três frases juntas e uma execução embaixo, sem dizer qual era de qual."""

    class _Planner:
        last_model = "m"
        last_reasoning_summary = None

    class _Orq:
        def __init__(self):
            self.planner = TestFalaGrudaNoPasso._Planner()
            self.turno = Turno()
            self.turno.contrato = "ok"
            self.turno.narracao = "Vou olhar a pasta."

    def test_a_fala_fica_guardada_em_vez_de_virar_evento(self):
        from sentury.harness.narracao import apos_planejar

        orq, log, ditos = self._Orq(), {}, []
        apos_planejar(orq, log, Narrador(), ditos.append)
        assert orq.turno.fala_da_volta == "Vou olhar a pasta."
        assert ditos == [None], "o raciocínio continua saindo pelo canal dele"

    def test_a_volta_seguinte_sem_fala_nova_nao_herda_a_anterior(self):
        from sentury.harness.narracao import apos_planejar

        orq, narrador = self._Orq(), Narrador()
        apos_planejar(orq, {}, narrador, lambda _: None)
        apos_planejar(orq, {}, narrador, lambda _: None)
        assert orq.turno.fala_da_volta is None, "mesma frase de novo não é fala nova"
