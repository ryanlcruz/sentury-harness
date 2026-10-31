"""Gatilho dispara porque o evento aconteceu, nao porque o modelo pediu.

Uma instrucao no prompt e um pedido: o modelo pode seguir, esquecer, ou achar
que nao vale a pena. Estes testes protegem a diferenca: e o fato de que um
gatilho NAO e uma autorizacao para rodar qualquer coisa.
"""
import pytest

from sentury import policies
from sentury.harness import hooks


def _com_hooks(tmp_path, monkeypatch, corpo):
    (tmp_path / "hooks.yaml").write_text(corpo, encoding="utf-8")
    monkeypatch.setenv("SENTURY_POLICIES_DIR", str(tmp_path))
    policies.limpar_cache()


@pytest.fixture(autouse=True)
def _limpa():
    yield
    policies.limpar_cache()


def test_hook_desligado_nao_dispara(tmp_path, monkeypatch):
    """Gatilho que roda comando sem ninguem ter pedido e uma superficie de
    execucao aberta por padrao: o contrario de uma protecao."""
    _com_hooks(tmp_path, monkeypatch,
               "versao: 1\nhooks:\n  - nome: t\n    quando: arquivo_alterado\n"
               "    padrao: '*.py'\n    comando: git status\n    ativo: false\n")
    assert hooks.aplicaveis("arquivo_alterado", alvo="a.py") == []


def test_padrao_casa_caminho_inteiro_e_nome(tmp_path, monkeypatch):
    """`*.py` tem que pegar `sentury/tools/shell.py`, que fnmatch sozinho nao
    casaria: e nao pode pegar um `.md` so por estar na mesma pasta."""
    _com_hooks(tmp_path, monkeypatch,
               "versao: 1\nhooks:\n  - nome: t\n    quando: arquivo_alterado\n"
               "    padrao: '*.py'\n    comando: git status\n    ativo: true\n")
    assert hooks.aplicaveis("arquivo_alterado", alvo="sentury/tools/shell.py")
    assert hooks.aplicaveis("arquivo_alterado", alvo="a.py")
    assert not hooks.aplicaveis("arquivo_alterado", alvo="sentury/tools/leia.md")


def test_hook_filtra_por_ferramenta(tmp_path, monkeypatch):
    _com_hooks(tmp_path, monkeypatch,
               "versao: 1\nhooks:\n  - nome: t\n    quando: ferramenta_concluida\n"
               "    ferramenta: executar_python\n    comando: git status\n    ativo: true\n")
    assert hooks.aplicaveis("ferramenta_concluida", ferramenta="executar_python")
    assert not hooks.aplicaveis("ferramenta_concluida", ferramenta="analyze_nps")


def test_evento_desconhecido_e_ignorado(tmp_path, monkeypatch):
    """Errar o nome do evento nao pode virar um hook que dispara em tudo."""
    _com_hooks(tmp_path, monkeypatch,
               "versao: 1\nhooks:\n  - nome: t\n    quando: quando_der_vontade\n"
               "    comando: git status\n    ativo: true\n")
    assert hooks.declarados() == []


def test_hook_roda_e_devolve_o_que_viu(tmp_path, monkeypatch):
    _com_hooks(tmp_path, monkeypatch,
               "versao: 1\nhooks:\n  - nome: estado\n    quando: arquivo_alterado\n"
               "    padrao: '*.py'\n    comando: git status --porcelain\n"
               "    descricao: ve o que mudou\n    ativo: true\n")
    observado = hooks.disparar("arquivo_alterado", alvo="x.py", session_id="sess-hook")
    assert len(observado) == 1 and observado[0]["hook"] == "estado"

    aviso = hooks.como_mensagem(observado)
    assert "GATILHO AUTOMÁTICO" in aviso
    # A mensagem diz que foi o ambiente que respondeu, nao que o usuario pediu.
    assert "não porque alguém pediu agora" in aviso


