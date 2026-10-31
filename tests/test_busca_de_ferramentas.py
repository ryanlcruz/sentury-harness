"""A busca de ferramentas traz a certa entre as seis que vao a mesa.

A busca casa pelo radical ("lembra" acha "lembre") e o `quando_usar` fala
do jeito que a pessoa pede. Sem isso, "me lembra amanha" traz
`buscar_conversas` em vez do agendamento.
"""
import pytest

from sentury.tools.capability_catalog import build_catalog, search_catalog
from sentury.tools.registry import ferramentas_do_setor_ativo

PEDIDOS = [
    ("me lembra amanhã às 9h de pagar a conta", "agenda"),
    ("me avisa daqui a uma hora pra tomar remédio", "agenda"),
    ("lembra que eu prefiro respostas curtas", "memoria"),
    ("guarda que meu nome é Ryan", "memoria"),
    ("esquece o que eu te falei do meu emprego", "memoria"),
    ("o que você sabe sobre mim?", "memoria"),
    ("do que a gente falou semana passada sobre o orçamento?", "buscar_conversas"),
    ("quantas linhas tem o arquivo config.py?", "ler_arquivo"),
    ("o que tem na pasta de downloads?", "listar_arquivos"),
    ("cria um arquivo notas.txt com a lista de compras", "escrever_arquivo"),
    ("troca a porta de 8080 para 9090 no config.ini", "editar_arquivo"),
    ("qual o último commit do repositório?", "executar_comando"),
    ("qual a versão do python instalada?", "executar_comando"),
    ("pesquisa na internet o preço do dólar hoje", "buscar_web"),
    ("lê essa página https://exemplo.com/artigo", "ler_pagina"),
    ("entra no site e clica em entrar", "browser"),
    ("onde está definida a função montar?", "codigo"),
    ("quem chama a função validar?", "codigo"),
    ("soma a coluna vendas do csv", "executar_python"),
    ("faz um plano de 5 passos para migrar o banco", "criar_plano"),
    ("todo dia às 8h me manda o resumo das vendas", "criar_workflow"),
    ("o pacote requests é seguro de instalar?", "checar_pacote"),
    ("me manda o arquivo relatorio.pdf aqui", "entregar_arquivo"),
    ("desfaz a última edição do main.py", "restaurar_versao"),
]


@pytest.fixture(scope="module")
def catalogo():
    return build_catalog(ferramentas_do_setor_ativo(), [])


@pytest.mark.parametrize("pedido,esperada", PEDIDOS)
def test_ferramenta_certa_vai_a_mesa(catalogo, pedido, esperada):
    achadas = [e.name for e, _ in search_catalog(catalogo, pedido, limit=6) if e.kind == "tool"]
    assert esperada in achadas, achadas
