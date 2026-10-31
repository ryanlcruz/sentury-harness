"""Isola o estado da máquina e registra o setor mínimo da bancada."""
import os
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("SENTURY_SESSION_BACKEND", "memory")

# Cada processo paralelo precisa de uma casa própria para não disputar arquivos.
_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _worker:
    os.environ["SENTURY_HOME"] = tempfile.mkdtemp(prefix=f"sentury-testes-{_worker}-")
else:
    os.environ.setdefault("SENTURY_HOME", tempfile.mkdtemp(prefix="sentury-testes-"))
# A entrega de arquivo vai para os Documentos da pessoa: nos testes, para uma pasta descartável.
os.environ["SENTURY_ARTEFATOS_DIR"] = tempfile.mkdtemp(prefix="sentury-entregas-")

from sentury.domains import carregador, registry, setores
from sentury.domains.escopo import usar_setor
from sentury.tools.registry import TOOL_REGISTRY, _carregar
from tests.fixtures.setor_teste.dados import StoreTeste


def _proteger_relatorio(report):
    from sentury.exec.segredos import redigir_segredos

    if report.failed and report.longrepr:
        report.longrepr = redigir_segredos(str(report.longrepr))
    elif isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        arquivo, linha, motivo = report.longrepr
        report.longrepr = (arquivo, linha, redigir_segredos(motivo))
    report.sections = [(nome, redigir_segredos(texto)) for nome, texto in report.sections]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    resultado = yield
    _proteger_relatorio(resultado.get_result())


def pytest_collectreport(report):
    _proteger_relatorio(report)

_fixtures = Path(__file__).parent / "fixtures"
setores.__path__.append(str(_fixtures))
_pacote = carregador.ler(_fixtures / "setor_teste")
assert _pacote is not None
_base = StoreTeste()
_grupos = [r[0] for r in _base.get_sqlite_conn().execute(
    "SELECT DISTINCT grupo FROM registros ORDER BY grupo")]
_base.get_sqlite_conn().close()
_pacote = replace(_pacote, dimensoes={"grupo": _grupos})
registry.register_domain(_pacote)
TOOL_REGISTRY.update(_carregar(_fixtures / "setor_teste" / "tools.yaml", "setor_teste"))


@pytest.fixture
def setor_teste(monkeypatch):
    """Seleciona o pacote da bancada sem alterar a escolha da instalação."""
    skills_originais = carregador.skills_do_pacote

    def skills(nome, pasta=None):
        if nome == _pacote.name:
            return _fixtures / nome / "skills"
        return skills_originais(nome, pasta)

    monkeypatch.setattr(carregador, "skills_do_pacote", skills)
    with usar_setor("setor_teste"):
        yield _pacote


@pytest.fixture(autouse=True)
def _casa_do_robinbandit(tmp_path, monkeypatch):
    """Cada teste usa contas e cofre temporários, sem ler segredos da máquina."""
    casa = tmp_path / "robinbandit"
    casa.mkdir()
    monkeypatch.setenv("ROBINBANDIT_HOME", str(casa))
    monkeypatch.setenv("ROBINBANDIT_VAULT_PATH", str(casa / "cofre.json"))
    monkeypatch.setenv("ROBINBANDIT_ACCOUNTS_PATH", str(casa / "contas.json"))
    for herdada in ("SENTURY_VAULT_PATH", "SENTURY_ACCOUNTS_PATH"):
        monkeypatch.delenv(herdada, raising=False)
    from sentury.harness import visao_auxiliar

    # A descrição da tela não pode chamar um modelo real durante a bancada.
    monkeypatch.setattr(visao_auxiliar, "_llm", None)
    from sentury.llm import auxiliar

    def sem_modelo_real(*args, **kwargs):
        raise RuntimeError("modelo auxiliar real desligado na bancada")

    monkeypatch.setattr(auxiliar, "build_route", sem_modelo_real)
    # O auxiliar padrão usa o modelo da própria conversa, sem passar pelo
    # `build_route`: com o `main` carregado, título, rascunho e resumo de página
    # chamariam o provedor de verdade. Sem a cadeia real, eles caem no plano B.
    import sys

    from sentury.tools import web

    monkeypatch.setattr(web, "_auxiliar", None)
    principal = sys.modules.get("sentury.main")
    if principal is not None and getattr(principal, "auxiliar_llm", None) is not None:
        monkeypatch.setattr(principal.auxiliar_llm, "atual", None)
        monkeypatch.setattr(principal.auxiliar_llm, "_montada", None)
    yield


@pytest.fixture(autouse=True)
def _sem_caixa_da_maquina(request, monkeypatch):
    """Só os testes marcados com docker dependem do daemon da máquina."""
    if request.node.get_closest_marker("docker") is None:
        from sentury.residentes import caixa

        monkeypatch.setattr(caixa, "disponivel", lambda: False)
    yield
