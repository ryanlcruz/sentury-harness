"""A escolha de modo no painel vale o turno inteiro, e so muda no seguinte.

Um turno faz varias chamadas ao modelo, e `build_tier_provider` relia a
selecao a cada uma: trocar o Dedicado no painel no meio da execucao mudava o
modelo entre o planner e o responder, em silencio.
"""
import asyncio
import json

import pytest

from robinbandit import account_config


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBINBANDIT_HOME", str(tmp_path / "robin"))
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    account_config.definir_selecao_do_modo("dedicado", [{"conta": "claude_code", "modelos": ["opus"]}])
    yield


def _modelos():
    return [m for alvo in account_config.selecao_do_turno("dedicado") for m in alvo["modelos"]]


def test_a_foto_do_turno_nao_muda_quando_o_painel_muda():
    token = account_config.congelar_selecao_do_turno()
    try:
        account_config.definir_selecao_do_modo("dedicado", [{"conta": "chatgpt_codex", "modelos": ["gpt"]}])
        assert _modelos() == ["opus"]
    finally:
        account_config.soltar_selecao_do_turno(token)
    assert _modelos() == ["gpt"], "fora do turno vale o painel"


async def test_dois_turnos_ao_mesmo_tempo_nao_se_misturam():
    vistos = {}

    async def turno(nome, pausa):
        token = account_config.congelar_selecao_do_turno()
        try:
            await asyncio.sleep(pausa)
            vistos[nome] = _modelos()
        finally:
            account_config.soltar_selecao_do_turno(token)

    primeiro = asyncio.create_task(turno("primeiro", 0.05))
    await asyncio.sleep(0.01)
    account_config.definir_selecao_do_modo("dedicado", [{"conta": "chatgpt_codex", "modelos": ["gpt"]}])
    await asyncio.gather(primeiro, turno("segundo", 0))

    assert vistos == {"primeiro": ["opus"], "segundo": ["gpt"]}


async def test_no_orquestrador_o_turno_inteiro_ve_a_mesma_selecao():
    """A pessoa troca o Dedicado no painel entre a primeira e a segunda chamada
    ao modelo. As chamadas do turno seguem com a selecao de quando ele comecou."""
    from tests.fixtures.setor_teste.dados import StoreTeste
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState

    vistos = []

    class Llm:
        last_model = last_provider = "t"
        last_usage = last_tool_calls = None

        async def complete(self, messages, *a, **k):
            vistos.append(_modelos())
            if len(vistos) == 1:
                account_config.definir_selecao_do_modo(
                    "dedicado", [{"conta": "chatgpt_codex", "modelos": ["gpt"]}])
                # Pede ferramenta: o turno volta ao modelo depois dela.
                return json.dumps({"action": "tool_call", "tool": "listar_arquivos",
                                   "arguments": {"caminho": "."}})
            return json.dumps({"action": "respond", "message": "ok"})

    llm = Llm()
    orq = SenturyOrchestrator(planner=llm, responder=llm,
                              store=StoreTeste())
    await orq.handle_message(AnalysisState.new("s", "u"), "lista os arquivos daqui")
    turno_um = list(vistos)
    vistos.clear()
    await orq.handle_message(AnalysisState.new("s", "u"), "lista de novo os arquivos")

    assert len(turno_um) >= 2, "o teste so prova algo com mais de uma chamada no turno"
    assert all(v == ["opus"] for v in turno_um), turno_um
    assert all(v == ["gpt"] for v in vistos), "no turno seguinte vale a troca"


def test_build_tier_provider_le_a_foto_do_turno(monkeypatch):
    """O construtor do Reforcado/Dedicado le `selecao_do_turno`, nao o painel."""
    from robinbandit import providers

    lidos = []
    monkeypatch.setattr(account_config, "selecao_do_turno", lambda modo: lidos.append(modo) or [])
    monkeypatch.setattr(account_config, "selecao_do_modo",
                        lambda modo: pytest.fail("leu o painel em vez da foto do turno"))
    from sentury.config import settings
    from sentury.main import _robin_config

    providers.build_tier_provider(_robin_config, "ultra_max", settings)
    assert lidos == ["dedicado"]
