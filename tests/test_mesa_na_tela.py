import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentury.residentes import mesa, registro, worker
from sentury.residentes.api_local import router


@pytest.fixture
def tela(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.setenv("SENTURY_HQ_URL", "")
    worker.configurar(None)
    mesa.configurar(None)
    for nome in ("atlas", "forge"):
        registro.criar({"nome": nome, "papel": "teste", "objetivo": "conferir", "ferramentas": ["ler_arquivo"]})
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def test_assunto_falas_destinatario_e_resumo(tela):
    resposta = tela.post("/sentury/residentes/_mesa", json={"titulo": "Decidir", "texto": "@atlas @forge"})
    assert resposta.status_code == 201
    assunto = resposta.json()
    assert assunto["participantes"] == ["atlas", "forge"]
    mesa.falar(assunto["id"], "atlas", "@forge confira a pasta")
    mesa.passar(assunto["id"], "forge")
    lido = tela.get(f"/sentury/residentes/_mesa/{assunto['id']}").json()
    assert lido["falas"][0]["para"] == "forge"
    eventos = tela.get("/sentury/residentes/_eventos").json()["eventos"]
    assert {"mesa_aberta", "mesa_fala", "mesa_passou"} <= {e["tipo"] for e in eventos}
    fechado = tela.post(f"/sentury/residentes/_mesa/{assunto['id']}/fechar", json={"resumo": "Forge confere."})
    assert fechado.status_code == 200
    assert fechado.json()["estado"] == "fechado"
    assert fechado.json()["resumo"] == "Forge confere."
    lista = tela.get("/sentury/residentes/_mesa").json()["assuntos"]
    assert lista[0]["id"] == assunto["id"]


def test_a_pessoa_fala_num_assunto_aberto_pela_tela(tela):
    """A pessoa entra na conversa da Mesa sem virar participante; assunto que não
    existe, ou título vazio, volta recusado com o motivo."""
    assunto = tela.post("/sentury/residentes/_mesa", json={"titulo": "Decidir", "texto": "@atlas"}).json()
    falado = tela.post(f"/sentury/residentes/_mesa/{assunto['id']}/falar", json={"texto": "@forge entra também"})
    assert falado.status_code == 200
    assert falado.json()["falas"][-1]["de"] == "pessoa" and "forge" in falado.json()["participantes"]
    assert "pessoa" not in falado.json()["participantes"]
    recusa = tela.post("/sentury/residentes/_mesa/inexistente/falar", json={"texto": "oi"})
    assert recusa.status_code == 422 and "inexistente" in recusa.json()["detail"]
    assert tela.post("/sentury/residentes/_mesa", json={"titulo": ""}).status_code == 422
