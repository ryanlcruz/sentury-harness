"""`python -m sentury.doctor`: o que falta antes de comecar, e como resolver."""
import json

from sentury import doctor
from sentury.doctor import AVISO, FALTA, OK, Checagem


def test_toda_checagem_que_nao_e_ok_diz_o_que_fazer():
    for c in doctor.diagnosticar():
        assert c.estado in (OK, AVISO, FALTA), c
        if c.estado != OK:
            assert c.como_resolver or "falhou" in c.detalhe, c


def test_falta_sai_com_codigo_1_e_aviso_nao(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "CHECAGENS", [lambda: Checagem("x", AVISO, "so aviso", "faca y")])
    assert doctor.main([]) == 0
    monkeypatch.setattr(doctor, "CHECAGENS", [lambda: Checagem("x", FALTA, "quebrado", "faca y")])
    assert doctor.main([]) == 1
    assert "FALTA" in capsys.readouterr().out


def test_checagem_quebrada_nao_esconde_as_outras(monkeypatch):
    def explode():
        raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "CHECAGENS", [explode, lambda: Checagem("y", OK, "bem")])
    resultado = doctor.diagnosticar()
    assert [c.estado for c in resultado] == [AVISO, OK]


def test_json(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "CHECAGENS", [lambda: Checagem("x", OK, "bem")])
    doctor.main(["--json"])
    assert json.loads(capsys.readouterr().out) == [
        {"nome": "x", "estado": "ok", "detalhe": "bem", "como_resolver": ""}]


def test_pacote_do_playwright_sem_chromium_e_falta(monkeypatch):
    """Era o buraco: o pacote importava, `is_available()` dizia que sim, e a
    falha so aparecia na primeira acao do navegador."""
    import importlib

    from sentury.tools import browser_playwright_provider as provedor

    real = importlib.import_module
    monkeypatch.setattr(doctor.importlib, "import_module",
                        lambda nome, *a: object() if nome == "playwright" else real(nome, *a))
    from sentury.tools import navegador_local

    monkeypatch.setattr(navegador_local, "precisa_do_chromium", lambda: True)
    monkeypatch.setattr(provedor, "chromium_baixado", lambda: False)
    assert doctor._navegador().estado == FALTA

    monkeypatch.setattr(provedor, "chromium_baixado", lambda: True)
    assert doctor._navegador().estado == OK


def test_sem_chromium_o_provedor_nao_se_oferece(monkeypatch):
    from sentury.tools import browser_playwright_provider as provedor

    from sentury.tools import navegador_local

    monkeypatch.setattr(navegador_local, "precisa_do_chromium", lambda: True)
    monkeypatch.setattr(provedor, "chromium_baixado", lambda: False)
    assert provedor.PlaywrightBrowserProvider().is_available() is False


def test_com_chrome_instalado_o_chromium_e_dispensavel(monkeypatch):
    """O Chrome ou o Edge da máquina abrem pelo Playwright: sem Chromium baixado
    o navegador continua pronto, e o instalador não precisa baixá-lo."""
    import importlib

    from sentury.tools import browser_playwright_provider as provedor
    from sentury.tools import navegador_local

    real = importlib.import_module
    monkeypatch.setattr(doctor.importlib, "import_module",
                        lambda nome, *a: object() if nome == "playwright" else real(nome, *a))
    monkeypatch.setattr(navegador_local, "precisa_do_chromium", lambda: False)
    monkeypatch.setattr(provedor, "chromium_baixado", lambda: False)
    # O pacote pode faltar na máquina dos testes; o que se mede é a regra do Chrome.
    import sys
    import types

    pacote, assincrono = types.ModuleType("playwright"), types.ModuleType("playwright.async_api")
    assincrono.async_playwright = object()
    monkeypatch.setitem(sys.modules, "playwright", pacote)
    monkeypatch.setitem(sys.modules, "playwright.async_api", assincrono)
    assert doctor._navegador().estado == OK
    assert provedor.PlaywrightBrowserProvider().is_available() is True


def test_sem_provedor_com_chave_e_falta(monkeypatch):
    import robinbandit

    monkeypatch.setattr(robinbandit, "describe_from_config",
                        lambda *a, **k: [{"key": "groq", "configured": False},
                                         {"key": "fallback", "configured": True}])
    assert doctor._provedores().estado == FALTA
