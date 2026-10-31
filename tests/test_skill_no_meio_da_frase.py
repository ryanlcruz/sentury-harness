"""A skill escolhida pelo `/` vale em qualquer ponto da frase."""
from sentury.harness.roteamento_de_skill import explicita

NOMES = {"montar-spec", "root-cause", "root-cause-analysis"}


def test_barra_no_meio_e_no_fim_da_frase():
    assert explicita("monte isso com /montar-spec para a API", NOMES) == "montar-spec"
    assert explicita("investigue a queda usando /root-cause-analysis.", NOMES) == "root-cause-analysis"
    assert explicita("[montar-spec] faça", NOMES) == "montar-spec"


def test_barra_de_caminho_ou_nome_desconhecido_nao_e_skill():
    assert explicita("leia /var/log/root-causes.txt", NOMES) is None
    assert explicita("use /inventada aqui", NOMES) is None
