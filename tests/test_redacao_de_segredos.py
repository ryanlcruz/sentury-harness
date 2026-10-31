"""As credenciais fictícias não chegam a mensagens, tracebacks ou diagnósticos."""
import io
import json
import logging
import sys
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from pydantic import ValidationError

from sentury.config import Settings
from sentury.exec import segredos
from sentury.exec.logs import FormatoSeguro, instalar_redacao
from sentury.exec.saida import preparar

BOT = "123456789:" + "aZ_" * 12


@pytest.fixture(autouse=True)
def registros_isolados(monkeypatch):
    monkeypatch.setattr(segredos, "_valores", set())


@pytest.mark.parametrize("campo", [
    "OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "GITHUB_MODELS_API_KEY",
    "CEREBRAS_API_KEY", "HUGGINGFACE_API_KEY", "SAMBANOVA_API_KEY", "MISTRAL_API_KEY",
    "COHERE_API_KEY", "DEEPINFRA_API_KEY", "FIREWORKS_API_KEY", "REPLICATE_API_KEY",
    "TELEGRAM_TOKEN", "PROVEDOR_FUTURO_SECRET",
])
def test_qualquer_campo_de_credencial_e_redigido_inclusive_csv(campo):
    tokens = "credencial-ficticia-um,credencial-ficticia-dois"
    for texto in (f"{campo}='{tokens}'", json.dumps({campo: tokens}), f"{campo}={tokens}"):
        seguro = segredos.redigir_segredos(texto)
        assert "credencial-ficticia-um" not in seguro
        assert "credencial-ficticia-dois" not in seguro
        assert campo in seguro


@pytest.mark.parametrize("url", [
    f"https://api.telegram.org/bot{BOT}/sendMessage",
    f"https://api.telegram.org/file/bot{BOT}/document/file.pdf",
    "https://api.telegram.org/bot123:token-ficticio/getMe",
])
def test_url_de_api_telegram_nao_carrega_token_no_diagnostico(url):
    seguro = segredos.redigir_segredos(url)
    assert BOT not in seguro and "token-ficticio" not in seguro
    assert "api.telegram.org" in seguro


def test_bot_solto_e_urlencoded_tambem_sao_redigidos():
    for token in (BOT, quote(BOT, safe="")):
        assert token not in segredos.redigir_segredos("erro: " + token)


def test_autenticacao_basic_e_credenciais_na_url_sao_redigidas():
    for texto in ("Basic dGVzdGU6c2VuaGE=", "postgres://usuario:senha-ficticia@servidor/banco"):
        seguro = segredos.redigir_segredos(texto)
        assert "dGVzdGU6c2VuaGE=" not in seguro
        assert "senha-ficticia" not in seguro


def test_gravacao_de_resultados_nao_guarda_credenciais():
    from sentury.harness import gravacao_do_turno as gravacao

    registros = []
    marca = gravacao.RESULTADOS_DO_TURNO.set(registros)
    try:
        gravacao.anotar_resultado("browser", {"acao": "navegar", "url": "https://api.telegram.org/bot" + BOT + "/getMe"},
                                 {"ok": False, "erro": "token=" + BOT})
        assert BOT not in json.dumps(registros)
    finally:
        gravacao.RESULTADOS_DO_TURNO.reset(marca)


def test_valor_opaco_registrado_nao_depende_de_prefixo_do_provedor():
    token = "opaque-ficticio-8edcd419-78bb-4bce"
    segredos.registrar_configuracao({"PROVEDOR_NOVO_API_KEY": token})
    assert token not in segredos.redigir_segredos("falha com " + token)
    assert token not in segredos.redigir_segredos("url=" + quote(token, safe=""))


def test_configuracao_registra_valores_no_boot_e_na_troca():
    cfg = Settings(_env_file=None, TELEGRAM_TOKEN=BOT)
    assert BOT not in segredos.redigir_segredos("falha " + BOT)
    nova = "credencial-opaca-nova-de-bancada"
    cfg.CEREBRAS_API_KEY = nova
    assert cfg.CEREBRAS_API_KEY == nova
    assert nova not in segredos.redigir_segredos("falha " + nova)


def test_erro_de_validacao_nao_imprime_o_valor_de_entrada():
    with pytest.raises(ValidationError) as capturado:
        Settings(_env_file=None, GROQ_API_KEY={"entrada": "valor-ficticio-sigiloso"})
    assert "valor-ficticio-sigiloso" not in str(capturado.value)
    assert "input_value" not in str(capturado.value)


