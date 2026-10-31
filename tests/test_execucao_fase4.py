"""Sandbox Python fora do processo da API."""
import asyncio
import contextvars
import http.client
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from sentury.exec import python_exec
from sentury.exec import provider_python
from sentury.exec.contrato import CodigoDeErro
from sentury.exec.rpc import ServidorRPC
from sentury.observability import clear_interventions, get_interventions


@pytest.fixture(autouse=True)
async def _pool_limpo():
    await provider_python.encerrar_pool()
    clear_interventions()
    yield
    await provider_python.encerrar_pool()


async def test_calculo_roda_no_filho():
    r = await provider_python.executar_em_filho(None, "resultado = sum(range(10))", timeout=10)
    assert r["resultado"] == 45
    assert r["modo"] == "filho"


async def test_erro_do_codigo_volta_sem_derrubar_o_pai():
    r = await provider_python.executar_em_filho(None, "resultado = 1 / 0", timeout=10)
    assert "ZeroDivisionError" in r["erro"]
    assert r["modo"] == "filho"


async def test_artefato_fica_na_pasta_de_entregas_do_pai(monkeypatch, tmp_path):
    """O arquivo que o filho grava cai na pasta de entregas do pai, nunca nos
    Documentos reais quando o pai está isolado."""
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_ARTEFATOS_DIR", str(tmp_path))
    r = await provider_python.executar_em_filho(
        None,
        "open('do_filho.txt', 'w').write('vim do filho')\nresultado = 'ok'",
        timeout=10,
    )
    assert r["modo"] == "filho"
    assert len(r["arquivos_gerados"]) == 1
    artefato = Path(r["arquivos_gerados"][0])
    assert tmp_path.resolve() in artefato.resolve().parents
    assert artefato.read_text(encoding="utf-8") == "vim do filho"


async def test_timeout_mata_o_processo(monkeypatch):
    criados = []
    popen_real = provider_python.subprocess.Popen

    def _capturar(*args, **kwargs):
        processo = popen_real(*args, **kwargs)
        criados.append(processo)
        return processo

    monkeypatch.setattr(provider_python.subprocess, "Popen", _capturar)
    r = await provider_python.executar_em_filho(
        None, "for _ in range(10 ** 10):\n    resultado = 1", timeout=1,
    )
    assert r["codigo_erro"] == CodigoDeErro.TIMEOUT
    assert r["modo"] == "filho"
    assert criados and criados[-1].poll() is not None


async def test_fallback_e_explicito_e_observavel(monkeypatch):
    async def _sem_filho():
        return None

    monkeypatch.setattr(provider_python, "_obter_trabalhador", _sem_filho)
    assert await provider_python.executar_em_filho(None, "resultado = 2") is None
    assert get_interventions()["by_kind"]["python_child_fallback"] == 1


async def test_queda_para_em_processo_declara_o_modo(monkeypatch):
    async def _falha(*_args, **_kwargs):
        return None

    monkeypatch.setattr(provider_python, "habilitado", lambda: True)
    monkeypatch.setattr(provider_python, "executar_em_filho", _falha)
    r = await python_exec.executar_python(None, "resultado = 6 * 7")
    assert r["resultado"] == 42
    assert r["modo"] == "em_processo"


async def test_pool_anuncia_trabalhador_realmente_quente():
    await provider_python.iniciar_pool(tamanho=1)
    assert provider_python._pool.qsize() == 1
    trabalhador = provider_python._pool.get_nowait()
    try:
        assert trabalhador.processo.poll() is None
        if provider_python.os.name == "nt" and trabalhador.limite is not None:
            assert trabalhador.limite.handle
    finally:
        provider_python._pool.put(trabalhador)


def _post_rpc(servidor, token, ferramenta="eco", argumentos=None):
    url = urlsplit(servidor.url)
    conexao = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
    corpo = json.dumps({"ferramenta": ferramenta, "argumentos": argumentos or []})
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    conexao.request("POST", url.path, body=corpo, headers=headers)
    resposta = conexao.getresponse()
    carga = json.loads(resposta.read().decode("utf-8"))
    conexao.close()
    return resposta.status, carga


def test_rpc_recusa_token_ausente_ou_invalido():
    with ServidorRPC({"eco": lambda valor: valor}) as servidor:
        assert _post_rpc(servidor, None, argumentos=["x"])[0] == 401
        assert _post_rpc(servidor, "errado", argumentos=["x"])[0] == 401
        status, carga = _post_rpc(servidor, servidor.token, argumentos=["x"])
        assert status == 200 and carga["resultado"] == "x"


def test_rpc_reaplica_contexto_do_turno():
    sessao = contextvars.ContextVar("sessao_teste_rpc", default="fora")
    token = sessao.set("sessao-a")
    try:
        servidor = ServidorRPC({"contexto": sessao.get}).iniciar()
    finally:
        sessao.reset(token)
    try:
        status, carga = _post_rpc(servidor, servidor.token, ferramenta="contexto")
        assert status == 200 and carga["resultado"] == "sessao-a"
    finally:
        servidor.fechar()


async def test_gif_search_mantem_api_e_roda_rede_no_pai(monkeypatch):
    chamados = []

    def _gif(consulta):
        chamados.append(consulta)
        return f"https://media.tenor.com/{consulta}/reacao.gif"

    monkeypatch.setattr(provider_python, "_ferramentas_rpc", lambda: {
        "gif_search": _gif,
        "arxiv_search": lambda *_a, **_k: [],
    })
    r = await provider_python.executar_em_filho(
        None, "resultado = gif_search('crise')", timeout=10,
    )
    assert r["resultado"] == "https://media.tenor.com/crise/reacao.gif"
    assert chamados == ["crise"]
    assert r["modo"] == "filho"


async def test_limite_de_memoria_encerra_e_classifica_o_filho(monkeypatch):
    # Pequeno o bastante para o worker quente subir; muito menor que a lista
    # pedida pelo codigo. O Job Object/RLIMIT decide antes de a maquina sofrer.
    monkeypatch.setattr(provider_python, "MEMORIA_MAXIMA_MB", 768)
    r = await provider_python.executar_em_filho(
        None, "resultado = [0] * (200 * 1024 * 1024)", timeout=15,
    )
    assert r["codigo_erro"] == CodigoDeErro.MEMORIA, r
    assert r["modo"] == "filho"
