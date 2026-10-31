"""A documentação automática da API é um mapa de todas as rotas, sem login:
fechada por padrão, aberta só para quem desenvolve."""
import subprocess


def test_por_padrao_a_documentacao_nao_existe():
    from sentury import main

    assert main.app.docs_url is None and main.app.redoc_url is None and main.app.openapi_url is None


def test_api_e_dev_sobem_com_a_documentacao(monkeypatch):
    import sentury as _pacote  # noqa: F401  (garante o caminho do projeto)
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("sentury_cli", Path(__file__).resolve().parents[1] / "sentury.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    chamadas = []
    monkeypatch.setattr(subprocess, "Popen", lambda comando, **kw: chamadas.append(kw.get("env")) or object())
    cli.subir_api(8000, recarregar=False, docs=True)
    cli.subir_api(8000, recarregar=False)
    assert chamadas[0]["SENTURY_DOCS"] == "true"
    assert chamadas[1] is None
