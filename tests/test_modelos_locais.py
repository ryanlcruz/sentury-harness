"""Modelos locais: o que está baixado, pôr para rodar e virar o provedor local do roteador."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentury import ajustes_api, modelos_locais as ml


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    pasta = tmp_path / "models"
    (pasta / "dono" / "Modelo-GGUF").mkdir(parents=True)
    (pasta / "dono" / "Modelo-GGUF" / "Modelo-Q4_K_M.gguf").write_bytes(b"x" * 1000)
    (pasta / "dono" / "Modelo-GGUF" / "mmproj-Modelo-BF16.gguf").write_bytes(b"x" * 10)
    monkeypatch.setattr(ml, "pasta_de_modelos", lambda: pasta)
    monkeypatch.setattr(ml, "memoria_da_maquina", lambda: {"total": 16 * 2**30, "livre": 8 * 2**30})
    return pasta


def _api():
    app = FastAPI()
    app.include_router(ajustes_api.router)
    return TestClient(app)


def test_lista_o_baixado_sem_o_projetor_de_imagem():
    """O projetor de visão acompanha o modelo e não roda sozinho: não aparece como opção."""
    assert [m["chave"] for m in ml.baixados()] == ["dono/Modelo-GGUF/Modelo-Q4_K_M.gguf"]
    assert ml.baixados()[0]["cabe"] == "folgado"


def test_cabe_compara_com_a_memoria_da_maquina():
    memoria = {"total": 16 * 2**30, "livre": 0}
    assert ml.cabe(4 * 2**30, memoria) == "folgado"
    assert ml.cabe(10 * 2**30, memoria) == "apertado"
    assert ml.cabe(14 * 2**30, memoria) == "pesado"


def test_rodar_so_aceita_modelo_da_pasta(monkeypatch):
    chamados = []
    monkeypatch.setattr(ml, "carregar", lambda chave: chamados.append(chave) or {"ok": True, "saida": ""})
    monkeypatch.setattr(ml, "servidor", lambda base=ml.ENDERECO_PADRAO: {"ligado": True, "carregados": [], "disponiveis": []})
    cliente = _api()
    assert cliente.post("/sentury/ajustes/modelos-locais/rodar", json={"modelo": "../fora.gguf"}).status_code == 422
    assert cliente.post("/sentury/ajustes/modelos-locais/rodar",
                        json={"modelo": "dono/Modelo-GGUF/Modelo-Q4_K_M.gguf"}).json()["ok"]
    assert chamados == ["dono/Modelo-GGUF/Modelo-Q4_K_M.gguf"]


@pytest.fixture
def escolhas_do_roteador(monkeypatch):
    """O lugar onde o roteador guarda os modelos escolhidos por provedor, em memória."""
    from robinbandit.accounts import account_config

    guardado = {}

    def definir(provedor, modelos, papel="texto"):
        if modelos:
            guardado[provedor] = list(modelos)
        else:
            guardado.pop(provedor, None)
        return list(modelos)

    monkeypatch.setattr(account_config, "definir_modelos_de_provedor", definir)
    monkeypatch.setattr(account_config, "overrides_de_modelos", lambda: dict(guardado))
    return guardado


def test_usar_exige_modelo_carregado_e_vira_o_modelo_do_lmstudio(monkeypatch, escolhas_do_roteador):
    """Escolhido, o modelo vai para o provedor `lmstudio` do roteador, onde a tela de Modelos também grava."""
    monkeypatch.setattr(ml, "servidor", lambda base=ml.ENDERECO_PADRAO: {"ligado": True, "carregados": ["modelo-q4"], "disponiveis": []})
    cliente = _api()
    assert cliente.put("/sentury/ajustes/modelos-locais/usar", json={"modelo": "outro"}).status_code == 422
    assert cliente.put("/sentury/ajustes/modelos-locais/usar",
                       json={"modelo": "modelo-q4", "base_url": "http://10.0.0.2:1234/v1"}).status_code == 422
    estado = cliente.put("/sentury/ajustes/modelos-locais/usar", json={"modelo": "modelo-q4"}).json()
    assert estado["escolhido"]["modelo"] == "modelo-q4" and escolhas_do_roteador == {"lmstudio": ["modelo-q4"]}
    cliente.put("/sentury/ajustes/modelos-locais/usar", json={"modelo": ""})
    assert escolhas_do_roteador == {} and ml.escolhido()["modelo"] == ""


def test_detecta_o_que_esta_instalado_e_rodando_sem_chave(monkeypatch, tmp_path):
    """Provedor local não pede chave: o Sentury olha se o programa existe e se o servidor responde."""
    lms = tmp_path / "lms.exe"
    lms.write_text("")
    monkeypatch.setattr(ml.ajustes, "cardapio", lambda: {"locais": {
        "lmstudio": {"executaveis": [str(lms)], "onde_rodar": "ligue"}, "ollama": {"executaveis": ["nao-existe-aqui"]}}})

    class Resposta:
        status_code = 200

        def json(self):
            return {"data": [{"id": "qwen3.5-9b"}]}

    def falso_get(url, timeout):
        if "1234" in url:
            return Resposta()
        raise ml.httpx.ConnectError("recusado")

    monkeypatch.setattr(ml.httpx, "get", falso_get)
    catalogo = {"lmstudio": {"cost_class": "local", "label": "LM Studio (local)", "base_url": "http://localhost:1234/v1"},
                "ollama": {"cost_class": "local", "label": "Ollama local", "base_url_env": "OLLAMA_BASE_URL"},
                "groq": {"cost_class": "free", "label": "Groq"}}
    achados = {a["provedor"]: a for a in ml.detectar(catalogo, {"lmstudio": ["qwen3.5-9b"]})}
    assert set(achados) == {"lmstudio", "ollama"}
    assert achados["lmstudio"]["instalado"] and achados["lmstudio"]["ligado"]
    assert achados["lmstudio"]["modelos"] == ["qwen3.5-9b"] and achados["lmstudio"]["em_uso"] == ["qwen3.5-9b"]
    assert not achados["ollama"]["instalado"] and not achados["ollama"]["ligado"]


def test_sem_lmstudio_a_resposta_diz_o_motivo(monkeypatch):
    monkeypatch.setattr(ml, "lms", lambda: None)
    assert "não está instalado" in ml.ligar_servidor()["saida"]
    assert not ml.baixar("dono/repo", "a.gguf")["ok"]


def test_baixar_recusa_arquivo_que_nao_e_gguf():
    cliente = _api()
    assert cliente.post("/sentury/ajustes/modelos-locais/baixar",
                        json={"repositorio": "dono/repo", "arquivo": "../../x.exe"}).status_code == 422
    assert cliente.post("/sentury/ajustes/modelos-locais/baixar",
                        json={"repositorio": "dono/../repo", "arquivo": "a.gguf"}).status_code == 422
