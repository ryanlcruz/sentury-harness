"""Checagem de pacote antes de rodar codigo de terceiro."""
import pytest

from sentury.tools import dependencias as dep


def test_reconhece_o_comando_mesmo_com_extensao_do_windows():
    """No Windows o npx e `npx.cmd`: sem tirar a extensao, a checagem nao
    rodaria justamente onde o comando tem outro nome."""
    assert dep.ecossistema_de("npx.cmd") == "npm"
    assert dep.ecossistema_de("C:/Program Files/nodejs/npx.cmd") == "npm"
    assert dep.ecossistema_de("uvx") == "PyPI"
    # Comando que nao baixa pacote nao tem o que checar.
    assert dep.ecossistema_de("python") == ""


def test_extrai_o_pacote_ignorando_flags_e_versao():
    assert dep.pacote_de(["-y", "algum-pacote", "/tmp"]) == "algum-pacote"
    assert dep.pacote_de(["-y", "pacote@1.2.3"]) == "pacote"
    # Escopo fica, versao sai.
    assert dep.pacote_de(["@escopo/pacote@2.0"]) == "@escopo/pacote"
    assert dep.pacote_de(["-y"]) == ""


async def test_malware_bloqueia_e_cve_apenas_avisa(monkeypatch):
    """Pacote publicado para roubar credencial nao tem versao segura. CVE e
    comum em dependencia viva: bloquear tudo faria desligarem a checagem."""
    async def _osv(pacote, ecossistema, versao=""):
        if pacote == "ruim":
            return {"ok": True, "consultado": True,
                    "malware": [{"id": "MAL-2024-0001", "resumo": "rouba token"}],
                    "vulnerabilidades": []}
        return {"ok": True, "consultado": True, "malware": [],
                "vulnerabilidades": [{"id": "GHSA-abc", "resumo": "algo antigo"}]}

    monkeypatch.setattr(dep, "consultar", _osv)

    barrado = await dep.verificar("ruim", "npm")
    assert not barrado["permitido"] and "MAL-2024-0001" in barrado["motivo"]

    passou = await dep.verificar("comum", "npm")
    assert passou["permitido"] and "GHSA-abc" in passou["aviso"]


async def test_rede_fora_libera_com_registro(monkeypatch):
    """Checagem que derruba o agente quando a internet cai protege menos do que
    atrapalha."""
    async def _explode(*a, **k):
        raise OSError("sem rede")

    class _Cliente:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        post = staticmethod(_explode)

    monkeypatch.setattr("httpx.AsyncClient", lambda **k: _Cliente())
    saida = await dep.consultar("qualquer", "npm")
    assert saida["ok"] and not saida["consultado"] and "indisponivel" in saida["motivo"]


async def test_comando_local_passa_sem_consultar():
    saida = await dep.verificar_comando("python", ["script.py"])
    assert saida["permitido"] and not saida["consultado"]


async def test_mcp_recusa_pacote_com_malware(monkeypatch):
    """A declaracao do servidor vem do usuario; o conteudo do pacote nao."""
    from sentury.external import mcp_registry

    async def _veredito(comando, args=None):
        return {"permitido": False, "motivo": "'x' tem alerta de malware no OSV (MAL-1)"}

    monkeypatch.setattr("sentury.tools.dependencias.verificar_comando", _veredito)
    resultado = await mcp_registry.inspecionar(
        {"transporte": "stdio", "comando": "npx", "args": ["-y", "x"]}, timeout=5)
    assert not resultado["conectado"] and "malware" in resultado["erro"]
