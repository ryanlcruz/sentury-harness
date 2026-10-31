import json
from types import SimpleNamespace

import pytest

from sentury.harness.policy import READ_TOOLS, sentury_harness
from sentury.harness.state import AnalysisState
from sentury.tools import ambiente
from sentury.tools.catalog import execute_tool
from sentury.tools.registry import TOOL_REGISTRY


def test_esquema_fechado_e_politica_de_leitura():
    meta = TOOL_REGISTRY["inspecionar_ambiente"]
    assert meta["efeito"] == "leitura" and meta["replay_leitura"]
    assert meta["parametros"]["additionalProperties"] is False
    assert "inspecionar_ambiente" in READ_TOOLS
    decisao = sentury_harness.evaluate(AnalysisState("s", "u"), "inspecionar_ambiente", "confira o ambiente", {"alvo": "sistema"})
    assert decisao.allowed


@pytest.mark.parametrize("args", [{"alvo": "shell"}, {"alvo": "processos", "comando": "apagar"}])
def test_comando_livre_nao_chega_ao_sistema(args, monkeypatch):
    monkeypatch.setattr(ambiente.subprocess, "run", lambda *a, **k: pytest.fail("executou"))
    assert ambiente.inspecionar(**args)["ok"] is False


def test_windows_usa_consulta_fixa_e_ignora_argumentos_externos(monkeypatch):
    vistas = []
    monkeypatch.setattr(ambiente.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ambiente.shutil, "which", lambda nome: "powershell.exe")

    def rodar(argv, **kwargs):
        vistas.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps([{"ProcessName": "app", "Id": 12,
                "CPU": 3.5, "WorkingSet64": 4096, "Responding": True, "MainWindowTitle": "Editor"}]))

    monkeypatch.setattr(ambiente.subprocess, "run", rodar)
    r = ambiente.inspecionar("processos")
    assert r["dados"][0] == {"nome": "app", "pid": 12, "cpu_segundos": 3.5,
                              "memoria_bytes": 4096, "respondendo": True, "titulo_janela": "Editor"}
    assert "Get-Process" in vistas[0][0][-1]
    assert "shell" not in vistas[0][1]


def test_recurso_ausente_nao_vira_erro(monkeypatch):
    monkeypatch.setattr(ambiente.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ambiente.shutil, "which", lambda nome: None)
    assert ambiente.inspecionar("janelas") == {"ok": True, "alvo": "janelas", "dados": "indisponível aqui",
                                               "limite": 500, "cpu_unidade": "segundos acumulados"}


def test_linux_le_processos_sem_shell(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    pasta = proc / "123"
    pasta.mkdir(parents=True)
    campos = ["S"] + ["0"] * 23
    campos[11], campos[12], campos[21] = "100", "50", "2"
    (pasta / "stat").write_text("123 (app com espaço) " + " ".join(campos), encoding="utf-8")
    monkeypatch.setattr(ambiente, "_PROC", proc)
    monkeypatch.setattr(ambiente.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ambiente.os, "sysconf", lambda chave: 100 if chave == "SC_CLK_TCK" else 4096, raising=False)
    monkeypatch.setattr(ambiente.subprocess, "run", lambda *a, **k: pytest.fail("abriu shell"))
    dados = ambiente.inspecionar("processos")["dados"]
    assert dados[0]["cpu_segundos"] == 1.5
    assert dados[0]["memoria_bytes"] == 8192
    assert dados[0]["titulo_janela"] == "indisponível aqui"


def test_portas_linux_so_devolve_escuta_local(tmp_path, monkeypatch):
    net = tmp_path / "net"
    net.mkdir()
    (net / "tcp").write_text("header\n0: 0100007F:1F40 00000000:0000 0A\n1: 0100007F:1234 0100007F:0050 01\n", encoding="ascii")
    (net / "tcp6").write_text("header\n0: 00000000000000000000000001000000:0050 00000000000000000000000000000000:0000 0A\n", encoding="ascii")
    monkeypatch.setattr(ambiente, "_PROC", tmp_path)
    assert ambiente._portas_linux() == [{"endereco": "127.0.0.1", "porta": 8000, "protocolo": "tcp"},
                                        {"endereco": "::1", "porta": 80, "protocolo": "tcp"}]


def test_disco_e_sistema_so_leem(monkeypatch):
    monkeypatch.setattr(ambiente.shutil, "disk_usage", lambda raiz: SimpleNamespace(total=100, used=40, free=60))
    assert ambiente.inspecionar("disco")["dados"]["livre_bytes"] == 60
    assert "onde_roda" in ambiente.inspecionar("sistema")["dados"]


async def test_catalogo_despacha_a_ferramenta(monkeypatch):
    monkeypatch.setattr(ambiente, "inspecionar", lambda **args: {"ok": True, "alvo": args["alvo"]})
    r = await execute_tool(None, AnalysisState("s", "u"), "inspecionar_ambiente", {"alvo": "disco"})
    assert r == {"ok": True, "alvo": "disco"}