def test_corte_de_texto_nao_preserva_fragmento_da_chave():
    token = "parte-inicial-sigilosa" + "x" * 200 + "parte-final-sigilosa"
    segredos.registrar_configuracao({"API_KEY": token})
    texto, _ = preparar("prefixo " + token + " fim", 50)
    assert "parte-inicial" not in texto and "parte-final" not in texto


def test_dados_estruturados_preservam_metricas_e_nao_mutam_as_credenciais():
    original = {"headers": {"Authorization": "Bearer " + BOT}, "credentials": {"opaque": "ficticio"},
                "tokens": {"entrada": 12, "saida": 4}, "ok": True}
    seguro = segredos.sanitizar_dados(original)
    assert seguro["headers"]["Authorization"] == segredos.MARCA
    assert seguro["credentials"] == segredos.MARCA
    assert seguro["tokens"] == {"entrada": 12, "saida": 4}
    assert original["headers"]["Authorization"] == "Bearer " + BOT
    assert segredos.redigir_segredos("total_tokens=12") == "total_tokens=12"


def test_formatter_redige_mensagem_argumentos_e_traceback():
    try:
        raise RuntimeError("URL de falha https://api.telegram.org/file/bot" + BOT + "/arquivo")
    except RuntimeError:
        record = logging.LogRecord("httpcore.network", logging.ERROR, __file__, 1,
                                  "falha %s", ("Authorization: Bearer " + BOT,), sys.exc_info())
    saida = FormatoSeguro(logging.Formatter("%(name)s %(message)s")).format(record)
    assert BOT not in saida
    assert "RuntimeError" in saida and "httpcore.network" in saida


def test_logger_criado_depois_da_instalacao_tambem_redige():
    anterior = logging.getLogRecordFactory()
    logger = logging.getLogger("bancada.provedor.futuro")
    handler = logging.StreamHandler(io.StringIO())
    logger.addHandler(handler)
    antes_nivel, antes_propagar = logger.level, logger.propagate
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    try:
        instalar_redacao()
        logger.warning("https://api.telegram.org/bot%s/getMe", BOT)
        assert BOT not in handler.stream.getvalue()
        assert "getMe" in handler.stream.getvalue()
    finally:
        logging.setLogRecordFactory(anterior)
        logger.removeHandler(handler)
        logger.setLevel(antes_nivel)
        logger.propagate = antes_propagar


def test_log_de_acesso_do_uvicorn_continua_formatando():
    """O formatador de acesso do uvicorn desempacota os argumentos do registro;
    zerá-los quebrava cada linha de acesso com "not enough values to unpack"."""
    from uvicorn.logging import AccessFormatter

    from sentury.exec.logs import proteger_registro

    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "GET", "/sentury/residentes", "1.1", 200), None)
    proteger_registro(record)
    saida = FormatoSeguro(AccessFormatter("%(client_addr)s %(request_line)s %(status_code)s",
                                          use_colors=False)).format(record)
    assert "GET /sentury/residentes HTTP/1.1" in saida and "200" in saida


def test_argumento_com_segredo_continua_redigido_no_registro():
    from sentury.exec.logs import proteger_registro

    record = logging.LogRecord("x", logging.INFO, __file__, 1, "chave %s", ("Authorization: Bearer " + BOT,), None)
    proteger_registro(record)
    assert BOT not in record.getMessage()


def test_observabilidade_nao_guarda_valores_sensiveis():
    from sentury.observability import tracer, interventions

    tracer.clear_traces()
    interventions.clear_interventions()
    try:
        tracer.record_turn_trace(session_id="s", user_id="u", user_message="token=" + BOT, reply="fim",
                                 deliberation={"steps": [{"tool": "consulta", "observation": "URL " + BOT}]})
        interventions.record_intervention("erro", {"TELEGRAM_TOKEN": BOT})
        assert BOT not in json.dumps(tracer.get_recent_traces())
        assert BOT not in json.dumps(interventions.get_interventions())
    finally:
        tracer.clear_traces()
        interventions.clear_interventions()


def test_relatorio_do_pytest_redige_falha_e_captura_sem_mudar_skip():
    from tests.conftest import _proteger_relatorio

    report = SimpleNamespace(failed=True, longrepr="erro TELEGRAM_TOKEN=" + BOT,
                             sections=[("Captured stderr", "url=" + BOT)])
    _proteger_relatorio(report)
    assert BOT not in report.longrepr and BOT not in report.sections[0][1]
    skipped = SimpleNamespace(failed=False, longrepr=("teste.py", 2, "ambiente indisponível"), sections=[])
    _proteger_relatorio(skipped)
    assert skipped.longrepr == ("teste.py", 2, "ambiente indisponível")
