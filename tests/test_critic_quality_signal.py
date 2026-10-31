"""O sinal de qualidade que vai para o RobinBandit sai da conferência, não de
um segundo passe do modelo.

Uma autocrítica por modelo custaria uma chamada a mais e reescreveria a
resposta sem avisar. A conferência determinística já diz se o número tem
origem, de graça. Este teste guarda as três propriedades que o bandit precisa
para não ficar cego nem surdo.
"""
from sentury.harness.guardrails import veredito


def test_aviso_de_lastro_reprova_o_provedor():
    """Inventar valor é o defeito que a autocrítica existia para pegar."""
    assert veredito("A economia foi de R$ 98.000.", houve_aviso=True) is False


def test_valor_com_origem_aprova():
    assert veredito("O ticket médio é R$ 150,00.", houve_aviso=False) is True


def test_resposta_sem_valor_nenhum_nao_gera_sinal():
    """Marcar tudo como bom achata o bandit: ele para de distinguir quem
    inventa de quem não inventa. Sem valor não há prova de fidelidade."""
    assert veredito("Listei a pasta e não havia nada lá.", houve_aviso=False) is None


def test_qualquer_moeda_conta_nao_so_real():
    for texto in ("custou US$ 40", "custou €40", "custou 40 dólares"):
        assert veredito(texto, houve_aviso=False) is True, texto


def test_texto_vazio_nao_quebra():
    assert veredito("", houve_aviso=False) is None
    assert veredito(None, houve_aviso=False) is None
