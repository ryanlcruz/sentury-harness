"""O sandbox de Python enxerga o que o dono liberou: e so isso.

Ate aqui `_confined_path` recusava qualquer caminho fora da raiz do sandbox, e o
namespace pre-carregava so os DataFrames do dominio. Consequencia pratica:
"analise o arquivo que esta nesta pasta" era impossivel: o agente tinha pandas
na mao e nao conseguia ABRIR o arquivo. O Python virava uma ferramenta do
DomainPack disfarcada de ferramenta geral.

A permissao reusada e a que ja existe: global (`tudo_liberado`) e por pasta
(`raiz_de_trabalho` + `pastas_extras`). Um segundo sistema de permissao aqui
seriam duas listas para manter, e uma delas desatualizada.
"""
import asyncio
from pathlib import Path

import pytest

from sentury.exec.python_exec import _confined_path, executar_python


@pytest.fixture(autouse=True)
def espaco(monkeypatch, tmp_path):
    """Nenhum teste toca a configuracao de pastas da maquina."""
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    yield


def _liberar(monkeypatch, *pastas):
    from sentury.exec import python_exec

    monkeypatch.setattr(python_exec, "_tudo_liberado", lambda: False)
    monkeypatch.setattr(
        python_exec, "_bases_permitidas",
        lambda: [python_exec._SANDBOX_ROOT] + [Path(p).resolve() for p in pastas],
    )


def test_le_arquivo_em_pasta_liberada(monkeypatch, tmp_path):
    pasta = tmp_path / "dados-do-usuario"
    pasta.mkdir()
    alvo = pasta / "planilha.csv"
    alvo.write_text("regiao,valor\nsul,100\n", encoding="utf-8")
    _liberar(monkeypatch, pasta)

    resolvido = _confined_path(str(alvo), for_write=False)
    assert resolvido == alvo.resolve()


def test_recusa_pasta_que_ninguem_liberou(monkeypatch, tmp_path):
    fora = tmp_path / "pasta-alheia"
    fora.mkdir()
    (fora / "segredo.txt").write_text("x", encoding="utf-8")
    _liberar(monkeypatch, tmp_path / "outra")

    with pytest.raises(PermissionError, match="fora do espaço liberado"):
        _confined_path(str(fora / "segredo.txt"), for_write=False)


def test_a_mensagem_diz_o_que_fazer(monkeypatch, tmp_path):
    """Recusar sem dizer como liberar transfere o problema para o usuario."""
    _liberar(monkeypatch, tmp_path / "nada")
    with pytest.raises(PermissionError) as erro:
        _confined_path(str(tmp_path / "x" / "y.csv"), for_write=False)
    assert "Harness" in str(erro.value)


def test_escrita_continua_so_de_artefato(monkeypatch, tmp_path):
    """Ler o que foi liberado e uma coisa; escrever `.py` na pasta do usuario e
    outra. A abertura de leitura nao pode afrouxar a de escrita.

    Script agora pode ser gravado, mas so no rascunho: o gate passou a ser a
    hora de rodar. Na pasta do usuario continua recusado, porque ali o risco
    nao e execucao: e sobrescrever o codigo dele."""
    pasta = tmp_path / "liberada"
    pasta.mkdir()
    _liberar(monkeypatch, pasta)

    assert _confined_path(str(pasta / "grafico.png"), for_write=True)
    with pytest.raises(PermissionError, match="só é permitido no rascunho"):
        _confined_path(str(pasta / "codigo.py"), for_write=True)


def test_permissao_global_abre_tudo(monkeypatch, tmp_path):
    """A global existe e e escolha explicita do dono; quando ligada, o sandbox
    deixa de ser o limite."""
    from sentury.exec import python_exec

    monkeypatch.setattr(python_exec, "_tudo_liberado", lambda: True)
    longe = tmp_path / "qualquer" / "lugar.csv"
    longe.parent.mkdir(parents=True)
    longe.write_text("a,b\n", encoding="utf-8")

    assert _confined_path(str(longe), for_write=False) == longe.resolve()


def test_ponto_ponto_nao_escapa(monkeypatch, tmp_path):
    """`a/../../etc/passwd` e barrado pelo que E depois do resolve, nao pelo
    que parece antes dele."""
    pasta = tmp_path / "liberada"
    pasta.mkdir()
    _liberar(monkeypatch, pasta)

    with pytest.raises(PermissionError):
        _confined_path(str(pasta / ".." / ".." / "fora.txt"), for_write=False)


def test_o_agente_de_fato_le_um_arquivo_do_usuario(monkeypatch, tmp_path):
    """O caso que motivou tudo, ponta a ponta."""
    pasta = tmp_path / "dados"
    pasta.mkdir()
    (pasta / "vendas.csv").write_text("regiao,valor\nsul,100\nsul,250\n", encoding="utf-8")
    _liberar(monkeypatch, pasta)

    codigo = (
        f'with open(r"{pasta / "vendas.csv"}", encoding="utf-8") as f:\n'
        '    linhas = f.read().splitlines()\n'
        # O contrato do sandbox e `resultado` ou `print()`: variavel solta nao
        # volta, e o proprio sandbox avisa isso quando nenhum dos dois aparece.
        'resultado = sum(float(l.split(",")[1]) for l in linhas[1:])\n'
    )
    devolvido = asyncio.run(executar_python(None, codigo))

    assert not devolvido.get("erro"), devolvido.get("erro")
    assert devolvido.get("resultado") == 350.0
