"""Integracao HTTP headless do RobinBandit incorporado ao Sentury."""

from fastapi.testclient import TestClient

from sentury import main as main_module


def test_resumo_e_endpoints_do_robinbandit_coexistem():
    client = TestClient(main_module.app)

    resumo = client.get("/sentury/robinbandit")
    estado = client.get("/sentury/robinbandit/state")
    modelos = client.get("/sentury/robinbandit/v1/models")
    logos = client.get("/sentury/robinbandit/logos")

    assert resumo.status_code == 200
    assert resumo.json()["backend"] == "robinbandit"
    assert estado.status_code == 200
    assert modelos.status_code == 200
    assert logos.status_code == 200


def test_interface_propria_do_robinbandit_fica_desligada():
    client = TestClient(main_module.app)

    for path in ("painel", "docs", "redoc", "openapi.json"):
        assert client.get(f"/sentury/robinbandit/{path}").status_code == 404


def test_endpoints_embutidos_usam_o_token_do_sentury(monkeypatch):
    monkeypatch.setattr(main_module.settings, "SENTURY_API_TOKEN", "segredo-teste")
    client = TestClient(main_module.app)

    assert client.get("/sentury/robinbandit/state").status_code == 401
    resposta = client.get(
        "/sentury/robinbandit/state",
        headers={"Authorization": "Bearer segredo-teste"},
    )
    assert resposta.status_code == 200


def test_login_embutido_exige_token_e_nao_expoe_credencial(monkeypatch):
    from robinbandit.accounts import login
    monkeypatch.setattr(login, "consultar", lambda *_: {"instalado": True, "configurada": False})
    monkeypatch.setattr(main_module.settings, "SENTURY_API_TOKEN", "segredo-teste")
    client = TestClient(main_module.app)
    caminho = "/sentury/robinbandit/login/chatgpt_codex"
    assert client.get(caminho, headers={"X-RobinBandit-Login": "1"}).status_code == 401
    resposta = client.get(caminho, headers={"Authorization": "Bearer segredo-teste", "X-RobinBandit-Login": "1"})
    assert resposta.status_code == 200
    assert resposta.json()["configurada"] is False
    assert not any(k in resposta.json() for k in ("access_token", "refresh_token", "id_token"))


def test_client_oferece_conexao_sem_colar_token():
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "sentury/client/src/features/runtime/ConectarConta.tsx").read_text(encoding="utf-8")
    assert "Continuar com ChatGPT" in fonte
    assert "Entrar pelo CLI oficial" in fonte
    assert "Cancelar login" in fonte
    assert "localStorage" not in fonte
    assert "setTimeout(conferir, 2000)" in fonte
