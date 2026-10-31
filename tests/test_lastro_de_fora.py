"""Gráfico feito com dado lido de arquivo, comando ou página tem lastro.

O guard antifabricação só aceitava as análises do setor: no generalista, um
gráfico do CSV lido por `ler_arquivo` era recusado como "número inventado".
"""
from types import SimpleNamespace

from sentury.harness.grounding import havia_dado_de_fora
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.tools.registry import com_propriedade
from sentury.harness.artefato_do_turno import recusar_artefato_sem_lastro

ANEXO = {"type": "chart_json", "content": "{}"}


def _julgar(state, tool_results, pre):
    falso = SimpleNamespace(_GROUNDING_TOOLS=SenturyOrchestrator._GROUNDING_TOOLS)
    return recusar_artefato_sem_lastro(
        falso, state, dict(ANEXO), "segue o gráfico", tool_results, pre_turn_had_data=pre,
    )


def test_ferramentas_de_dado_de_fora_vem_do_yaml():
    assert {"ler_arquivo", "executar_comando", "ler_pagina"} <= com_propriedade("traz_dado")
    assert "executar_python" not in SenturyOrchestrator._GROUNDING_TOOLS


def test_grafico_do_arquivo_lido_no_turno_passa():
    anexo, _ = _julgar(AnalysisState("s", "u"), [{"tool": "ler_arquivo", "result": {"conteudo": "a,1"}}], False)
    assert anexo is not None


def test_grafico_sem_nenhum_dado_continua_recusado():
    anexo, texto = _julgar(AnalysisState("s", "u"), [], False)
    assert anexo is None and "inventados" in texto


def test_python_sozinho_nao_se_da_lastro():
    anexo, _ = _julgar(AnalysisState("s", "u"), [{"tool": "executar_python", "result": {"stdout": "1"}}], False)
    assert anexo is None


def test_dado_lido_em_turno_anterior_conta():
    state = AnalysisState("s", "u")
    state.history.append({"role": "system", "content": "RESULTADO DA FERRAMENTA ...",
                          "chamada": {"id": "", "nome": "executar_comando", "argumentos": {}}})
    assert havia_dado_de_fora(state, SenturyOrchestrator._GROUNDING_TOOLS)
    state_vazio = AnalysisState("s", "u")
    state_vazio.history.append({"role": "system", "content": "x",
                                "chamada": {"id": "", "nome": "executar_python", "argumentos": {}}})
    assert not havia_dado_de_fora(state_vazio, SenturyOrchestrator._GROUNDING_TOOLS)
