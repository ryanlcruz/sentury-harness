"""O rascunho da conversa nao guarda o anexo para sempre.

`rascunho/<sessao>/recebidos` guardava o curriculo anexado sem prazo, e apagar
a conversa deixava o arquivo em disco. Agora: apagar a conversa apaga o
rascunho dela, e anexo recebido tem prazo (`SENTURY_RECEBIDOS_DIAS`).
"""
import base64
import os
import time

import pytest
from fastapi.testclient import TestClient

from sentury.tools import arquivos, recebidos


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    return tmp_path / "casa"


def _anexo(nome="curriculo.txt", texto="Maria, dev python"):
    corpo = base64.b64encode(texto.encode()).decode()
    return {"nome": nome, "data_url": f"data:text/plain;base64,{corpo}"}


def _envelhecer(caminho, dias):
    quando = time.time() - dias * 86400
    os.utime(caminho, (quando, quando))


class TestApagarAConversa:
    def test_leva_o_rascunho_junto(self, casa):
        recebidos.guardar("conversa-1", [_anexo()])
        (arquivos.pasta_de_rascunho("conversa-1") / "script.py").write_text("print(1)")

        assert arquivos.apagar_rascunho("conversa-1") is True
        assert not (casa / "rascunho" / "conversa-1").exists()

    def test_nao_toca_o_rascunho_de_outra(self, casa):
        recebidos.guardar("conversa-1", [_anexo()])
        recebidos.guardar("conversa-2", [_anexo()])

        arquivos.apagar_rascunho("conversa-1")
        assert (casa / "rascunho" / "conversa-2" / "recebidos" / "curriculo.txt").exists()

    @pytest.mark.parametrize("sessao", ["", "..", "../..", "/"])
    def test_id_estranho_nao_apaga_nada_fora(self, casa, sessao):
        recebidos.guardar("conversa-1", [_anexo()])
        arquivos.apagar_rascunho(sessao)
        assert (casa / "rascunho" / "conversa-1" / "recebidos" / "curriculo.txt").exists()
        assert casa.exists()

    def test_pelo_endpoint(self, casa, monkeypatch):
        import sentury.main as main

        class StoreFalso:
            async def delete(self, session_id):
                pass

        class IndiceFalso:
            async def remove(self, user_id, session_id):
                pass

        monkeypatch.setattr(main, "session_store", StoreFalso())
        monkeypatch.setattr(main, "session_index", IndiceFalso())
        main.app.dependency_overrides[main.verify_api_token] = lambda: None
        recebidos.guardar("conversa-9", [_anexo()])
        try:
            with TestClient(main.app) as cliente:
                corpo = cliente.delete("/sentury/sessions/conversa-9?user_id=eu").json()
        finally:
            main.app.dependency_overrides.clear()

        assert corpo["rascunho_apagado"] is True
        assert not (casa / "rascunho" / "conversa-9").exists()


class TestPrazoDoRecebido:
    def test_velho_sai_e_novo_fica(self, casa):
        velho, = recebidos.guardar("conversa-1", [_anexo("velho.txt")])
        novo, = recebidos.guardar("conversa-1", [_anexo("novo.txt", "outro")])
        _envelhecer(velho, 31)

        assert recebidos.podar(dias=30) == 1
        assert not velho.exists() and novo.exists()

    def test_so_recebidos_o_resto_do_rascunho_fica(self, casa):
        """O que o agente entregou mora no rascunho, e conversa antiga aponta para la."""
        entregue = arquivos.pasta_de_rascunho("conversa-1") / "relatorio.xlsx"
        entregue.write_bytes(b"planilha")
        _envelhecer(entregue, 400)

        recebidos.podar(dias=30)
        assert entregue.exists()

    def test_prazo_zero_desliga(self, casa):
        velho, = recebidos.guardar("conversa-1", [_anexo()])
        _envelhecer(velho, 400)
        assert recebidos.podar(dias=0) == 0 and velho.exists()

    def test_roda_uma_vez_por_dia_na_chegada_de_anexo(self, casa):
        velho, = recebidos.guardar("conversa-1", [_anexo("velho.txt")])
        _envelhecer(velho, 31)
        (casa / "rascunho" / ".ultima_poda_de_recebidos").write_text(str(time.time()))

        recebidos.guardar("conversa-2", [_anexo()])
        assert velho.exists(), "podou de novo no mesmo dia"

        amanha = time.time() + 25 * 3600
        assert recebidos.podar_se_preciso(agora=amanha) == 1
        assert not velho.exists()
