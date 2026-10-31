"""L1c: o planner decide DE NOVO depois de ver o resultado.

Sem isto ele decide tudo antes de qualquer dado existir, e nada do que foi
construido consegue reagir: o `deliberate` nao tem um "depois de ver os dados"
(medido: 0 disparos em 13 casos), o orcamento nao tem entre-passos onde frear,
e refinar o artefato anterior nao tem momento.
"""
import json

import pytest

from sentury.config import settings
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.test_orchestrator import (
    EchoResponder, RoteiroPlanner, ScriptedPlanner,
    _respond, _store, _tool_call,
)


def _orch(planner):
    return SenturyOrchestrator(planner=planner, responder=EchoResponder(),
                               store=_store())


async def test_investiga_em_etapas_em_vez_de_roteiro_fechado(monkeypatch):
    """A diferenca entre executar um roteiro e investigar: a 2a ferramenta e
    escolhida DEPOIS de ver o resultado da 1a."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    planner = ScriptedPlanner([
        _tool_call("consultar_medida"),      # volta 1: olha o panorama
        _tool_call("consultar_medida"),       # volta 2: JA vendo o Medida, cava a causa
        _respond("A queda vem do backlog."),   # volta 3: tem o suficiente
    ])
    r = await _orch(planner).handle_message(AnalysisState.new("s-rep1", "u"), "por que o medida caiu?")
    stats = r["harness"]["loop_stats"]
    # Mais de uma volta = o planner foi consultado DEPOIS de ver o resultado.
    # (Nao exijo consumir o roteiro todo: o guard de evidencia pode injetar a
    # ferramenta causal antes, e ai o planner precisa de menos passos.)
    assert stats["loops"] >= 2
    assert len(planner.scripted) < 3, "o planner nao foi reconsultado"


async def test_para_sozinho_quando_o_planner_responde(monkeypatch, setor_teste):
    """Regra do letta v3: nao chamou ferramenta, para. Nao precisa de contador."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    planner = ScriptedPlanner([_tool_call("consultar_medida"), _respond("Pronto."),
                               _respond("nao deveria chegar aqui")])
    r = await _orch(planner).handle_message(AnalysisState.new("s-rep2", "u"), "como esta o medida?")
    stats = r["harness"]["loop_stats"]
    assert stats["exit_reason"] == "completed"
    assert stats["loops"] < 6, "girou ate o teto em vez de parar quando o planner respondeu"


async def test_desligado_mantem_o_plano_fechado(monkeypatch, setor_teste):
    """Default intocado: sem a flag, uma volta so, como sempre foi."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", False)
    planner = ScriptedPlanner([_tool_call("consultar_medida"), _respond("x"), _respond("x")])
    r = await _orch(planner).handle_message(AnalysisState.new("s-rep3", "u"), "como esta o medida?")
    assert r["harness"]["loop_stats"]["loops"] == 1


async def test_o_orcamento_e_o_freio(monkeypatch):
    """Replanejar sem freio seria custo ilimitado. Quem segura e o orcamento."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setattr(settings, "SENTURY_MAX_LOOPS", 3)
    # planner que NUNCA responde: so o orcamento pode parar isso
    planner = ScriptedPlanner([_tool_call("consultar_medida")] * 20)
    r = await _orch(planner).handle_message(AnalysisState.new("s-rep4", "u"), "analise")
    assert r["harness"]["loop_stats"]["loops"] <= 3


async def test_passo_pulado_nao_vira_conclusao_suja(monkeypatch, setor_teste):
    """Com o loop livre isso e rotina: o guard de evidencia injeta uma
    ferramenta, o planner propoe a mesma, o guard de repeticao corta. Concluir
    depois disso e conclusao LIMPA -- o pulo fica registrado a parte."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    planner = ScriptedPlanner([_tool_call("consultar_medida"), _tool_call("consultar_medida"),
                               _respond("pronto")])
    r = await _orch(planner).handle_message(AnalysisState.new("s-rep5", "u"), "como esta o medida?")
    stats = r["harness"]["loop_stats"]
    assert stats["exit_reason"] == "completed"
    assert stats["repeated_calls_skipped"] >= 1


async def test_erro_de_browser_volta_ao_agente_para_outra_acao(monkeypatch):
    """Uma navegação falha não vira resposta fixa nem encerra a investigação."""
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    chamadas = []

    async def browser_falso(_store, _state, tool, argumentos, *_args, **_kwargs):
        chamadas.append((tool, argumentos))
        if len(chamadas) == 1:
            return {"ok": False, "motivo": "navegação indisponível"}
        return {"ok": True, "titulo": "Example Domains"}

    monkeypatch.setattr("sentury.harness.execucao_do_passo.execute_tool", browser_falso)
    planner = RoteiroPlanner([
        _tool_call("browser", acao="navegar", argumentos={"url": "https://example.com"}),
        _tool_call("browser", acao="snapshot"),
        _respond("Conferi a página."),
    ])

    resposta = await _orch(planner).handle_message(
        AnalysisState.new("s-browser-recovery", "u"), "confira o título no navegador",
    )

    assert len(chamadas) == 2
    assert any(
        "navegação indisponível" in str(chamada["messages"])
        for chamada in planner.calls[1:]
    )
    assert "Nao vou dizer que gerei" not in resposta["message"]
