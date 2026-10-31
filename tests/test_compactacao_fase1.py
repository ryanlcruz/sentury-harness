"""Primeira etapa da compactacao: barata, deterministica, antes de gastar LLM.

Cortar o texto pelo comeco e pelo fim jogaria o meio fora. Num produto de
analise isso e arriscado: o valor esta nos numeros, e o corte por caractere
pode remover justo eles.
"""
from sentury.harness.context_budget import (
    ContextBudgetManager,
    Contextualizer,
    summarize_tool_result,
)


def _resultado(tool, corpo, ruido=4000):
    return (f'RESULTADO DA FERRAMENTA "{tool}" (ja executada): '
            + str({**corpo, "_dump": "x" * ruido}))


def _mgr():
    return ContextBudgetManager(Contextualizer(llm_chain=None), tool_budget_chars=800)


def test_resumo_preserva_os_numeros():
    saida = summarize_tool_result(_resultado("consultar_medida", {
        "grupo": "Alfa", "medida": -49.3, "volume": 2009}))
    assert "consultar_medida" in saida
    assert "-49.3" in saida and "2009" in saida and "Alfa" in saida
    assert len(saida) < 400


def test_resumo_encolhe_de_verdade():
    bruto = _resultado("executar_python", {"volume": 15000, "pct_backlog": 33.6})
    assert len(summarize_tool_result(bruto)) < len(bruto) / 5


def test_resultado_recente_fica_intacto():
    """E o dado com que o agente esta trabalhando agora."""
    hist = [{"role": "system", "content": _resultado("consultar_medida", {"medida": -31.2})}]
    assert _mgr().prune_tool_outputs(hist, proteger_ultimos=6) == hist


def test_resultado_antigo_vira_uma_linha():
    antigos = [{"role": "system", "content": _resultado("consultar_medida", {"medida": -30.0 - i})}
               for i in range(8)]
    saida = _mgr().prune_tool_outputs(antigos, proteger_ultimos=2)
    assert "resumido para poupar contexto" in saida[0]["content"]
    assert "resumido para poupar contexto" not in saida[-1]["content"]


def test_leitura_repetida_some_do_historico():
    """Mesma ferramenta, mesmo conteudo: a copia mais nova basta."""
    igual = _resultado("consultar_medida", {"medida": -31.2})
    hist = [{"role": "system", "content": igual} for _ in range(4)]
    saida = _mgr().prune_tool_outputs(hist, proteger_ultimos=1)
    assert len(saida) < len(hist)


def test_mensagem_que_nao_e_resultado_passa_intacta():
    hist = [
        {"role": "user", "content": "como esta o medida?"},
        {"role": "assistant", "content": "y" * 9000},
    ]
    assert _mgr().prune_tool_outputs(hist) == hist


def _conversa_com_turnos():
    """Historico com a forma real: pergunta -> resultado -> resposta."""
    grande = _resultado("consultar_medida", {"medida": -31.2, "volume": 5000})
    outro = _resultado("consultar_medida", {"grupo": "Alfa", "medida": -49.3})
    return [
        {"role": "user", "content": "como esta o medida?"},
        {"role": "system", "content": grande},
        {"role": "assistant", "content": "O Medida consolidado esta em -31,2."},
        {"role": "user", "content": "qual a causa raiz?"},
        {"role": "system", "content": outro},
        {"role": "assistant", "content": "A causa e o backlog no Alfa."},
        {"role": "user", "content": "e o que dizem por ai sobre isso?"},
    ]


def test_resultado_de_turno_fechado_encolhe_e_o_do_turno_fica():
    """O que o turno anterior ja respondeu nao precisa viajar inteiro de novo.

    Antes a protecao era por contagem (os 6 ultimos) mais um teto de tamanho:
    numa conversa comum isso protegia TODOS os resultados e a poda economizava
    exatamente zero. Este teste existe para essa regressao nao voltar calada.
    """
    historico = _conversa_com_turnos()
    antes = sum(len(m["content"]) for m in historico)
    saida = _mgr().prune_tool_outputs(historico, proteger_ultimos=1)
    depois = sum(len(m["content"]) for m in saida)

    assert depois < antes, "a poda nao economizou nada"
    # O primeiro resultado ja foi respondido: vira resumo.
    assert "resumido para poupar contexto" in saida[1]["content"]
    # O ultimo continua inteiro: e o dado com que ele acabou de trabalhar.
    assert "resumido para poupar contexto" not in saida[4]["content"]
    # Pergunta e resposta nao sao tocadas.
    assert saida[0]["content"] == "como esta o medida?"
    assert saida[2]["content"].startswith("O Medida consolidado")


