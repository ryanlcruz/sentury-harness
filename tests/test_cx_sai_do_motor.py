"""O motor para de saber o que e NPS.

Antes o catalogo de CX morava dentro do `PLANNER_SYSTEM_PROMPT` e uma funcao
(`_catalogo_do_setor`) REMOVIA essas linhas quando o setor estava desligado.
Subtrativo, e fragil pelo motivo de sempre: bastava uma frase falar de detrator
sem usar a palavra "NPS" para escapar do filtro, e o generalista continuava
oferecendo analise que o produto de quem estava usando nao tem.

A inversao: o prompt base nao tem CX, e o pacote soma o dele. O teste que
importa e o primeiro: se o motor souber o que e NPS de novo, o resto nao
adianta.
"""
import re
from pathlib import Path

import pytest

from sentury.domains import escolha
from sentury.harness.orchestrator import PLANNER_SYSTEM_PROMPT, _prompt_do_planejador

# Vocabulario que so faz sentido no setor de CX. Nenhum deles pode aparecer no
# prompt que o generalista recebe.
DE_CX = (
    "nps", "csat", "detrator",
    "analyze_nps", "analyze_tickets", "analyze_sentiment", "analyze_segments",
    "root_cause", "executive_summary", "generate_insights",
    "generate_recommendations", "priorizar_casos", "gerar_resposta",
    "compare_periods",
    "feedbacks", "technicians", "pesquisa de satisfacao",
)


@pytest.fixture
def setor(monkeypatch):
    """Liga um setor sem mexer no disco de quem esta rodando o teste."""
    def escolher(nome):
        monkeypatch.setattr(escolha, "ler", lambda *a, **k: nome)
    return escolher


VOCABULARIO_DE_CX = (
    r"\bnps\b", r"\bcsat\b", r"\bdetratore?s?\b",
    r"analyze_", r"root_cause", r"executive_summary", r"\bfilial\b",
)


def test_o_prompt_base_nao_sabe_o_que_e_nps():
    """O teste que sustenta todos os outros: se o vocabulario de um setor volta
    para o motor, nao importa o quanto o resto esteja bem montado."""
    baixo = PLANNER_SYSTEM_PROMPT.lower()
    achados = [t for t in DE_CX if t in baixo]
    assert achados == [], achados


def test_o_generalista_nao_recebe_nada_de_cx(setor):
    """Era "prompt base e mais nada". Agora o prompt tambem carrega a orientacao
    de cada ferramenta NA MESA (ver llm/secoes.py): e e exatamente por isso que
    a regua ficou mais forte, nao mais fraca: a orientacao de uma ferramenta de
    setor so existe quando a ferramenta existe.

    Entao o que se afirma aqui deixou de ser tamanho e passou a ser conteudo."""
    setor("generalista")
    montado = _prompt_do_planejador()
    assert montado.startswith(PLANNER_SYSTEM_PROMPT.rstrip())
    achados = [p for p in VOCABULARIO_DE_CX if re.search(p, montado, re.I)]
    assert achados == [], achados


def test_setor_sem_planner_nao_quebra(setor):
    """`coder` nao tem `planner.md`, e nao ter e o normal: a maioria dos
    pacotes so declara metrica e vocabulario.

    O prompt ganha as orientacoes das ferramentas NA MESA (ver llm/secoes.py),
    entao a comparacao e "comeca com a base", nao "e igual a base"."""
    setor("coder")
    montado = _prompt_do_planejador()
    assert montado.startswith(PLANNER_SYSTEM_PROMPT.rstrip())
    assert "# O que o planejador precisa saber" not in montado


def test_pacote_quebrado_devolve_o_prompt_base(monkeypatch):
    """O motor tem que continuar de pe com o pacote no chao."""
    from sentury.harness import orchestrator

    def explode():
        raise RuntimeError("pacote corrompido")

    monkeypatch.setattr("sentury.domains.registry.get_active_domain", explode)
    montado = orchestrator._prompt_do_planejador()
    # Falha ABERTA: o pacote caiu, e o prompt base continua saindo inteiro.
    assert montado.startswith(PLANNER_SYSTEM_PROMPT.rstrip())


