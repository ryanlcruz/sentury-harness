import json
import os
import subprocess
import sys
import time

import pytest

from sentury.memory import escritor_unico


def _lock_antigo(pasta):
    caminho = pasta / escritor_unico.ARQUIVO
    caminho.write_text(json.dumps({"pid": os.getpid() + 100000, "desde": 1000,
                                   "host": escritor_unico._HOST}), encoding="utf-8")
    return caminho


def test_pid_reutilizado_nao_prende_o_store(tmp_path, monkeypatch):
    caminho = _lock_antigo(tmp_path)
    monkeypatch.setattr(escritor_unico, "_vivo", lambda pid: True)
    monkeypatch.setattr(escritor_unico, "_inicio_do_processo", lambda pid: 2000)

    trava = escritor_unico.Lock(tmp_path).adquirir()
    assert json.loads(caminho.read_text(encoding="utf-8"))["pid"] == os.getpid()
    trava.liberar()


def test_processo_existente_anterior_ao_lock_continua_protegido(tmp_path, monkeypatch):
    _lock_antigo(tmp_path)
    monkeypatch.setattr(escritor_unico, "_vivo", lambda pid: True)
    monkeypatch.setattr(escritor_unico, "_inicio_do_processo", lambda pid: 900)

    with pytest.raises(escritor_unico.OutroEscritorAtivo):
        escritor_unico.Lock(tmp_path).adquirir()


def test_sem_horario_confiavel_erra_para_proteger(tmp_path, monkeypatch):
    _lock_antigo(tmp_path)
    monkeypatch.setattr(escritor_unico, "_vivo", lambda pid: True)
    monkeypatch.setattr(escritor_unico, "_inicio_do_processo", lambda pid: None)

    with pytest.raises(escritor_unico.OutroEscritorAtivo):
        escritor_unico.Lock(tmp_path).adquirir()


@pytest.mark.skipif(os.name != "nt", reason="API do Windows")
def test_windows_obtem_inicio_real_do_processo():
    # O processo do pytest pode ter minutos de vida quando a suíte chega aqui.
    # Um filho recém-criado dá limites reais sem depender da ordem/duração.
    antes = time.time()
    processo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        inicio = escritor_unico._inicio_do_processo(processo.pid)
        assert inicio is not None
        assert antes <= inicio <= time.time()
    finally:
        processo.terminate()
        processo.wait(timeout=5)
