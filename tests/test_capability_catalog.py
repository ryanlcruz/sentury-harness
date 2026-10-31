from sentury.skills.skill_schema import SkillEntry
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.tools.capability_catalog import build_catalog, render_matches, search_catalog
from sentury.tools.registry import TOOL_REGISTRY, sempre_exposta, ferramentas_do_setor_ativo
from tests.test_orchestrator import CapturePlanner, EchoResponder, _respond, _store


def _names(matches):
    return [entry.name for entry, _score in matches]


def test_catalogo_e_derivado_do_registry_vivo(setor_teste):
    catalog = build_catalog(TOOL_REGISTRY)
    esperadas = {nome for nome, meta in ferramentas_do_setor_ativo().items() if sempre_exposta(meta)}
    assert {entry.name for entry in catalog} == esperadas
    assert "save_analysis" not in esperadas


def test_busca_local_encontra_conhecimento_sem_chamar_llm():
    """Pergunta CONCEITUAL cai na busca de conhecimento, nao numa analise.

    O `quando_usar` do `buscar_conhecimento` fala de conceito, nao de sigla
    de um setor; a pergunta do teste tambem e de conceito, para nao passar
    por casar uma metrica de CX.
    """
    matches = search_catalog(
        build_catalog(TOOL_REGISTRY), "o que é isso? defina o conceito", limit=4)
    assert "buscar_conhecimento" in _names(matches)


def test_busca_local_encontra_causa_e_correlacao(setor_teste):
    matches = search_catalog(
        build_catalog(TOOL_REGISTRY),
        "por que o Medida caiu e qual a relação com o backlog?",
        limit=6,
    )
    names = _names(matches)
    assert "consultar_medida" in names
    assert "consultar_medida" in names


def test_skills_entram_com_resumo_sem_corpo_completo(tmp_path):
    skill = SkillEntry(
        name="root-cause-analysis",
        description="Investiga causa raiz com evidências.",
        category="analysis",
        family="operations",
        priority=80,
        tags=["ishikawa", "5 porquês"],
        path=tmp_path,
        tools_used=["consultar_medida"],
    )
    matches = search_catalog(
        build_catalog({}, [skill]),
        "faça um ishikawa",
        limit=3,
    )
    assert _names(matches) == ["root-cause-analysis"]
    rendered = render_matches(matches)
    assert "root-cause-analysis" in rendered
    assert "SKILL.md" not in rendered


def test_consulta_sem_sinal_nao_fabrica_match():
    assert search_catalog(build_catalog(TOOL_REGISTRY), "oi", limit=5) == []


def test_mapa_compacto_preserva_os_nomes_exatos():
    from sentury.tools.capability_catalog import CapabilityEntry, render_manifest

    entradas = [CapabilityEntry(
        f"tool_{i}", "tool", "descrição " * 100, category="plugin") for i in range(8)]
    mapa = render_manifest(entradas, max_chars=1000)
    assert len(mapa) <= 1000
    assert "[plugin]:" not in mapa
    assert all(f"`tool_{i}`" in mapa for i in range(8))


async def test_planner_recebe_candidatos_e_harness_os_torna_observaveis(monkeypatch, setor_teste):
    from sentury.config import settings

    monkeypatch.setattr(settings, "SENTURY_PROGRESSIVE_CAPABILITIES", True)

    # O mecanismo sob demanda é o que se mede aqui; o teto em zero o liga.

    monkeypatch.setattr(settings, "SENTURY_FERRAMENTAS_TETO_TOKENS", 0)
    planner = CapturePlanner(_respond("Vou responder com base no pedido."))
    orchestrator = SenturyOrchestrator(
        planner=planner,
        responder=EchoResponder(),
        store=_store(),
    )

    result = await orchestrator.handle_message(
        AnalysisState.new("capability-prompt", "u"),
        "por que o Medida caiu e qual a relação com o backlog?",
    )

    prompt = "\n".join(str(m.get("content") or "") for m in planner.calls[0]["messages"])
    assert "Descoberta Progressiva de Capacidades" in prompt
    assert "Descoberta Progressiva" not in planner.calls[0]["messages"][0]["content"]
    assert "`consultar_medida`" in prompt
    public_names = {item["name"] for item in result["harness"]["capability_matches"]}
    assert "consultar_medida" in public_names
