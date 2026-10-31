import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml

from sentury.residentes import caixa, caixa_exec
from sentury.residentes.escopo import vestido
from sentury.residentes.manifesto import Manifesto
from sentury.residentes.servidor_hq import SomenteHQ


@pytest.fixture
def agente():
    return Manifesto(nome="atlas", papel="Observador", objetivo="Verifique", criado_em=123)


def inspect_seguro(agente):
    _, volume = caixa.nomes(agente)
    return {"Config": {"Image": "sentury-caixa:local", "User": "1000:1000",
                       "Labels": {"sentury.politica": "1", "sentury.residente": agente.nome}},
            "HostConfig": {"ReadonlyRootfs": True, "NetworkMode": "none", "CapDrop": ["ALL"],
                           "SecurityOpt": ["no-new-privileges:true"], "Memory": 512 * 1024**2,
                           "MemorySwap": 512 * 1024**2, "NanoCpus": 10**9, "PidsLimit": 128},
            "Mounts": [{"Type": "volume", "Name": volume, "Destination": "/workspace"}],
            "State": {"Running": True}}


def test_comando_nao_monta_host_nem_segredos(agente):
    comando = caixa.comando_criar(agente, "sentury-caixa:local")
    assert comando[comando.index("--network") + 1] == "none"
    assert comando[comando.index("--user") + 1] == "1000:1000"
    assert "--read-only" in comando and "--privileged" not in comando
    assert "--env" not in comando and "docker.sock" not in " ".join(comando)
    assert "type=volume" in comando[comando.index("--mount") + 1]
    assert caixa.nomes(agente) != caixa.nomes(Manifesto(nome="atlas", papel="a", objetivo="b", criado_em=124))


@pytest.mark.parametrize("volume", ["/var/run/docker.sock", "C:\\Users", "sentury-workspace-x,target=/var/run"])
def test_recusa_montagem_arbitraria(volume):
    with pytest.raises(ValueError):
        caixa.montagem(volume)


def test_reaproveita_caixa_e_recusa_namespaces_do_host(agente, monkeypatch):
    seguro = inspect_seguro(agente)
    chamadas = []
    def docker(argv, **kwargs):
        chamadas.append(argv)
        dados = {"Driver": "local", "Options": None} if argv[1] == "volume" else seguro
        return SimpleNamespace(returncode=0, stdout=json.dumps([dados]))
    monkeypatch.setattr(caixa, "_docker", docker)
    assert caixa.garantir(agente) == caixa.nomes(agente)[0]
    assert not any(c[1] in ("run", "rm") for c in chamadas)
    for campo, valor in [("PidMode", "host"), ("Privileged", True), ("Memory", 0), ("Devices", [{}])]:
        inseguro = copy.deepcopy(seguro)
        inseguro["HostConfig"][campo] = valor
        assert not caixa._segura(inseguro, agente, "sentury-caixa:local")
    seguro["Mounts"].append({"Type": "bind", "Source": "/var/run/docker.sock"})
    assert not caixa._segura(seguro, agente, "sentury-caixa:local")


def test_volume_local_com_bind_nao_passa(monkeypatch):
    monkeypatch.setattr(caixa, "_docker", lambda *a, **k: SimpleNamespace(returncode=0,
        stdout=json.dumps([{"Driver": "local", "Options": {"device": "/var/run/docker.sock"}}])))
    with pytest.raises(ValueError):
        caixa._volume_seguro("sentury-workspace-atlas")


def test_recria_somente_container_do_residente(agente, monkeypatch):
    dados = inspect_seguro(agente)
    dados["HostConfig"]["NetworkMode"] = "host"
    chamadas = []
    def docker(argv, **kwargs):
        chamadas.append(argv)
        return SimpleNamespace(returncode=1 if argv[1] == "volume" else 0, stdout=json.dumps([dados]))
    monkeypatch.setattr(caixa, "_docker", docker)
    caixa.garantir(agente)
    assert [c[1] for c in chamadas] == ["volume", "inspect", "rm", "run"]
    dados["Config"]["Labels"]["sentury.residente"] = "outro"
    chamadas.clear()
    with pytest.raises(ValueError):
        caixa.garantir(agente)
    assert not any(c[1] == "rm" for c in chamadas)


