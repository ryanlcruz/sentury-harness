"""AskUserQuestion: _extract_clarification normaliza/saneia o plano do Planner.

O método não usa `self`, então testamos a lógica de saneamento chamando-o com um
self fictício: sem precisar montar o orquestrador inteiro (store, LLMs, etc.)."""
import types

from sentury.harness.orchestrator import SenturyOrchestrator

_extract = SenturyOrchestrator._extract_clarification
_fake = types.SimpleNamespace()


def test_sem_perguntar_usuario_retorna_none():
    plan = [{"tool": "consultar_medida", "arguments": {}}]
    assert _extract(_fake, plan) is None


def test_extrai_pergunta_valida():
    plan = [{
        "tool": "perguntar_usuario",
        "arguments": {
            "intro": "Antes de gerar o gráfico preciso confirmar.",
            "questions": [{
                "header": "Objetivo",
                "question": "Qual o objetivo do gráfico?",
                "multiSelect": False,
                "options": [
                    {"label": "Evolução", "description": "Tendência no tempo"},
                    {"label": "Comparação", "description": "Entre regiões"},
                    {"label": "Distribuição", "description": "Como se distribui"},
                ],
            }],
        },
    }]
    out = _extract(_fake, plan)
    assert out is not None
    assert out["intro"].startswith("Antes de gerar")
    assert len(out["questions"]) == 1
    q = out["questions"][0]
    assert q["header"] == "Objetivo"
    assert q["multiSelect"] is False
    assert [o["label"] for o in q["options"]] == ["Evolução", "Comparação", "Distribuição"]


def test_teto_de_etapas_e_de_opcoes():
    """O teto e do codigo, nao do prompt: o prompt pedia no maximo 3 e o modelo
    mandava o que queria."""
    from sentury.harness.orchestrator import MAX_ETAPAS_DE_PERGUNTA, MAX_OPCOES_POR_ETAPA

    plan = [{
        "tool": "perguntar_usuario",
        "arguments": {
            "questions": [
                {"question": f"P{i}", "options": [{"label": f"o{j}"} for j in range(9)]}
                for i in range(MAX_ETAPAS_DE_PERGUNTA + 3)
            ],
        },
    }]
    out = _extract(_fake, plan)
    assert len(out["questions"]) == MAX_ETAPAS_DE_PERGUNTA
    assert len(out["questions"][0]["options"]) == MAX_OPCOES_POR_ETAPA


def test_pergunta_com_menos_de_2_opcoes_e_descartada():
    plan = [{
        "tool": "perguntar_usuario",
        "arguments": {"questions": [{"question": "P?", "options": [{"label": "so-uma"}]}]},
    }]
    assert _extract(_fake, plan) is None


def test_intro_default_quando_ausente():
    plan = [{
        "tool": "perguntar_usuario",
        "arguments": {"questions": [{"question": "P?", "options": [
            {"label": "a"}, {"label": "b"}]}]},
    }]
    out = _extract(_fake, plan)
    assert out["intro"]  # não vazio (usa default)


def test_options_como_strings_puras():
    plan = [{
        "tool": "perguntar_usuario",
        "arguments": {"questions": [{"question": "P?", "options": ["Barras", "Linha"]}]},
    }]
    out = _extract(_fake, plan)
    assert [o["label"] for o in out["questions"][0]["options"]] == ["Barras", "Linha"]
