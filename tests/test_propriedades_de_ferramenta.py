from sentury.harness.funcoes import ferramentas_ligadas
from sentury.tools.registry import TOOL_REGISTRY, com_propriedade


def test_badges_usam_o_yaml_e_aceitam_outra_ferramenta_declarada(monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "ferramenta_de_teste",
                        {"funcoes_disponiveis": ["novo", "workflow"]})
    assert ferramentas_ligadas(["novo"]) == {"ferramenta_de_teste"}
    assert "ferramenta_de_teste" in ferramentas_ligadas(["workflow"])
    assert not ferramentas_ligadas(["ausente"])


def test_terminais_e_fontes_de_dado_derivam_de_propriedades():
    from sentury.tools.saida_da_tela import TERMINAIS
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.policy import ANALYSIS_TOOLS

    assert TERMINAIS == com_propriedade("saida_terminal")
    assert TERMINAIS == {"executar_python", "executar_comando", "executar_script", "command_status", "processos"}
    assert SenturyOrchestrator._GROUNDING_TOOLS == com_propriedade("traz_dado")
    assert ANALYSIS_TOOLS - {"executar_python"} <= com_propriedade("traz_dado")
    assert "executar_python" not in com_propriedade("traz_dado")
