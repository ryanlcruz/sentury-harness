from sentury.renderers.chart import generate_chart_data


def test_time_series_prefers_line_chart():
    from sentury.artifacts.visualization import plan_visualization

    plan = plan_visualization(
        tool="consultar_medida",
        table=[
            {"mes": "2026-01", "medida": -27.1},
            {"mes": "2026-02", "medida": -26.3},
            {"mes": "2026-03", "medida": -31.2},
        ],
    )

    assert plan["chart_type"] == "line"


def test_small_percentage_distribution_prefers_doughnut():
    from sentury.artifacts.visualization import plan_visualization

    plan = plan_visualization(
        tool="consultar_medida",
        table=[
            {"sentimento": "promotores", "pct": 18.6},
            {"sentimento": "neutros", "pct": 30.3},
            {"sentimento": "detratores", "pct": 51.1},
        ],
    )

    assert plan["chart_type"] == "doughnut"


def test_pizza_em_serie_temporal_negativa_vira_linha():
    # Regressão do "erro 500 ao trocar gráfico" + "gráfico de cabeça pra baixo":
    # pedir pizza sobre Medida (série temporal negativa) fazia ax.pie() lançar
    # "Wedge sizes must be non negative". Barras negativas "penduram" pra baixo e
    # parecem invertidas, então uma série temporal negativa vira LINHA.
    from sentury.artifacts.visualization import plan_visualization

    plan = plan_visualization(
        tool="consultar_medida",
        table=[
            {"mes": "2026-01", "medida": -25.0},
            {"mes": "2026-02", "medida": -30.0},
            {"mes": "2026-07", "medida": -49.3},
        ],
        tipo="pizza",
    )

    assert plan["chart_type"] == "line"
    assert all(v < 0 for v in plan["values"])  # os dados negativos foram preservados


def test_pizza_categorica_negativa_degrada_para_barras():
    # Sem eixo temporal, pizza incompatível (negativos) degrada para barras.
    from sentury.artifacts.visualization import plan_visualization

    plan = plan_visualization(
        tool="consultar_medida",
        table=[
            {"unidade": "Rental", "delta": -5.0},
            {"unidade": "Peças", "delta": -3.0},
            {"unidade": "Serviço", "delta": -8.0},
        ],
        tipo="pizza",
    )

    assert plan["chart_type"] == "bar"


def test_pizza_com_valores_positivos_continua_pizza():
    # A guarda não pode ser agressiva: pizza sobre percentuais positivos segue pizza.
    from sentury.artifacts.visualization import plan_visualization

    plan = plan_visualization(
        tool="consultar_medida",
        table=[
            {"cat": "A", "pct": 40.0},
            {"cat": "B", "pct": 35.0},
            {"cat": "C", "pct": 25.0},
        ],
        tipo="pizza",
    )

    assert plan["chart_type"] == "doughnut"


def test_long_category_labels_prefer_horizontal_bar():
    from sentury.artifacts.visualization import plan_visualization

    plan = plan_visualization(
        tool="executar_python",
        table=[
            {"motivo": "Atraso na entrega de pecas no sudeste", "pct": 31.0},
            {"motivo": "Falha de comunicacao na abertura do chamado", "pct": 22.0},
        ],
    )

    assert plan["chart_type"] == "bar"
    assert plan["index_axis"] == "y"


def test_generate_chart_data_uses_doughnut_for_small_percentage_distribution():
    result = [
        {"grupo": "Alfa", "pct": 18.6},
        {"grupo": "Beta", "pct": 30.3},
        {"grupo": "Gama", "pct": 51.1},
    ]

    payload = generate_chart_data("consultar_medida", result, tipo="pizza")

    assert payload["type"] == "doughnut"


def test_generate_chart_data_uses_horizontal_bar_for_long_labels():
    result = [
            {"motivo": "Atraso na entrega de pecas no sudeste", "pct": 31.0},
            {"motivo": "Falha de comunicacao na abertura do chamado", "pct": 22.0},
    ]

    payload = generate_chart_data("executar_python", result)

    assert payload["type"] == "bar"
    assert payload["options"]["indexAxis"] == "y"


def test_many_categories_are_aggregated_into_outros():
    from sentury.artifacts.visualization import plan_visualization

    table = [
        {"motivo": f"Motivo {index}", "pct": float(20 - index)}
        for index in range(10)
    ]

    plan = plan_visualization(
        tool="executar_python",
        table=table,
    )

    assert plan["chart_type"] == "bar"
    assert plan["aggregation_applied"] is True
    assert len(plan["labels"]) == 8
    assert plan["labels"][-1] == "Outros"


def test_long_labels_gain_short_display_labels_but_keep_full_text():
    result = [
            {"motivo": "Atraso muito grande na entrega de pecas para o cliente do sudeste", "pct": 31.0},
            {"motivo": "Falha de comunicacao recorrente na abertura do chamado tecnico", "pct": 22.0},
    ]

    payload = generate_chart_data("executar_python", result)

    labels = payload["data"]["labels"]
    full_labels = payload["meta"]["full_labels"]

    assert labels[0].endswith("...")
    assert full_labels[0].startswith("Atraso muito grande")
    assert payload["meta"]["label_truncation_applied"] is True

def test_a_forma_preferida_vem_do_setor(setor_teste):
    """O setor diz que a saida da ferramenta tem rotulo longo; o motor nao precisa saber qual."""
    from sentury.artifacts.visualization import plan_visualization

    plan = plan_visualization(tool="consultar_motivos",
                              table=[{"grupo": "Alfa", "medida": 3.0}, {"grupo": "Beta", "medida": 5.0}])
    assert (plan["chart_type"], plan["index_axis"]) == ("bar", "y")


def test_forma_que_o_motor_nao_desenha_fica_de_fora(setor_teste):
    from sentury.domains.do_setor import formas_de_grafico

    assert formas_de_grafico() == {"consultar_motivos": "barra_horizontal"}


def test_sem_setor_o_motor_nao_conhece_ferramenta_de_cx():
    """O nome de uma analise de CX nao muda o grafico do generalista."""
    from sentury.artifacts.visualization import plan_visualization
    from sentury.domains.escopo import usar_setor

    with usar_setor("generalista"):
        plan = plan_visualization(tool="analyze_nps",
                                  table=[{"regiao": "Norte", "nps": 10.0}, {"regiao": "Sul", "nps": 20.0}])
    assert plan["chart_type"] == "bar"
