"""O que funcionou em cada site volta como dica, sem decidir pelo agente."""
import pytest

from sentury.memory import estrategia


@pytest.fixture(autouse=True)
def casa_isolada(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))


def _lida(texto):
    return {"ok": True, "url": "https://www.vagas.exemplo.com/lista", "texto": texto}


def test_pagina_quase_vazia_sugere_o_navegador():
    r = estrategia.apos_ler_pagina("https://vagas.exemplo.com/lista", _lida("Menu Entrar"))
    assert "browser" in r["dica"]
    assert estrategia.do_site("https://vagas.exemplo.com")["ler_pagina"]["falhou"] == 1


def test_na_proxima_pagina_do_site_a_dica_vem_mesmo_com_texto_razoavel():
    url = "https://vagas.exemplo.com/lista"
    estrategia.apos_ler_pagina(url, _lida("Menu"))
    estrategia.registrar(url, estrategia.BROWSER, True)
    # outra pagina do mesmo site, www incluso: a origem e a mesma
    r = estrategia.apos_ler_pagina("https://www.vagas.exemplo.com/vaga/42", _lida("x" * 300))
    assert "prefira `browser`" in r["dica"]


def test_site_que_barrou_o_navegador_vira_aviso():
    url = "https://portal.exemplo.com/vagas"
    barrado = {"executado": True, "observation": {"metadados": {"url": url, "bloqueio": "access_denied"}}}
    estrategia.apos_browser({}, dict(barrado))
    r = estrategia.apos_browser({}, dict(barrado))
    assert "access_denied" in r["dica"] and "outra fonte" in r["dica"]


def test_leitura_boa_nao_ganha_dica():
    r = estrategia.apos_ler_pagina("https://docs.exemplo.com/a", _lida("conteudo " * 60))
    assert "dica" not in r


def test_falha_de_rede_nao_conta_como_degrau_ruim():
    r = estrategia.apos_ler_pagina("https://x.exemplo.com", {"ok": False, "motivo": "timeout"})
    assert r == {"ok": False, "motivo": "timeout"}
    assert estrategia.do_site("https://x.exemplo.com") == {}