def test_o_filtro_subtrativo_morreu():
    """`_catalogo_do_setor` cortava linha a linha por palavra-chave. Se ele
    voltar, volta junto o falso negativo que ele nunca soube pegar."""
    fonte = Path("sentury/harness/orchestrator.py").read_text(encoding="utf-8")
    assert "_catalogo_do_setor" not in fonte
    assert "_TERMOS_DE_CX" not in fonte


def test_nenhuma_ferramenta_listada_duas_vezes():
    """Quatro estavam: `ler_arquivo`, `listar_arquivos`, `escrever_arquivo` e
    `editar_arquivo`, cada uma com DESCRICAO DIFERENTE. O modelo recebia duas
    versoes contraditorias da mesma ferramenta em toda chamada."""
    nomes = [
        linha.split("(")[0].strip("- ").strip()
        for linha in PLANNER_SYSTEM_PROMPT.splitlines()
        if linha.startswith("- ") and "(" in linha
    ]
    repetidas = sorted({n for n in nomes if nomes.count(n) > 1})
    assert repetidas == [], repetidas


# ------------------------- a tabela de recuperacao de grafico

def test_a_tabela_de_grafico_saiu_do_motor():
    fonte = Path("sentury/harness/orchestrator.py").read_text(encoding="utf-8")
    assert "_CHART_ANALYSIS_HINTS" not in fonte


def test_o_generalista_nao_tem_o_que_recuperar(setor):
    """Era um bug latente: a tabela morava no motor, entao o generalista pedia
    grafico de "sentimento" e o motor injetava `analyze_sentiment`: que depois
    do bloco 4 nem esta na mesa dele. Rodava contra dado que nao existe."""
    from sentury.domains.do_setor import dicas_de_grafico as _dicas_de_grafico

    setor("generalista")
    assert _dicas_de_grafico() == ()


def test_dica_sem_termo_ou_sem_ferramenta_e_ignorada(tmp_path):
    """Metade de uma dica nao recupera nada, e uma entrada pela metade num
    YAML e erro de quem escreveu: melhor sumir que rotear para o vazio."""
    from sentury.domains.carregador import ler

    (tmp_path / "pack.yaml").write_text(
        "nome: teste" + chr(10) +
        # Pacote sem metrica nenhuma e descartado pelo carregador, entao o
        # minimo tem que estar aqui para o teste falar sobre as dicas.
        "metricas:" + chr(10) +
        "  x:" + chr(10) +
        "    label: X" + chr(10) +
        "    grupo: operacao" + chr(10) +
        "dicas_de_grafico:" + chr(10) +
        "  - ferramenta: boa" + chr(10) +
        "    termos: [x]" + chr(10) +
        "  - ferramenta: sem_termos" + chr(10) +
        "    termos: []" + chr(10) +
        "  - termos: [sem_ferramenta]" + chr(10),
        encoding="utf-8",
    )
    pack = ler(tmp_path / "pack.yaml")
    assert pack.dicas_de_grafico == (("boa", ("x",)),)


# ------------------------------- as ferramentas de entrega

def test_o_motor_nao_conhece_as_entregas_pelo_nome():
    """O laco do turno sabia `gerar_resposta` e `gerar_plano_acao` de cor, e
    carregava junto o nome do arquivo, o titulo e o texto que manda o modelo
    enriquecer com "o IMPACTO operacional (maquina parada, SLA, churn)". Copy
    de produto de CX no caminho mais quente do motor."""
    fonte = Path("sentury/harness/orchestrator.py").read_text(encoding="utf-8")
    assert "plano-de-acao.md" not in fonte
    assert "maquina parada" not in fonte and "máquina parada" not in fonte
    assert "Plano de Ação" not in fonte


def test_o_generalista_nao_tem_entrega(setor):
    """Sem setor, nenhuma ferramenta entrega por conta propria: tudo passa pelo
    modelo, como qualquer resultado."""
    from sentury.domains.do_setor import entregas

    setor("generalista")
    assert entregas() == {}