def test_hook_nao_e_autorizacao_para_rodar_qualquer_coisa(tmp_path, monkeypatch):
    """Declarar um hook diz QUANDO um comando roda, nao da o direito de
    roda-lo: ele passa pela mesma politica de permissao."""
    from sentury.tools import permissoes

    _com_hooks(tmp_path, monkeypatch,
               "versao: 1\nhooks:\n  - nome: perigoso\n    quando: arquivo_alterado\n"
               "    padrao: '*'\n    comando: rm -rf build\n    ativo: true\n")
    sessao = "sess-hook-perm"
    permissoes.limpar_sessao(sessao)
    permissoes.esquecer("rm")
    try:
        observado = hooks.disparar("arquivo_alterado", alvo="x.py", session_id=sessao)
        assert observado[0]["precisa_permissao"] is True
        assert observado[0]["ok"] is False
        # E o agente le isso como "nao rodou", nao como "passou".
        assert "precisa da autorização" in hooks.como_mensagem(observado)
    finally:
        permissoes.esquecer("rm")
        permissoes.limpar_sessao(sessao)


def test_sem_arquivo_de_hooks_nenhum_dispara(tmp_path, monkeypatch):
    """Nenhum hook e o estado seguro: uma instalacao sem o arquivo nao pode
    ganhar gatilhos por acidente."""
    monkeypatch.setenv("SENTURY_POLICIES_DIR", str(tmp_path))
    policies.limpar_cache()
    assert hooks.declarados() == []
    assert hooks.disparar("arquivo_alterado", alvo="x.py") == []


def test_orquestrador_dispara_pelos_arquivos_que_a_ferramenta_reportou():
    """Quem nao reporta arquivo nao dispara hook de arquivo: melhor um gatilho
    que nao roda do que um que roda sobre uma suposicao."""
    assert hooks.arquivos_tocados("executar_python", {"arquivos_gerados": ["grafico.png", "dados.csv"]}) == [
        "grafico.png", "dados.csv"]
    assert hooks.arquivos_tocados("executar_comando", {"saida": "mexi em tudo"}) == []
    assert hooks.arquivos_tocados("executar_python", "texto solto") == []


def test_edicao_de_arquivo_dispara_pelo_caminho():
    """Escrever e editar devolvem o arquivo em `caminho`. Sem contar esse campo,
    o hook de rodar os testes depois de editar um .py nunca disparava."""
    assert hooks.arquivos_tocados("editar_arquivo", {"ok": True, "caminho": "app/rota.py"}) == ["app/rota.py"]
    assert hooks.arquivos_tocados("escrever_arquivo", {"ok": True, "caminho": "novo.py"}) == ["novo.py"]


def test_leitura_e_falha_nao_disparam_hook_de_arquivo():
    """Ler um arquivo também devolve `caminho`, e uma escrita recusada não
    mudou nada: nenhum dos dois é arquivo alterado."""
    assert hooks.arquivos_tocados("ler_arquivo", {"ok": True, "caminho": "app/rota.py"}) == []
    assert hooks.arquivos_tocados("editar_arquivo", {"ok": False, "recusado": True, "caminho": "app/rota.py"}) == []


def test_depois_da_ferramenta_poe_o_resultado_no_historico(monkeypatch):
    """Uma edição dispara o hook do arquivo e o que ele viu entra no histórico
    do turno como observação."""
    disparados = []

    def falso(evento, *, alvo="", ferramenta="", session_id="", habilitado=True):
        disparados.append((evento, alvo))
        if evento == "arquivo_alterado":
            return [{"hook": "testes", "comando": "pytest", "ok": False, "erro": "2 failed"}]
        return []

    monkeypatch.setattr(hooks, "disparar", falso)

    class Estado:
        session_id = "s"
        history = []

    estado = Estado()
    hooks.depois_da_ferramenta(estado, "editar_arquivo", {"ok": True, "caminho": "app/rota.py"})
    assert ("arquivo_alterado", "app/rota.py") in disparados
    assert "2 failed" in estado.history[-1]["content"]
