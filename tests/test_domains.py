"""O pacote ativo fornece métricas, identidade e vocabulário ao motor."""
from sentury.config import settings
from sentury.domains import (
    DOMAIN_REGISTRY,
    DomainContext,
    DomainPack,
    default_context,
    get_active_domain,
    register_domain,
)

_METRICAS = {"medida"}


def test_setor_de_teste_registrado_e_selecionado(setor_teste):
    assert "setor_teste" in DOMAIN_REGISTRY
    assert get_active_domain().name == "setor_teste"


def test_metric_names_uniao(setor_teste):
    assert set(get_active_domain().metric_names) == _METRICAS


def test_domainpack_contrato_completo_com_defaults(setor_teste):
    d = get_active_domain()
    # O CX passou a declarar a propria identidade: e ela que o prompt monta em
    # cima do nucleo do agente. Trocar de setor troca esta metade.
    assert d.persona and "Medida" in d.persona
    # Era `is None`: o campo existia e ninguem lia, e o redator carregava o CX
    # no texto do MOTOR. Agora o setor declara a voz da resposta final dele.
    assert d.responder_persona and "registros" in d.responder_persona.lower()
    assert d.expected_sources == frozenset() and d.capabilities == frozenset()


def test_contexto_padrao_respeita_o_setor(setor_teste):
    ctx = default_context()
    assert isinstance(ctx, DomainContext)
    assert ctx.tenant_id == "default"
    assert ctx.domain_pack.name == "setor_teste"
    assert ctx.binding.domain == "setor_teste"
    assert set(ctx.domain_pack.metric_names) == _METRICAS


def test_dominio_desconhecido_cai_no_generalista(monkeypatch):
    """Um setor inexistente usa o generalista sem herdar métricas."""
    monkeypatch.setattr(settings, "SENTURY_DOMAIN", "setor_que_nao_existe")
    pack = get_active_domain()
    assert pack.name == "generalista"
    assert not pack.metric_names, "generalista nao herda metrica de setor nenhum"


def test_register_domain_pluga_novo_setor(monkeypatch):
    fake = DomainPack(
        name="marketing_test",
        metric_meta={"roas": {"label": "ROAS", "unidade": "x",
                              "fonte": "mídia", "descricao": "retorno sobre investimento"}},
        higher_is_better={"roas": True},
        cx_metrics=frozenset({"roas"}),
        ops_metrics=frozenset(),
    )
    try:
        register_domain(fake)
        monkeypatch.setattr(settings, "SENTURY_DOMAIN", "marketing_test")
        assert get_active_domain().name == "marketing_test"
        assert get_active_domain().metric_names == frozenset({"roas"})
    finally:
        DOMAIN_REGISTRY.pop("marketing_test", None)