def test_o_card_e_o_anexo_usam_o_mesmo_nome(setor):
    """Com reescrita, o documento chega como texto da resposta e vira card;
    sem reescrita, vira anexo direto. Os dois caminhos tem que produzir o mesmo
    nome de arquivo: senao o mesmo plano baixa diferente dependendo de qual
    provedor atendeu o turno."""
    import inspect

    from sentury.harness.artefato_do_turno import plano_vira_card

    fonte = inspect.getsource(plano_vira_card)
    assert "_entregas_do_setor()" in fonte
    assert 'entrega.get("arquivo")' in fonte


def test_os_leitores_de_pacote_moram_juntos():
    """Tres perguntas que o motor faz ao setor, no mesmo lugar. Espalhadas pelo
    orquestrador elas viravam mais linha num arquivo que ja bate no teto."""
    from sentury.domains import do_setor

    assert sorted(do_setor.__all__) == [
        # `analises`: as analises moram no pacote, e o motor pede por aqui em
        # vez de importar direto.
        # `analise_de_base`: o conselho pergunta ao setor qual analise rodar;
        # cravar `analyze_nps` no orquestrador chamaria, no generalista, uma
        # ferramenta que nao existe.
        "analise_de_base", "analises",
        # `atalhos` e `exemplos_de_pedido`: os comandos e os exemplos da ajuda
        # do Telegram (`/nps`, "SLA da filial") ficavam no gateway do motor.
        "atalhos",
        # `colunas_de_grafico`: o par de colunas a plotar por ferramenta vem do
        # setor, e nao de um dicionario de analises de CX no motor.
        "colunas_de_grafico",
        # `cores_de_rotulo`: leal/neutro/detrator com cor fixa estavam no
        # renderer de grafico do motor.
        "cores_de_rotulo",
        "dicas_de_grafico", "dimensoes", "entregas",
        # `executar_analise`: o despacho das analises (`regiao`, `filial`,
        # `unidade_negocio`) e do setor, nao do `catalog.py`.
        "executar_analise",
        # `executar_na_voz` e `ferramentas_da_voz`: as consultas da ligacao
        # (NPS, chamados, causa-raiz) moravam em `external/live_gateway.py`.
        "executar_na_voz", "exemplos_de_pedido", "ferramenta_de_causa", "ferramentas_da_voz",
        # `fontes_de_dados` e `publicos`: as opcoes da pergunta "de que dado e
        # este material, e para quem" (harness/termos_do_setor.py).
        "fontes_de_dados",
        # `formas_de_grafico`: NPS em linha e sentimento em rosca estavam
        # cravados pelo nome da ferramenta em `artifacts/visualization.py`.
        "formas_de_grafico",
        "guardas",
        # `insight_proativo`: a observacao sobre o NPS do mes era um metodo
        # do orquestrador (setores/cx/analises/insights.py).
        "insight_proativo",
        # `medir_para_alerta` e `metricas_vigiaveis`: o vigia do `/alerta` e do
        # motor, e a medicao (chamados, filial, SLA) e pergunta ao setor.
        "medir_para_alerta", "metricas_vigiaveis", "publicos",
        # `termos_de_dado`: as palavras que o planejador de artefatos lia como
        # dado (nps, csat, sla, chamados) eram uma lista no motor.
        # `rotulos_de_coluna` e `titulos_de_secao`: "Promotores", "Neutros" e
        # "NPS e lealdade" eram dicionarios em `renderers/html_dashboard.py`.
        "rotulos_de_coluna",
        "termos_de_dado",
        # `titulos_de_painel`: o titulo de cada painel vem do setor, nao de um
        # dicionario em `renderers/html_dashboard.py`.
        "titulos_de_painel",
        # `titulos_de_passo`: "Cruzando o NPS com chamados..." era o titulo do
        # passo no `_tool_title` do orquestrador.
        "titulos_de_passo",
        "titulos_de_secao",
    ]


# ------------------------------------- as guardas declaradas pelo setor

def _com_dados():
    from sentury.harness.state import AnalysisState

    estado = AnalysisState.new("s1", "u1")
    estado.results = {"r1": {"tool": "analyze_nps"}}
    estado.last_result_id = "r1"
    return estado


def _orquestrador():
    from sentury.harness.orchestrator import SenturyOrchestrator

    return SenturyOrchestrator.__new__(SenturyOrchestrator)


