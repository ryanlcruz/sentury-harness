"""A conversa chega ao modelo como conversa, não como resumo reescrito."""
from sentury.harness.conversa import montar

SISTEMA = "Você é o Sentury."


def _historico():
    return [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "Oi! Em que posso ajudar?"},
        # deste turno: a pergunta ainda nao entrou no historico
        {"role": "system", "content": 'RESULTADO DA FERRAMENTA "listar_arquivos": pyproject.toml'},
    ]


def test_a_pergunta_fica_antes_do_que_ela_provocou():
    msgs = montar(SISTEMA, _historico(), "o que tem na pasta?")
    texto = [m["content"] for m in msgs]
    i_pergunta = next(i for i, t in enumerate(texto) if "o que tem na pasta?" in t)
    i_resultado = next(i for i, t in enumerate(texto) if "pyproject.toml" in t)
    assert i_pergunta <= i_resultado
    assert texto[1] == "oi" and texto[2] == "Oi! Em que posso ajudar?"
    assert not any("Solicitação:" in t for t in texto)


def test_mensagens_seguidas_da_pessoa_nao_somem():
    historico = [{"role": "user", "content": "primeiro pedido"}, {"role": "user", "content": "e mais isto"}]
    msgs = montar(SISTEMA, historico, "terceiro")
    corpo = "\n".join(m["content"] for m in msgs)
    assert "primeiro pedido" in corpo and "e mais isto" in corpo and "terceiro" in corpo


def test_o_contexto_do_turno_vai_no_fim_e_o_sistema_nao_muda():
    a = montar(SISTEMA, _historico(), "p", contexto_do_turno="Hoje e 2026-09-24")
    b = montar(SISTEMA, _historico(), "p", contexto_do_turno="Hoje e 2026-09-25")
    assert a[0] == b[0] == {"role": "system", "content": SISTEMA}
    assert "2026-09-24" in a[-1]["content"] and "não é mensagem da pessoa" in a[-1]["content"]


def test_papeis_alternam_e_a_primeira_fala_e_da_pessoa():
    historico = [{"role": "assistant", "content": "Bem-vindo."}, {"role": "system", "content": "aviso"}]
    msgs = montar(SISTEMA, historico, "p")
    papeis = [m["role"] for m in msgs]
    assert papeis[1] == "user"
    assert all(papeis[i] != papeis[i + 1] for i in range(1, len(papeis) - 1))


def test_pergunta_que_ja_esta_no_turno_nao_duplica():
    historico = [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "de novo"}]
    corpo = "\n".join(m["content"] for m in montar(SISTEMA, historico, "de novo"))
    assert corpo.count("de novo") == 1


def _com_chamada():
    from sentury.harness.conversa import marcar_chamada

    resultado = marcar_chamada({"role": "system", "content": 'RESULTADO DA FERRAMENTA "listar_arquivos": a.py'},
                               {"tool": "listar_arquivos", "id": "call_1"}, "listar_arquivos", {"caminho": "."})
    return [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "Oi!"}, resultado]


def test_resultado_vira_par_chamada_e_resposta_tool_como_nas_referencias():
    msgs = montar(SISTEMA, _com_chamada(), "o que tem na pasta?", nativo=True)
    chamada = next(m for m in msgs if m.get("tool_calls"))
    resposta = next(m for m in msgs if m["role"] == "tool")
    assert chamada["role"] == "assistant"
    assert chamada["tool_calls"][0]["function"]["name"] == "listar_arquivos"
    assert resposta["tool_call_id"] == chamada["tool_calls"][0]["id"] == "call_1"
    assert msgs.index(chamada) + 1 == msgs.index(resposta)


def test_sem_nativo_o_resultado_continua_texto():
    msgs = montar(SISTEMA, _com_chamada(), "o que tem na pasta?")
    assert not any(m.get("tool_calls") or m["role"] == "tool" for m in msgs)
    assert any("a.py" in m["content"] for m in msgs)


def test_gemini_e_claude_recebem_o_par_como_texto_sem_mensagem_vazia():
    from robinbandit.providers import claude_provider, gemini_provider

    msgs = montar(SISTEMA, _com_chamada(), "o que tem na pasta?", nativo=True)
    _, gemini = gemini_provider._split_messages(msgs)
    _, claude = claude_provider._split_messages(msgs)
    for convertidas, campo in ((gemini, "parts"), (claude, "content")):
        assert all(m[campo] for m in convertidas)
        papeis = [m["role"] for m in convertidas]
        assert all(papeis[i] != papeis[i + 1] for i in range(len(papeis) - 1))
    assert "chamei listar_arquivos" in str(claude)


def test_claude_code_recebe_a_chamada_e_o_resultado_em_texto():
    """O Dedicado cai no Claude Code quando o Codex esta fora; o CLI nao tem
    papel de ferramenta, e a chamada com conteudo vazio sumia do prompt."""
    from robinbandit.providers.claude_code_provider import _texto_das_mensagens

    _, dialogo = _texto_das_mensagens(montar(SISTEMA, _com_chamada(), "o que tem na pasta?", nativo=True))
    # A chamada vai no mesmo bloco que a instrução pede, não em prosa que o modelo imitaria.
    assert '"tool_calls": [{"name": "listar_arquivos"' in dialogo and "(chamei" not in dialogo
    assert "Resultado da ferramenta:" in dialogo and "a.py" in dialogo
    assert dialogo.index('"name": "listar_arquivos"') < dialogo.index("Resultado da ferramenta:")


def test_orientacao_no_meio_do_turno_chega_como_fala_da_pessoa():
    """Papel de usuario, com o texto dela, e nao um aviso de sistema que a
    saida de um `cat` conseguiria imitar."""
    from sentury.harness.caixa_do_turno import MARCA, mensagem

    orientacao = {"role": "system", "content": mensagem("use so as vagas remotas"), MARCA: "use so as vagas remotas"}
    msgs = montar(SISTEMA, _com_chamada() + [orientacao], "procure vagas", nativo=True)
    assert msgs[-1] == {"role": "user", "content": "use so as vagas remotas"}
    assert not any("INSTRUÇÃO DO SISTEMA" in str(m.get("content")) for m in msgs)


def test_a_imagem_anexada_chega_ao_modelo_e_o_router_pede_quem_enxerga():
    """A pergunta é remontada do texto; a imagem mora na mensagem do turno no
    histórico. Sem trazê-la, o modelo não via a imagem e o Router não pedia
    visão."""
    from robinbandit.routing.chain import ChainProvider

    imagem = {"nome": "foto.png", "data_url": "data:image/png;base64,AAAA"}
    historico = [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "Oi!"},
        {"role": "user", "content": "o que tem nesta foto?", "imagens": [imagem]},
        {"role": "system", "content": 'RESULTADO DA FERRAMENTA "memoria": nada'},
    ]
    msgs = montar(SISTEMA, historico, "o que tem nesta foto?", "contexto do turno", nativo=True)
    com_imagem = [m for m in msgs if m.get("imagens")]
    assert len(com_imagem) == 1 and com_imagem[0]["imagens"] == [imagem]
    assert "o que tem nesta foto?" in com_imagem[0]["content"]
    assert ChainProvider.exigencias(msgs) == {"vision"}
