"""O medidor da escada: quantas leituras foram texto e quantas foram print.

Para provar que "reduzimos screenshot" faltava contar. O tracer era um anel de
100 em memoria: morria com o processo e nao separava texto de print.
"""
import time

import pytest

from sentury.memory import estrategia


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    return tmp_path


def _browser(acao, url="https://vagas.exemplo.com/1", sessao="s1", **extra):
    argumentos = {"acao": acao, "argumentos": {"url": url, **extra}}
    resultado = {"executado": True, "observation": {"metadados": {"url": url}}}
    return estrategia.apos_browser(argumentos, resultado, sessao=sessao)


def test_texto_e_print_contam_separado_por_site():
    estrategia.apos_ler_pagina("https://vagas.exemplo.com/lista", {"ok": True, "texto": "x" * 500}, sessao="s1")
    _browser("navegar")
    _browser("clicar")
    _browser("imagens")
    _browser("snapshot", url="https://outro.com/a", sessao="s2")

    r = estrategia.resumo_da_escada()
    assert (r["texto"], r["print"]) == (4, 1)
    assert r["parcela_print"] == 0.2
    assert r["por_site"]["vagas.exemplo.com"] == {"texto": 3, "print": 1}
    assert r["por_site"]["outro.com"] == {"texto": 1, "print": 0}
    assert r["por_sessao"]["s1"] == {"texto": 3, "print": 1}


def test_roteiro_conta_cada_passo_que_le():
    passos = [{"acao": "navegar"}, {"acao": "clicar"}, {"acao": "esperar"},
              {"acao": "conferir"}, {"acao": "ver"}, {"acao": "pensar"}]
    _browser("roteiro", passos=passos)

    r = estrategia.resumo_da_escada()
    assert (r["texto"], r["print"]) == (2, 1), "esperar, conferir e pensar nao leem a pagina"


def test_acao_que_nao_executou_nao_conta():
    estrategia.apos_browser({"acao": "imagens"}, {"executado": False, "fase": "permissao"})
    estrategia.apos_ler_pagina("https://a.com", {"ok": False, "erro": "timeout"})
    assert estrategia.resumo_da_escada()["leituras"] == 0


def test_sobrevive_ao_processo_e_respeita_a_janela(casa):
    """Durável: esta no disco, nao num anel em memoria."""
    antigo = time.time() - 40 * 86400
    estrategia.anotar_leitura("https://a.com", estrategia.BROWSER, estrategia.PRINT, "s", agora=antigo)
    estrategia.anotar_leitura("https://a.com", estrategia.BROWSER, estrategia.TEXTO, "s")

    assert (casa / "leituras.jsonl").exists()
    assert estrategia.resumo_da_escada(30)["leituras"] == 1
    assert estrategia.resumo_da_escada(60)["leituras"] == 2


def test_sem_leitura_a_parcela_e_nula():
    assert estrategia.resumo_da_escada()["parcela_print"] is None


def test_poda_guarda_so_os_ultimos_90_dias(monkeypatch, casa):
    monkeypatch.setattr(estrategia, "_PODA_ACIMA_DE_BYTES", 300)
    velho = time.time() - 100 * 86400
    for _ in range(5):
        estrategia.anotar_leitura("https://a.com", estrategia.BROWSER, estrategia.PRINT, "s", agora=velho)
    for _ in range(3):
        estrategia.anotar_leitura("https://a.com", estrategia.BROWSER, estrategia.TEXTO, "s")

    linhas = (casa / "leituras.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 3


def test_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    import sentury.main as main

    _browser("imagens")
    main.app.dependency_overrides[main.verify_api_token] = lambda: None
    try:
        corpo = TestClient(main.app).get("/sentury/escada?dias=7").json()
    finally:
        main.app.dependency_overrides.clear()
    assert corpo["print"] == 1 and corpo["dias"] == 7
