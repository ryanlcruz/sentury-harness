"""O guardrail de dinheiro pergunta pelo numero, nao pelo simbolo.

Perguntar pelo simbolo deixa passar dolar, euro, "1,2 milhao" e "3M", e acusa
"R$ 150,00" quando a ferramenta devolveu `150.0` sem simbolo. A pergunta certa e
se o valor tem lastro na evidencia: assim vale em qualquer moeda e setor.
"""
import pytest

from sentury.harness.grounding import find_ungrounded

# Uma evidencia de e-commerce: tem dinheiro, ao contrario do dataset de CX.
EVIDENCIA = "nps: 32.4 | ticket_medio: 150.0 | volume: 5000 | economia_total: 12000"


def acusou(texto: str, evidencia: str = EVIDENCIA) -> bool:
    return bool(find_ungrounded(texto, evidencia)["currency"])


# --------------------------------------------- o que tem lastro, passa

@pytest.mark.parametrize("texto", [
    "Ticket medio de R$ 150,00",
    "saving of $12,000",
    "€ 150",
    "faturamento de 5000 reais",
    "economia de R$ 12.000",
])
def test_valor_que_esta_na_evidencia_passa(texto):
    """O caso que mais importa: em e-commerce o dado TEM dinheiro, e a versao
    anterior reescrevia resposta correta porque a evidencia nao trazia o
    simbolo."""
    assert not acusou(texto), texto


def test_conta_derivada_continua_legitima():
    """Analista soma e subtrai o tempo todo. Com 150 e 12000 na mesa, citar a
    diferenca e trabalho, nao invencao: e o guard nunca pode chamar de
    fabricacao o que a gente PEDE que ele faca."""
    assert not acusou("diferenca de R$ 11.850")


# ----------------------------------------- o que nao tem lastro, acusa

@pytest.mark.parametrize("texto", [
    "economia de R$ 100.000",
    "custo de US$ 99 mil",
    "saving of $77,777",
    "reducao de £ 4.321",
])
def test_valor_inventado_e_acusado(texto):
    assert acusou(texto), texto


def test_pega_moeda_que_antes_escapava():
    """De sete formas, a versao anterior pegava uma. Estas quatro passavam."""
    for texto in ("US$ 50 mil", "$100,000", "€ 2.400", "GBP 900"):
        assert acusou(texto, evidencia="nps: 32.4"), texto


# ------------------------------------------- sem premissa de dominio

def test_a_premissa_sobre_o_dataset_morreu():
    """A regra antiga era "o dataset de CX nao tem valor monetario, logo
    qualquer R$ e fabricado". Isso e falso em e-commerce."""
    import inspect

    from sentury.harness import guardrails

    fonte = inspect.getsource(guardrails.currency_guardrail)
    # O docstring CITA a regra antiga para explicar por que ela caiu, e isso e
    # documentacao, nao residuo. O que nao pode voltar e o COMPORTAMENTO: a
    # decisao olha a evidencia, nao o setor.
    assert "find_ungrounded" in fonte
    assert "NUMERO" in fonte or "numero" in fonte


def test_o_mesmo_texto_muda_de_veredito_conforme_o_dado():
    """Prova de que o guard olha o DADO e nao o setor: a mesma frase e legitima
    onde o valor existe e fabricada onde nao existe."""
    assert not acusou("R$ 150,00", evidencia="ticket_medio: 150.0")
    assert acusou("R$ 150,00", evidencia="nps: 32.4")


# ------------------------------------------------------ nao chuta na duvida

def test_sem_digito_reconhecivel_nao_acusa():
    """Na duvida o guard se cala: falso positivo custa uma reescrita e a
    confianca de quem le."""
    assert not acusou("custou muito dinheiro")
    assert not acusou("R$")


def test_evidencia_vazia_nao_quebra():
    assert acusou("R$ 100", evidencia="")
    assert not acusou("sem numero nenhum", evidencia="")


class TestAvisaEmVezDeReescrever:
    """Avisar em vez de reescrever: bloquear custaria uma chamada de modelo por
    resposta suspeita e apagaria também os valores que tinham lastro."""

    def _guard(self, monkeypatch, evidencia):
        from sentury.harness import guardrails

        monkeypatch.setattr(guardrails, "evidence_text", lambda _: evidencia)
        return guardrails

    def test_nada_bloqueia_mais(self, monkeypatch):
        g = self._guard(monkeypatch, EVIDENCIA)
        assert g.OUTPUT_GUARDRAILS == []
        assert g.currency_guardrail(None, "economia de R$ 98.000").tripwire_triggered is False

    def test_valor_sem_lastro_vira_aviso_com_o_numero(self, monkeypatch):
        g = self._guard(monkeypatch, EVIDENCIA)
        aviso = g.currency_guardrail(None, "A economia foi de R$ 98.000.").aviso
        assert aviso and "R$ 98.000" in aviso
        # O regex de dinheiro e guloso e levava o ponto final da frase junto.
        assert "R$ 98.000." not in aviso

    def test_valor_com_lastro_nao_avisa(self, monkeypatch):
        g = self._guard(monkeypatch, EVIDENCIA)
        assert g.currency_guardrail(None, "O ticket médio é R$ 150,00.").aviso is None

    def test_o_guard_de_moeda_virou_observador(self, monkeypatch):
        g = self._guard(monkeypatch, EVIDENCIA)
        assert g.currency_guardrail in g.OBSERVERS


# ------------------------------------- o que vira aviso no log do servidor

async def test_so_vira_aviso_no_log_o_que_chega_a_pessoa(caplog):
    """Decimal sem lastro numa conversa comum ("Python 3.13") é telemetria;
    dinheiro sem lastro avisa a pessoa e por isso também aparece no log."""
    import logging

    from sentury.data.store import SemDados
    from sentury.harness.orchestrator import SenturyOrchestrator, logger
    from sentury.harness.state import AnalysisState

    orq = SenturyOrchestrator(planner=None, responder=None, store=SemDados())
    with caplog.at_level(logging.WARNING, logger=logger.name):
        await orq._enforce_grounding(AnalysisState.new("s", "u"), "Use o Python 3.13 com o pip 24.2.")
    assert not [r for r in caplog.records if "grounding_decimals" in r.getMessage()]
    assert orq.turno.grounding.get("grounding_decimals"), "a contagem continua na telemetria"

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=logger.name):
        await orq._enforce_grounding(AnalysisState.new("s", "u"), "A economia foi de R$ 98.000.")
    assert [r for r in caplog.records if "grounding_currency" in r.getMessage()]
