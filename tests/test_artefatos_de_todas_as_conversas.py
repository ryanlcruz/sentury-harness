"""A biblioteca de artefatos nao pode ser um cache da conversa aberta."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def cliente(monkeypatch):
    import sentury.main as main

    class IndiceFalso:
        async def list(self, user_id):
            return [
                {"session_id": "s1", "title": "Analise de terca"},
                {"session_id": "s2", "title": "Analise de quarta"},
                {"session_id": "s3", "title": "Sem artefato"},
            ]

        async def load(self, user_id, session_id):
            if session_id == "s1":
                return {"artifacts": {
                    "a1": {"attachment": {"titulo": "vendas.csv", "tipo": "table"}, "created_at": 10},
                }}
            if session_id == "s2":
                return {"artifacts": {
                    "a2": {"attachment": {"nome": "grafico.png", "tipo": "chart"}, "created_at": 20},
                }}
            return {"artifacts": {}}

    monkeypatch.setattr(main, "session_index", IndiceFalso())
    monkeypatch.setattr(main, "verify_api_token", lambda: None)
    main.app.dependency_overrides[main.verify_api_token] = lambda: None
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_reune_artefatos_de_conversas_diferentes(cliente):
    corpo = cliente.get("/sentury/artefatos?user_id=eu").json()
    assert corpo["total"] == 2
    # Mais novo primeiro: a biblioteca e consultada de tras para frente.
    assert [a["id"] for a in corpo["artefatos"]] == ["a2", "a1"]
    assert corpo["artefatos"][0]["session_title"] == "Analise de quarta"
    assert corpo["artefatos"][1]["titulo"] == "vendas.csv"


def test_nao_devolve_o_corpo_do_anexo(cliente):
    """O corpo sai pelo endpoint do artefato. Cem base64 para desenhar uma
    grade de cartoes era a razao de a aba nunca ter sido servidor."""
    artefato = cliente.get("/sentury/artefatos?user_id=eu").json()["artefatos"][0]
    assert set(artefato) == {"id", "session_id", "session_title", "titulo", "tipo", "criado_em"}
