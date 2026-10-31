"""O navegador que o Sentury abre sozinho: o Chrome instalado primeiro.

O Chromium baixado pelo Playwright não é assinado, e o Windows com Controle
Inteligente de Aplicativos o barra; ele fica só para máquina sem Chrome.
"""
import asyncio

import pytest

from sentury.tools import navegador_local


class _Chromium:
    def __init__(self, sem_chrome=False, erro=None, com_edge=False):
        self.chamadas, self.sem_chrome, self.erro, self.com_edge = [], sem_chrome, erro, com_edge

    def launch(self, **opcoes):
        self.chamadas.append(opcoes)
        if opcoes.get("channel") == "msedge" and self.com_edge:
            return "edge"
        if opcoes.get("channel") and self.sem_chrome:
            raise RuntimeError("Chromium distribution 'chrome' is not found at C:\\chrome.exe")
        if opcoes.get("channel") and self.erro:
            raise RuntimeError(self.erro)
        return "navegador"


class _Playwright:
    def __init__(self, **kw):
        self.chromium = _Chromium(**kw)


def test_abre_o_chrome_instalado(monkeypatch):
    monkeypatch.delenv("SENTURY_NAVEGADOR_CANAL", raising=False)
    p = _Playwright()
    assert navegador_local.abrir(p, headless=True) == "navegador"
    assert p.chromium.chamadas == [{"channel": "chrome", "headless": True}]


def test_sem_chrome_cai_no_chromium(monkeypatch):
    monkeypatch.delenv("SENTURY_NAVEGADOR_CANAL", raising=False)
    p = _Playwright(sem_chrome=True)
    assert navegador_local.abrir(p, headless=True) == "navegador"
    assert p.chromium.chamadas[-1] == {"headless": True}


def test_erro_do_chrome_que_nao_e_ausencia_sobe():
    """Chrome que existe e quebra não vira Chromium escondido: o erro aparece."""
    with pytest.raises(RuntimeError, match="crashed"):
        navegador_local.abrir(_Playwright(erro="Browser crashed"))


def test_canal_escolhido_por_ambiente(monkeypatch):
    monkeypatch.setenv("SENTURY_NAVEGADOR_CANAL", "chromium")
    p = _Playwright()
    navegador_local.abrir(p)
    assert p.chromium.chamadas == [{}]


def test_versao_async_segue_a_mesma_regra(monkeypatch):
    monkeypatch.delenv("SENTURY_NAVEGADOR_CANAL", raising=False)

    class _Async:
        def __init__(self):
            self.chamadas = []

        async def launch(self, **opcoes):
            self.chamadas.append(opcoes)
            if opcoes.get("channel"):
                raise RuntimeError("Executable doesn't exist at /opt/google/chrome/chrome")
            return "navegador"

    p = type("P", (), {"chromium": _Async()})()
    assert asyncio.run(navegador_local.abrir_async(p)) == "navegador"
    assert p.chromium.chamadas == [{"channel": "chrome"}, {"channel": "msedge"}, {}]


def test_sem_chrome_abre_o_edge_antes_do_chromium(monkeypatch):
    """O Edge vem com o Windows e é assinado: entra antes do Chromium baixado."""
    monkeypatch.delenv("SENTURY_NAVEGADOR_CANAL", raising=False)
    p = _Playwright(sem_chrome=True, com_edge=True)
    assert navegador_local.abrir(p) == "edge"
    assert [c.get("channel") for c in p.chromium.chamadas] == ["chrome", "msedge"]


def test_navegador_instalado_pelos_caminhos_padrao(monkeypatch, tmp_path):
    monkeypatch.setattr(navegador_local, "_caminhos", lambda canal: [tmp_path / f"{canal}.exe"])
    assert navegador_local.navegador_instalado() == ""
    assert navegador_local.precisa_do_chromium() is True
    (tmp_path / "msedge.exe").write_bytes(b"")
    assert navegador_local.navegador_instalado() == "msedge"
    monkeypatch.delenv("SENTURY_NAVEGADOR_CANAL", raising=False)
    assert navegador_local.precisa_do_chromium() is False
    monkeypatch.setenv("SENTURY_NAVEGADOR_CANAL", "chromium")
    assert navegador_local.precisa_do_chromium() is True