def test_arquivos_ficam_no_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(caixa_exec, "RAIZ", workspace)
    assert caixa_exec.executar("escrever", {"caminho": "a.txt", "conteudo": "antes"})["ok"]
    assert caixa_exec.executar("editar", {"caminho": "a.txt", "antes": "antes", "depois": "depois"})["ok"]
    assert caixa_exec.executar("ler", {"caminho": "a.txt"})["conteudo"] == "depois"
    assert caixa_exec.executar("listar", {"caminho": "."})["arquivos"] == [{"caminho": "a.txt", "tipo": "arquivo"}]
    with pytest.raises(ValueError):
        caixa_exec.caminho("../fora")


async def test_catalogo_encaminha_pela_propriedade_do_yaml(agente, monkeypatch):
    from sentury.tools import catalog
    from sentury.harness.state import AnalysisState
    monkeypatch.setattr(caixa, "disponivel", lambda: True)
    monkeypatch.setattr(caixa, "_executar", lambda *a: {"ok": True, "modo": "caixa", "saida": "da caixa"})
    local = AsyncMock(side_effect=AssertionError("não executa na HQ"))
    monkeypatch.setattr(catalog, "_executar_local", local)
    with vestido(agente):
        resultado = await catalog._executar_ferramenta(None, AnalysisState("teste", "pessoa"), "executar_comando", {"comando": "pwd"})
    assert resultado["saida"] == "da caixa"
    local.assert_not_called()


async def test_sem_docker_preserva_local_com_aviso(agente, monkeypatch):
    from sentury.tools import catalog
    monkeypatch.setattr(caixa, "disponivel", lambda: False)
    monkeypatch.setattr(catalog, "_executar_local", AsyncMock(return_value={"ok": True}))
    with vestido(agente):
        resultado = await catalog._executar_ferramenta(None, None, "ler_arquivo", {"caminho": "README.md"})
    assert resultado["modo"] == "local" and "sem isolamento" in resultado["aviso"]


async def test_hq_nao_expoe_interface():
    from fastapi import FastAPI
    app = FastAPI()
    @app.get("/hq/teste")
    def teste():
        return {"ok": True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=SomenteHQ(app)), base_url="http://teste") as client:
        assert (await client.get("/hq/teste")).status_code == 200
        assert (await client.get("/")).status_code == 404
        assert (await client.get("/docs")).status_code == 404


def test_compose_socket_so_na_hq():
    raiz = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((raiz / "docker-compose.yml").read_text())
    assert any("docker.sock" in v for v in compose["services"]["hq"]["volumes"])
    assert "docker.sock" not in json.dumps(compose["services"]["caixa"])
    assert "sentury_home:/var/lib/sentury" in compose["services"]["hq"]["volumes"]


@pytest.mark.skipif(not shutil.which("docker"), reason="Docker não está instalado")
def test_imagem_da_caixa_disponivel():
    import subprocess
    resultado = subprocess.run(["docker", "image", "inspect", "sentury-caixa:local"], capture_output=True)
    if resultado.returncode:
        pytest.skip("A imagem local precisa ser construída para o teste de integração")
    assert resultado.returncode == 0


def test_hq_com_caixa_obrigatoria_nao_cai_no_modo_local(monkeypatch):
    import asyncio

    from sentury.residentes import caixa, escopo
    from sentury.residentes import manifesto as _m

    agente = _m.validar({"nome": "atlas", "papel": "infra", "objetivo": "vigiar", "ferramentas": ["executar_comando"]})
    monkeypatch.setattr(caixa, "disponivel", lambda: False)
    monkeypatch.setenv("SENTURY_CAIXA_OBRIGATORIA", "true")
    with escopo.vestido(agente):
        resultado, aviso = asyncio.run(caixa.tentar("comando", {"comando": "id"}))
    assert resultado is not None and resultado["ok"] is False and "nada roda fora dela" in resultado["erro"]
    monkeypatch.delenv("SENTURY_CAIXA_OBRIGATORIA")
    with escopo.vestido(agente):
        resultado, aviso = asyncio.run(caixa.tentar("comando", {"comando": "id"}))
    assert resultado is None and "modo local" in aviso