def test_resumo_guarda_o_id_para_o_detalhe_poder_voltar():
    """Sem o ID, o resumo vira dado sem procedencia e o detalhe some pra sempre."""
    from sentury.harness.context_budget import summarize_tool_result

    bruto = (
        "ID DO RESULTADO NA SESSÃO: 'resultado_004'\n"
        + _resultado("consultar_medida", {"grupo": "Alfa", "medida": -49.3})
    )
    resumo = summarize_tool_result(bruto)
    assert "resultado_004" in resumo
    assert "-49.3" in resumo and "Alfa" in resumo


def test_resumo_nao_carrega_embrulho_do_pandas():
    from sentury.harness.context_budget import summarize_tool_result

    resumo = summarize_tool_result(
        'RESULTADO DA FERRAMENTA "consultar_medida" (ja executada): '
        "{'medida': np.float64(-31.2), 'volume': 5000}"
    )
    assert "medida=-31.2" in resumo and "np.float64" not in resumo


def test_historico_sem_pergunta_ainda_poda():
    """Se a pergunta ja saiu numa compactacao anterior, nao ha turno corrente
    para proteger: e proteger tudo seria voltar a economizar nada."""
    so_resultados = [
        {"role": "system", "content": _resultado("consultar_medida", {"medida": -30.0 - i})}
        for i in range(5)
    ]
    saida = _mgr().prune_tool_outputs(so_resultados, proteger_ultimos=1)
    assert any("resumido para poupar contexto" in m["content"] for m in saida)


def test_prefixo_do_planner_vem_antes_do_que_muda(setor_teste):
    """O que é igual em todo turno vai no prefixo estável; o que muda vai no
    contexto do turno. O provedor só desconta o prefixo idêntico caractere a
    caractere: o índice de skills e o contrato de artefato não mudam com o
    pedido, o modo muda."""
    from sentury.harness.chamada_da_volta import contexto_do_turno, prompt_estavel
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState
    from tests.test_orchestrator import CapturePlanner, CaptureResponder, _store

    orq = SenturyOrchestrator(planner=CapturePlanner("{}"), responder=CaptureResponder(), store=_store())
    estavel = prompt_estavel(orq, nativo=True, manifesto=None)
    turno = contexto_do_turno(orq, AnalysisState.new("prefixo", "u"), "oi", nativo=True, modo="action_plan",
                              descoberta=None, contexto_adicional=None, rag_context="", is_replanning=False)
    assert "Catálogo de Skills Procedurais" in estavel, "o índice de skills saiu do prefixo"
    assert "mode: action_plan" in turno and "mode:" not in estavel, "o modo, que muda com o pedido, entrou no prefixo"
    assert "Hoje é" in turno and "Hoje é" not in estavel, "a data entrou no prefixo"


def test_uso_do_turno_conta_o_que_veio_do_cache():
    """Sem esse numero nao da pra saber se a mesma entrada custou 10% ou 100%."""
    from robinbandit.chain import _somar, _USO_DO_TURNO, iniciar_contagem

    iniciar_contagem()
    _somar({"entrada": 21112, "saida": 675, "total": 22894, "cacheado": 19000})
    _somar({"entrada": 300, "saida": 40, "total": 340})
    from robinbandit.chain import contagem_do_turno

    uso = contagem_do_turno()
    assert uso["cacheado"] == 19000
    assert uso["entrada"] == 21412 and uso["chamadas"] == 2

    # Sem nenhum acerto o campo some, para nao passar por medida o que e
    # so ausencia de informacao do provedor.
    iniciar_contagem()
    _somar({"entrada": 10, "saida": 5, "total": 15})
    assert "cacheado" not in contagem_do_turno()


def test_gemini_traduz_o_token_cacheado():
    from robinbandit.gemini_provider import _usage_gemini

    com = _usage_gemini({"usageMetadata": {
        "promptTokenCount": 21112, "candidatesTokenCount": 675,
        "totalTokenCount": 22894, "cachedContentTokenCount": 19000,
    }})
    assert com["cacheado"] == 19000
    # Sem cache hit o campo nem aparece: evita mostrar "0 do cache" como se
    # fosse medida quando o provedor simplesmente nao informou.
    sem = _usage_gemini({"usageMetadata": {
        "promptTokenCount": 500, "candidatesTokenCount": 50, "totalTokenCount": 550,
    }})
    assert "cacheado" not in sem


