"""Pedir para VER código não executa código. Três camadas, e nenhuma adivinha intenção.

A preocupação: *"podemos querer ver um código no chat, e o harness pode acabar
executando"*. Ela é justa: e já aconteceu. A docstring de
`extrair_bloco_declarado` registra o bug: a execução era inferida do texto ao
redor (`plt.`, `.png`), então *"me passa um código em python que salva um
gráfico"* rodava no sandbox em vez de só mostrar.

A defesa de hoje tem três camadas, e este arquivo fixa as três. Elas são
independentes de propósito: a primeira diz a regra, a segunda a obriga, a terceira
limita o dano se as duas primeiras falharem.

1. **O prompt declara a regra.** O modelo é instruído sobre quando marcar.
2. **A cerca obriga.** Só roda bloco marcado, e a marca é sintática, não inferida.
3. **O sandbox limita.** Um bloco marcado ainda não importa `os`, não abre rede e
   só escreve artefato dentro do rascunho.

## O que NÃO entrou, e por quê

Tentei um quarto: um regex sobre a mensagem do usuário ("me mostra", "me passa",
"sem executar") para vetar a execução. Está fora de propósito. Adivinhar intenção
por lista de palavras é a mesma doença de uma lista de imports permitidos: erra
em tudo que ninguém escreveu na lista, e erra em silêncio.

A decisão é sobre o comando, nunca sobre as palavras de quem pediu. Aqui o bloco
inline roda dentro do sandbox confinado, então não há operação perigosa a
detectar: a camada 3 faz esse trabalho por construção.
"""
import pathlib

from sentury.llm.action_parser import extrair_bloco_declarado

CODIGO = "plt.plot([1, 2, 3])\nplt.savefig('g.png')"
RAIZ = pathlib.Path(__file__).resolve().parent.parent


def _cerca(marca: str) -> str:
    return f"```python{marca}\n{CODIGO}\n```"


# ------------------------------------------- camada 1: a regra é declarada

def test_o_prompt_diz_quando_marcar():
    """Sem a regra escrita, a camada 2 vira sorte: o modelo marca por hábito."""
    fonte = (RAIZ / "sentury" / "artifacts" / "planner.py").read_text(encoding="utf-8")
    assert "```python run" in fonte
    assert "LER" in fonte and "nao e executado" in fonte


# ------------------------------------------- camada 2: a cerca obriga

def test_bloco_sem_marca_nao_roda():
    assert extrair_bloco_declarado(_cerca("")) is None


def test_bloco_marcado_roda():
    assert "savefig" in (extrair_bloco_declarado(_cerca(" run")) or "")


def test_a_marca_e_sintatica_e_nao_inferida():
    """A regressão a evitar é a volta do bug: inferir execução do conteúdo.

    Um bloco cheio de `plt.` e `.png` sem marca continua sendo código para ler.
    """
    tentador = "```python\nimport matplotlib.pyplot as plt\nplt.savefig('grafico.png')\n```"
    assert extrair_bloco_declarado(tentador) is None


def test_prosa_ao_redor_nao_muda_a_decisao():
    assert extrair_bloco_declarado(
        "Vou gerar agora mesmo o grafico e salvar o png:\n\n" + _cerca("")
    ) is None


# ------------------------------- camada 3: o que um bloco marcado pode fazer

async def test_bloco_marcado_ainda_nao_alcanca_o_sistema():
    from sentury.exec.python_exec import executar_python

    r = await executar_python(None, "import os\nresultado = os.getcwd()")
    assert r.get("erro"), "o sandbox deixou importar os"


async def test_bloco_marcado_grava_no_rascunho_e_nao_na_pasta_de_codigo():
    from sentury.exec.python_exec import _SANDBOX_ROOT, executar_python

    nome = "prova_camada3.png"
    await executar_python(None, f"plt.plot([1,2])\nplt.savefig({nome!r})")
    try:
        assert not (RAIZ / nome).exists(), "gravou na pasta de código"
    finally:
        (pathlib.Path(_SANDBOX_ROOT) / nome).unlink(missing_ok=True)
