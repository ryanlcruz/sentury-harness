"""Uma volta que não observou nada não pode dizer "evidência suficiente".

O benchmark pegou isto literalmente. O agente listou a pasta, viu que o banco
não estava ali, e na volta seguinte o planner propôs **a mesma**
`listar_arquivos` com os mesmos argumentos. O guarda de repetição cortou:
certo, e o turno saiu assim:

    loops: 2   tool_calls: 1   repeated_calls_skipped: 1
    exit_reason: "completed"
    stop_reason: "evidência suficiente para responder"

Logo depois de o próprio texto da resposta dizer que não tinha achado o banco.

## O que NÃO mudou, e por quê

`exit_reason` continua `completed`. Duas outras suítes afirmam isso
(`test_loop_budget.py::test_passo_repetido_e_registrado_sem_sujar_a_conclusao` e
`test_replanejamento.py::test_passo_pulado_nao_vira_conclusao_suja`), e as
docstrings contam que alguém já tentou virar `REPETITION_DETECTED` e reverteu,
com razão: com o loop livre, cortar repetição é rotina saudável, o guarda de
evidência injeta uma ferramenta, o planner propõe a mesma, o guarda corta. Marcar
o turno como sujo esconderia a repetição que importa, a do agente girando em
falso.

A mentira que o benchmark pegou estava na **frase**, não na constante. `completed`
é o motivo auditável; `stop_reason` é o que a pessoa lê na Deliberação: e ela
dizia "evidência suficiente para responder". É só a frase que mudou.

A frase é escrita **onde a repetição acontece**, e um resultado novo a limpa: ela
descreve o que de fato terminou o turno, não o que aconteceu em algum momento
dele. Antes ficava no ponto de saída do laço, que a partir do re-planejamento por
lembrete deixou de ser alcançado no caso comum.
"""
import pytest

from sentury.config import settings
from sentury.harness.loop_budget import StopReason
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.test_orchestrator import (
    EchoResponder,
    ScriptedPlanner,
    _respond,
    _store,
    _tool_call,
)


@pytest.fixture
def com_loop_livre(monkeypatch):
    """O caso só existe com o loop ligado: é ele que dá a segunda volta."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True, raising=False)


def _orq(respostas_do_planner):
    return SenturyOrchestrator(
        planner=ScriptedPlanner(respostas_do_planner),
        responder=EchoResponder(),
        store=_store(),
    )


async def test_a_volta_que_so_repetiu_diz_que_repetiu(com_loop_livre, setor_teste):
    """Volta 1 roda; volta 2 propõe a mesma coisa e o guarda corta."""
    orq = _orq([_tool_call("consultar_medida"), _tool_call("consultar_medida"), _respond("Pronto.")])
    r = await orq.handle_message(AnalysisState.new("s-noop", "u"), "como esta o medida?")

    stats = r["harness"]["loop_stats"]
    assert stats["repeated_calls_skipped"] >= 1, stats
    assert "repetia" in stats["stop_reason"], stats
    # E o motivo auditável segue sendo conclusão: ver a docstring do módulo.
    assert stats["exit_reason"] == StopReason.COMPLETED, stats


async def test_o_motivo_generico_nao_sobrescreve_o_especifico(com_loop_livre):
    """O texto genérico era escrito por cima de qualquer motivo já registrado."""
    orq = _orq([_tool_call("consultar_medida"), _tool_call("consultar_medida"), _respond("Pronto.")])
    r = await orq.handle_message(AnalysisState.new("s-noop2", "u"), "como esta o medida?")

    assert r["harness"]["loop_stats"]["stop_reason"] != "evidência suficiente para responder"


async def test_turno_que_observou_algo_continua_concluindo(com_loop_livre, setor_teste):
    """A regressão a evitar: transformar rotina saudável em falha."""
    orq = _orq([_tool_call("consultar_medida"), _respond("Pronto.")])
    r = await orq.handle_message(AnalysisState.new("s-ok", "u"), "como esta o medida?")

    stats = r["harness"]["loop_stats"]
    assert stats["exit_reason"] == StopReason.COMPLETED, stats
    assert stats["tool_calls"] >= 1, stats


async def test_resposta_direta_continua_dizendo_que_foi_direta(com_loop_livre):
    orq = _orq([_respond("A capital do Chile é Santiago.")])
    r = await orq.handle_message(AnalysisState.new("s-direta", "u"), "capital do Chile?")

    stats = r["harness"]["loop_stats"]
    assert "sem necessidade de ferramenta" in stats["stop_reason"], stats