def test_cada_provedor_relata_cache_do_seu_jeito():
    """Tres nomes diferentes para a mesma coisa, um formato so na saida.

    Nem todo modelo tem cache de prefixo. O que nao pode e um turno barato e
    um caro parecerem iguais so porque o provedor usa outro nome de campo.
    """
    from robinbandit.claude_provider import _usage_anthropic
    from robinbandit.openai_compat import _normalizar_usage as formato_openai
    from robinbandit.groq_provider import _normalizar_usage as formato_groq

    # Anthropic reparte a entrada: `input_tokens` NAO inclui o que veio do
    # cache, entao somar as partes e o que torna o numero comparavel.
    anthropic = _usage_anthropic({
        "input_tokens": 1200, "cache_read_input_tokens": 19000,
        "cache_creation_input_tokens": 0, "output_tokens": 675,
    })
    assert anthropic == {"entrada": 20200, "saida": 675, "total": 20875, "cacheado": 19000}

    openai = formato_openai({
        "prompt_tokens": 21112, "completion_tokens": 675, "total_tokens": 21787,
        "prompt_tokens_details": {"cached_tokens": 19000},
    })
    assert openai["cacheado"] == 19000 and openai["entrada"] == 21112

    # Provedor sem cache nao ganha campo zerado: ausencia de informacao nao
    # deve passar por medida.
    for sem in (formato_openai({"prompt_tokens": 500, "completion_tokens": 50, "total_tokens": 550}),
                formato_groq({"prompt_tokens": 800, "completion_tokens": 40, "total_tokens": 840})):
        assert "cacheado" not in sem


def test_resumo_vale_para_qualquer_ferramenta():
    """A lista de campos era a de CX; resultado de outra coisa virava
    'resultado obtido' e perdia tudo."""
    bruto = _resultado("listar_arquivos", {"pasta": "C:/dados", "total": 42, "ocultos": False})
    resumo = summarize_tool_result(bruto)
    assert "pasta=C:/dados" in resumo and "total=42" in resumo and "ocultos=False" in resumo
    assert "_dump" not in resumo


def test_resumo_entende_json():
    resumo = summarize_tool_result('RESULTADO DA FERRAMENTA "ler_pagina": {"titulo": "Vagas", "links": 18}')
    assert "titulo=Vagas" in resumo and "links=18" in resumo


def test_resumo_de_resultado_grande_guarda_onde_esta_o_texto_inteiro(tmp_path, monkeypatch):
    """O resultado grande vai inteiro para o rascunho. Quando ele vira resumo no
    turno seguinte, o caminho fica: é a saída para rever o detalhe sem rodar a
    ferramenta de novo. O teste monta o resultado pelo mesmo caminho do turno,
    então uma mudança no aviso do rascunho aparece aqui."""
    from pathlib import Path

    from sentury.llm.prompts import build_tool_result_instruction

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    grande = {"caminho": "C:/x/grande.log", "conteudo": "linha de log\n" * 2000}
    resumo = summarize_tool_result(build_tool_result_instruction("ler_arquivo", grande, sessao="s1"))
    assert "caminho=C:/x/grande.log" in resumo
    caminho = resumo.split("continua em `", 1)[1].split("`", 1)[0]
    assert Path(caminho).is_file()
    assert "linha de log" in Path(caminho).read_text(encoding="utf-8")


def test_resultado_marcado_fica_inteiro_em_turno_antigo():
    """A resposta de um colega é o material que o coordenador junta no fim: ela
    não vira resumo quando outro colega responde depois e o turno recomeça."""
    from sentury.harness.context_budget import MANTER_INTEIRO

    colega = {"role": "system", "content": 'RESULTADO DA FERRAMENTA "pedir_ao_agente" (já executada):\n'
                                           "Nina respondeu:\n| Notebook | 5 | R$ 4.200,00 |",
              MANTER_INTEIRO: True}
    hist = [{"role": "user", "content": "monte o plano"}, colega,
            {"role": "user", "content": "Tito respondeu, continue"},
            {"role": "system", "content": _resultado("consultar_medida", {"medida": -31.2})},
            {"role": "user", "content": "Vera respondeu, continue"}]
    saida = _mgr().prune_tool_outputs(hist, proteger_ultimos=0)
    assert saida[1] == colega
    assert "resumido para poupar contexto" in saida[3]["content"]