def test_as_regioes_do_brasil_sairam_do_motor():
    """Era o pior do lote: `["sudeste", "sul", "norte", "nordeste",
    "centro-oeste"]` dentro do laco do turno. Valor do DATASET no motor: um
    cliente cuja operacao e por pais, unidade ou produto nao tem "sudeste" em
    lugar nenhum, e o motor procurava assim mesmo."""
    fonte = Path("sentury/harness/orchestrator.py").read_text(encoding="utf-8")
    for regiao in ("sudeste", "nordeste", "centro-oeste"):
        assert regiao not in fonte.lower(), regiao


def test_o_roteamento_por_metodologia_saiu_do_motor():
    """As frases que disparam uma metodologia moravam numa tabela de 33 linhas
    no orquestrador, a dois mil linhas do arquivo que descreve o procedimento:
    entao mudar a skill nunca lembrava de mudar o gatilho. Agora cada skill
    declara os seus, e com a skill dentro do pacote o gatilho liga e desliga
    com o setor."""
    fonte = Path("sentury/harness/orchestrator.py").read_text(encoding="utf-8")
    assert "_IMPLICIT_SKILL_TRIGGERS" not in fonte
    for frase in ("espinha de peixe", "5 whys", "5w2h", "matriz gut", "six sigma"):
        assert frase not in fonte.lower(), frase


def test_nenhuma_metodologia_mora_no_motor():
    """Metodologia de CX é do setor: o motor não cita nenhuma, nem como pista
    de título, que mora no `tools.yaml`."""
    fonte = Path("sentury/harness/orchestrator.py").read_text(encoding="utf-8").lower()
    assert "ishikawa" not in fonte, "mencao nova a ishikawa no motor"
    assert "dmaic" not in fonte, "mencao nova a dmaic no motor"
    assert "six sigma" not in fonte


def test_o_rotulo_da_skill_mora_com_a_skill():
    """O rotulo de uma skill mora no SKILL.md dela, nao no motor: desligar o
    setor tira a skill e o rotulo juntos."""
    fonte = Path("sentury/harness/orchestrator.py").read_text(encoding="utf-8")
    assert "_SKILL_CATALOG" not in fonte
    assert "causa-raiz de dores de CX" not in fonte
    assert "monte um diagrama do NPS" not in fonte


def test_a_memoria_nao_fala_de_gestor_nem_de_filial():
    """O texto da memoria entra no prompt de todo setor."""
    from sentury.memory.user_memory import build_memory_context

    texto = build_memory_context([{"texto": "prefere tabelas"}]).lower()
    for termo in ("gestor", "filial", "região", "regiao", "unidade"):
        assert termo not in texto, termo


def test_o_que_chega_ao_modelo_no_generalista_nao_fala_de_cx(setor, setor_teste):
    """Os exemplos do planejador entram no prompt de todo turno; o titulo do
    passo e as heuristicas de conselho e de filtro liam NPS."""
    from pathlib import Path

    from sentury.harness import orchestrator
    from sentury.harness.orchestrator import SenturyOrchestrator as O

    planner = (Path(orchestrator.__file__).parents[1] / "context" / "base" / "PLANNER_SYSTEM_PROMPT.md").read_text(encoding="utf-8").lower()
    for termo in ("nps", "filiais", "filial"):
        assert termo not in planner, termo

    setor("generalista")
    assert "NPS" not in O._tool_title("root_cause", {})
    setor("setor_teste")
    assert O._tool_title("consultar_medida", {}).startswith("Consultando a medida")


def test_o_catalogo_nao_conhece_os_argumentos_de_cx(setor_teste):
    """O despacho das analises e do pacote. O catalogo so encaminha."""
    import inspect

    from sentury.tools import catalog

    fonte = inspect.getsource(catalog)
    for termo in ("unidade_negocio", "filial", "analyze_nps", "canal_preferido"):
        assert termo not in fonte, termo
    assert "consultar_medida" in catalog.CHARTABLE_SOURCE_TOOLS
    assert "consultar_medida" in catalog.EXPORT_SOURCE_TOOLS
