import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sentury.harness.state import AnalysisState
from sentury.artifacts.imagens_recebidas import guardar


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1sAAAAASUVORK5CYII="
IMAGEM = {"nome": "tela.png", "data_url": "data:image/png;base64," + PNG}


def test_preserva_a_imagem_sem_base64_no_historico():
    from sentury.main import _anexar_imagens

    state = AnalysisState.new("s1", "eu")
    state.history.append({"role": "user", "content": "Veja esta tela"})
    _anexar_imagens(state, SimpleNamespace(imagens=[SimpleNamespace(**IMAGEM)], funcoes=[]))
    assert state.imagens_do_turno == [IMAGEM]
    registro = next(iter(state.artifacts.values()))["attachment"]
    assert registro["title"] == "tela.png" and registro["type"] == "png"
    assert registro["content_base64"] == PNG
    assert PNG not in json.dumps(state.history)
    assert not state.to_dict().get("artifacts")
    restaurado = AnalysisState.from_dict(state.to_persisted_dict())
    assert restaurado.artifacts == state.artifacts


def test_nova_tentativa_nao_duplica_mas_outro_conteudo_cria_artefato():
    state = AnalysisState.new("s1", "eu")
    guardar(state, [IMAGEM])
    ids = list(state.artifacts)
    guardar(state, [IMAGEM])
    assert list(state.artifacts) == ids
    guardar(state, [{**IMAGEM, "data_url": "data:image/png;base64," + base64.b64encode(b"outro").decode()}])
    assert len(state.artifacts) == 2


@pytest.mark.parametrize("url", ["data:image/png;base64,@@@", "data:image/png;base64,", "https://site/imagem",
                               "data:text/html;base64,YWJj"])
def test_payload_invalido_nao_vira_artefato(url):
    state = AnalysisState.new("s1", "eu")
    guardar(state, [{"nome": "imagem", "data_url": url}])
    assert not state.artifacts


def test_nome_nao_preserva_caminho_da_pessoa():
    state = AnalysisState.new("s1", "eu")
    guardar(state, [{**IMAGEM, "nome": "C:/pessoal/tela.png"}])
    assert next(iter(state.artifacts.values()))["attachment"]["filename"] == "tela.png"


def test_persiste_em_disco_lista_so_metadados_e_busca_o_corpo(tmp_path, monkeypatch):
    import sentury.main as main
    from sentury.memory.local_session_store import LocalSessionStore
    from sentury.memory.session_index import SessionIndex

    store = LocalSessionStore(tmp_path)
    indice = SessionIndex(store)
    monkeypatch.setattr(main, "session_store", store)
    monkeypatch.setattr(main, "session_index", indice)
    main.app.dependency_overrides[main.verify_api_token] = lambda: None
    state = AnalysisState.new("s1", "eu")
    state.history.append({"role": "user", "content": "Esta é minha imagem"})
    main._anexar_imagens(state, SimpleNamespace(imagens=[SimpleNamespace(**IMAGEM)], funcoes=[]))
    asyncio.run(main._persist_state(state))
    # Um índice novo lê o arquivo, sem depender do estado do turno em memória.
    monkeypatch.setattr(main, "session_index", SessionIndex(LocalSessionStore(tmp_path)))
    try:
        with TestClient(main.app) as client:
            lista = client.get("/sentury/artefatos?user_id=eu").json()["artefatos"]
            assert len(lista) == 1 and lista[0]["titulo"] == "tela.png" and lista[0]["tipo"] == "png"
            assert set(lista[0]) == {"id", "session_id", "session_title", "titulo", "tipo", "criado_em"}
            assert PNG not in json.dumps(lista)
            url = f"/sentury/sessions/s1/artifacts/{lista[0]['id']}"
            assert client.get(url + "?user_id=eu").json()["attachment"]["content_base64"] == PNG
            assert client.get(url + "?user_id=outro").status_code == 404
    finally:
        main.app.dependency_overrides.clear()


class TestOutrosArquivos:
    """PDF, planilha e texto anexados também entram na biblioteca de artefatos."""

    def test_pdf_vira_artefato_pelo_nome(self):
        from sentury.artifacts.imagens_recebidas import guardar_arquivos

        state = AnalysisState.new("s1", "eu")
        corpo = base64.b64encode(b"%PDF-1.4 conteudo").decode()
        guardar_arquivos(state, [{"nome": r"C:\Users\pessoa\Documentos\contrato.pdf",
                                  "data_url": "data:application/pdf;base64," + corpo}])
        registro = next(iter(state.artifacts.values()))["attachment"]
        assert registro["title"] == "contrato.pdf" and registro["type"] == "pdf"
        assert registro["mime_type"] == "application/pdf"
        assert registro["content_base64"] == corpo and registro["origem"] == "anexo_da_pessoa"

    def test_mime_vazio_e_repeticao_nao_quebram(self):
        from sentury.artifacts.imagens_recebidas import guardar_arquivos

        state = AnalysisState.new("s1", "eu")
        arquivo = {"nome": "notas.csv", "data_url": "data:;base64," + base64.b64encode(b"a,b\n1,2").decode()}
        guardar_arquivos(state, [arquivo])
        guardar_arquivos(state, [arquivo])
        assert len(state.artifacts) == 1
        registro = next(iter(state.artifacts.values()))["attachment"]
        assert registro["type"] == "csv" and registro["mime_type"] == "application/octet-stream"

    @pytest.mark.parametrize("url", ["data:application/pdf;base64,***", "data:application/pdf;base64,", "texto solto"])
    def test_anexo_invalido_nao_vira_artefato(self, url):
        from sentury.artifacts.imagens_recebidas import guardar_arquivos

        state = AnalysisState.new("s1", "eu")
        guardar_arquivos(state, [{"nome": "x.pdf", "data_url": url}])
        assert state.artifacts == {}

    def test_o_envio_do_chat_guarda_o_anexo(self, tmp_path, monkeypatch):
        from sentury.main import _preparar_turno

        monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
        state = AnalysisState.new("s-anexo", "eu")
        corpo = base64.b64encode(b"linha um\nlinha dois").decode()
        arquivo = SimpleNamespace(model_dump=lambda: {"nome": "nota.txt", "data_url": "data:text/plain;base64," + corpo})
        payload = SimpleNamespace(session_id="s-anexo", message="leia isto", imagens=[], funcoes=[], arquivos=[arquivo])
        _preparar_turno(state, payload)
        tipos = [r["attachment"]["type"] for r in state.artifacts.values()]
        assert tipos == ["txt"]
