"""A Mesa: assuntos, vez de falar, limites do código e fechamento com resumo."""
import asyncio
import time

import pytest

from sentury.residentes import escopo, hq, identidade, mesa, registro, tarefas, worker

ATLAS = {"nome": "atlas", "papel": "planejador", "objetivo": "organizar o trabalho",
         "ferramentas": ["ler_arquivo"]}
IRIS = {"nome": "iris", "papel": "analista", "objetivo": "conferir números", "ferramentas": ["ler_arquivo"]}
FORGE = {"nome": "forge", "papel": "construtor", "objetivo": "rodar scripts", "ferramentas": ["ler_arquivo"]}


@pytest.fixture(autouse=True)
def casa_limpa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    worker.configurar(None)
    mesa.configurar(None)
    yield
    worker.configurar(None)
    mesa.configurar(None)


def _turnos(roteiro):
    """Cada residente tem a lista das falas dele; um passo é o argumento do
    `falar_na_mesa`, ou um texto solto (a resposta final sem a ferramenta)."""
    from sentury.harness.state import AnalysisState
    from sentury.residentes.ferramentas import executar

    vistos = []

    async def rodar(agente, tarefa):
        vistos.append((agente.nome, tarefa.pedido))
        passo = roteiro[agente.nome].pop(0)
        if isinstance(passo, str):
            return {"message": passo}
        state = AnalysisState(session_id=hq.sessao_do(agente.nome), user_id="hq")
        with escopo.vestido(agente, tarefa):
            r = await executar("falar_na_mesa", passo, state)
        assert r["ok"], r
        return {"message": "falei"}

    return rodar, vistos


async def _esperar_fechar(assunto_id, prazo=400):
    for _ in range(prazo):
        assunto = mesa.carregar(assunto_id)
        if assunto.estado == mesa.FECHADO:
            return assunto
        await asyncio.sleep(0.01)
    raise AssertionError(f"o assunto não fechou: {mesa.carregar(assunto_id).publico()}")


async def _esperar_a_pessoa(assunto_id, prazo=400):
    """A rodada acabou num assunto da pessoa: ele segue aberto, esperando por ela."""
    for _ in range(prazo):
        assunto = mesa.carregar(assunto_id)
        if assunto.eventos and assunto.eventos[-1].get("tipo") == "mesa_sua_vez":
            assert assunto.estado == mesa.ABERTO
            return assunto
        await asyncio.sleep(0.01)
    raise AssertionError(f"a rodada não acabou: {mesa.carregar(assunto_id).publico()}")


async def _pessoa_fecha(assunto_id):
    """A pessoa manda fechar sem resumo: quem coordenou escreve o resumo da conversa."""
    await _esperar_a_pessoa(assunto_id)
    hq.fechar_assunto(assunto_id)
    return await _esperar_fechar(assunto_id)


def test_conversa_inteira_ate_o_resumo_na_memoria():
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    rodar, vistos = _turnos({
        "atlas": [{"texto": "@iris as duas fontes dão preços diferentes"},
                  {"resumo": "fica a fonte B; Forge confere amanhã"}],
        "iris": [{"texto": "a fonte A está desatualizada desde agosto"}],
    })
    worker.configurar(rodar)
    avisadas = []
    worker.observar(avisadas.append)

    async def cenario():
        aberto = hq.abrir_assunto("qual fonte de preço usar?", texto="@atlas @iris decidam")
        assert aberto["participantes"] == ["atlas", "iris"]
        return await _esperar_fechar(aberto["id"])

    fechado = asyncio.run(cenario())
    assert [f["de"] for f in fechado.falas] == ["atlas", "iris"]
    assert fechado.falas[0]["para"] == "iris"
    assert fechado.resumo == "fica a fonte B; Forge confere amanhã"
    assert "fica a fonte B" in registro.ler_memoria("iris")
    assert "Assunto na Mesa: qual fonte de preço usar?" in vistos[0][1]
    assert avisadas == []  # a pessoa lê a Mesa; não recebe aviso de cada fala
    tipos = [e["tipo"] for e in hq.eventos()]
    assert {"mesa_aberta", "mesa_fala", "mesa_fechada"} <= set(tipos)


def test_resposta_sem_a_ferramenta_vira_fala_e_texto_vazio_passa():
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    rodar, _ = _turnos({"atlas": ["acho que a B", "B, por consenso"], "iris": [""]})
    worker.configurar(rodar)

    async def cenario():
        aberto = hq.abrir_assunto("fonte?", texto="@atlas @iris")
        return await _pessoa_fecha(aberto["id"])

    fechado = asyncio.run(cenario())
    assert [f["texto"] for f in fechado.falas] == ["acho que a B"]
    assert fechado.resumo == "B, por consenso"


def test_teto_de_falas_e_chamado_com_arroba_ganha_mais_uma():
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    assunto = mesa.abrir("tema", "pessoa", "@atlas @iris")
    for i in range(3):
        mesa.falar(assunto.id, "atlas", f"fala {i}")
    with pytest.raises(mesa.AssuntoInvalido):
        mesa.falar(assunto.id, "atlas", "quarta")
    mesa.falar(assunto.id, "iris", "@atlas e o prazo?")
    assert mesa.proximo(mesa.carregar(assunto.id)) == "atlas"
    mesa.falar(assunto.id, "atlas", "sexta-feira")



def test_a_pessoa_fala_fora_da_conta_e_reabre_a_rodada():
    """A fala da pessoa não gasta vez de ninguém nem a põe entre os participantes.
    Ela abre uma rodada nova: sem @ a mesa toda é chamada, com @ só quem ela citou."""
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    assunto = mesa.abrir("tema", "pessoa", "@atlas @iris")
    for i in range(3):
        mesa.falar(assunto.id, "atlas", f"fala {i}")
        mesa.falar(assunto.id, "iris", f"resposta {i}")
    mesa.marcar_fechando(assunto.id)
    assert mesa.proximo(mesa.carregar(assunto.id)) is None

    reaberto = mesa.falar(assunto.id, mesa.PESSOA, "e o custo, alguém olhou?")
    assert reaberto.participantes == ["atlas", "iris"] and not reaberto.fechando
    assert reaberto.chamados == ["atlas", "iris"] and mesa.proximo(reaberto) == "atlas"
    mesa.falar(assunto.id, "atlas", "olhei, cabe")
    mesa.falar(assunto.id, "iris", "confere")

    so_um = mesa.falar(assunto.id, mesa.PESSOA, "@iris e o prazo?")
    assert so_um.chamados == ["iris"] and mesa.proximo(so_um) == "iris"

def test_pingue_pongue_fecha_quando_dois_monopolizam():
    for dados in (ATLAS, IRIS, FORGE):
        registro.criar(dados)
    assunto = mesa.abrir("tema", "pessoa", "@atlas @iris @forge")
    for i in range(mesa.PINGUE_PONGUE):
        mesa.falar(assunto.id, ("atlas", "iris")[i % 2], f"concordo {i}")
    aberto = mesa.carregar(assunto.id)
    assert aberto.motivo and mesa.proximo(aberto) is None


def test_com_dois_so_o_teto_limita_e_nao_ha_pingue_pongue():
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    assunto = mesa.abrir("tema", "pessoa", "@atlas @iris")
    for i in range(mesa.PINGUE_PONGUE):
        mesa.falar(assunto.id, ("atlas", "iris")[i % 2], f"fato novo {i}")
    aberto = mesa.carregar(assunto.id)
    assert not aberto.motivo and mesa.proximo(aberto) is None


def test_uma_acao_por_vez():
    from sentury.harness.state import AnalysisState
    from sentury.residentes.ferramentas import executar

    atlas = registro.criar(ATLAS)
    registro.criar(IRIS)
    assunto = mesa.abrir("tema", "pessoa", "@atlas @iris")
    vez = tarefas.enfileirar("atlas", "fale", f"{mesa.ORIGEM}{assunto.id}")
    state = AnalysisState(session_id=hq.sessao_do("atlas"), user_id="hq")
    with escopo.vestido(atlas, vez):
        assert asyncio.run(executar("falar_na_mesa", {"texto": "minha parte"}, state))["ok"]
        segunda = asyncio.run(executar("falar_na_mesa", {"passar": True}, state))
    assert not segunda["ok"] and "termine o turno" in segunda["erro"]


def test_quem_entra_pela_decisao_barata():
    """Sem @ na abertura, cada residente decide se o assunto é dele."""
    for dados in (ATLAS, IRIS, FORGE):
        registro.criar(dados)

    async def decidir(agente, assunto):
        return agente.nome == "forge"

    mesa.configurar(decidir)
    assunto = mesa.abrir("o script de backup quebrou", "pessoa", "alguém veja")
    convidado = asyncio.run(mesa.convidar(assunto.id))
    assert convidado.participantes == ["forge"]


def test_quem_ficou_de_fora_aparece_e_volta_com_arroba():
    """Quem decidiu não entrar fica registrado no assunto, para a tela dizer quem não veio,
    e sai da lista quando a pessoa o chama depois."""
    for dados in (ATLAS, IRIS, FORGE):
        registro.criar(dados)

    async def decidir(agente, assunto):
        return agente.nome != "iris"

    mesa.configurar(decidir)
    assunto = mesa.abrir("apresentação", "pessoa", "pessoal, cada um se apresente")
    convidado = asyncio.run(mesa.convidar(assunto.id))
    assert convidado.ficaram_de_fora == ["iris"]
    assert [e["agente"] for e in convidado.eventos if e["tipo"] == "mesa_ficou_de_fora"] == ["iris"]
    depois = mesa.falar(assunto.id, mesa.PESSOA, "@iris você também")
    assert "iris" in depois.participantes and depois.ficaram_de_fora == []


def test_as_decisoes_de_entrar_correm_juntas_e_a_ordem_e_a_dos_residentes():
    """Cada decisão é uma chamada ao modelo; em fila elas somavam segundos antes da primeira
    fala. Quem responde primeiro não fura a ordem em que os residentes falam."""
    for dados in (ATLAS, IRIS, FORGE):
        registro.criar(dados)
    espera = {"atlas": 0.3, "iris": 0.2, "forge": 0.1}

    async def decidir(agente, assunto):
        await asyncio.sleep(espera[agente.nome])
        return True

    mesa.configurar(decidir)
    assunto = mesa.abrir("apresentação", "pessoa", "pessoal, cada um se apresente")
    inicio = time.monotonic()
    convidado = asyncio.run(mesa.convidar(assunto.id))
    assert time.monotonic() - inicio < 0.5
    assert convidado.participantes == ["atlas", "iris", "forge"]


def test_a_vez_diz_desde_quando_esta_rodando():
    """A tela mostra há quanto tempo o residente está com a vez."""
    registro.criar(ATLAS)
    assunto = mesa.abrir("teste", "pessoa", "@atlas fala")
    vez = tarefas.enfileirar("atlas", "sua vez", origem=f"mesa:{assunto.id}")
    tarefas.comecar(vez.id)
    linha = hq._vezes()[assunto.id][0]
    assert linha["estado"] == tarefas.RODANDO and abs(linha["desde"] - time.time()) < 5


def test_vez_esperando_autorizacao_leva_a_tarefa():
    """Residente que parou pedindo autorização na Mesa: a vez leva a tarefa, para a
    tela mostrar o cartão ali na conversa, e não só na aba da HQ."""
    registro.criar(ATLAS)
    assunto = mesa.abrir("teste", "pessoa", "@atlas limpa os logs antigos")
    vez = tarefas.enfileirar("atlas", "sua vez", origem=f"mesa:{assunto.id}")
    tarefas.comecar(vez.id)
    tarefas.esperar(vez.id, "precisa da sua autorização: rm -r logs", pendente="rm -r logs")
    linha = hq._vezes()[assunto.id][0]
    assert linha["estado"] == tarefas.ESPERANDO and linha["tarefa"] == vez.id
    assert any(t["id"] == vez.id and t["pendente"] == "rm -r logs" for t in hq.esperando())


def test_arroba_na_abertura_limita_quem_entra():
    """Com @, quem abriu já escolheu: os outros não são consultados e só entram
    se alguém os chamar numa fala."""
    for dados in (ATLAS, IRIS, FORGE):
        registro.criar(dados)
    consultados = []

    async def decidir(agente, assunto):
        consultados.append(agente.nome)
        return True

    mesa.configurar(decidir)
    assunto = mesa.abrir("o script de backup quebrou", "pessoa", "@atlas veja")
    convidado = asyncio.run(mesa.convidar(assunto.id))
    assert convidado.participantes == ["atlas"] and consultados == []
    depois = mesa.falar(assunto.id, mesa.PESSOA, "@forge você também")
    assert depois.participantes == ["atlas", "forge"]


def test_falar_na_mesa_fora_da_vez_explica_a_saida():
    from sentury.harness.state import AnalysisState
    from sentury.residentes.ferramentas import executar

    atlas = registro.criar(ATLAS)
    state = AnalysisState(session_id=hq.sessao_do("atlas"), user_id="hq")
    with escopo.vestido(atlas, tarefas.enfileirar("atlas", "outra coisa")):
        r = asyncio.run(executar("falar_na_mesa", {"texto": "oi"}, state))
    assert not r["ok"] and "abrir_assunto" in r["erro"]


def test_mesa_pelo_telegram_abre_e_o_resumo_volta_ao_chat():
    from sentury.residentes import telegram as tg

    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    assert tg.ler_assunto("/mesa") == ("", "")
    assert tg.ler_assunto("oi") is None
    titulo, texto = tg.ler_assunto("/mesa qual fonte de preço?\n@atlas @iris decidam")
    assert (titulo, texto) == ("qual fonte de preço?", "@atlas @iris decidam")

    resposta = asyncio.run(tg.abrir_na_mesa(555, titulo, texto))
    assert "Abri na Mesa" in resposta and "Atlas" in resposta and "Iris" in resposta
    assunto = mesa.listar()[0]
    assert assunto.canal == "telegram:555"
    assert "Escreva o assunto" in asyncio.run(tg.abrir_na_mesa(555, "", ""))

    avisos = []
    mesa.ao_fechar(lambda a: avisos.append(tg.aviso_de_fechamento(a)))
    try:
        mesa.falar(assunto.id, "atlas", "fica a B")
        mesa.fechar(assunto.id, "fica a fonte B", por="atlas")
    finally:
        mesa._AO_FECHAR.clear()
    chat, texto_do_aviso = avisos[0]
    assert chat == 555 and "fica a fonte B" in texto_do_aviso and "Atlas" in texto_do_aviso


def test_autonomia_do_manifesto_limita_iniciativas_e_falas():
    from sentury.residentes import manifesto as _m

    with pytest.raises(_m.ManifestoInvalido):
        _m.validar({**ATLAS, "autonomia": {"iniciativas_por_dia": 99}})
    with pytest.raises(_m.ManifestoInvalido):
        _m.validar({**ATLAS, "autonomia": {"voar": 1}})
    registro.criar({**ATLAS, "autonomia": {"iniciativas_por_dia": 1, "falas_por_assunto": 1}})
    registro.criar(IRIS)

    primeiro = hq.abrir_assunto("o backup", "atlas", "@iris olha o log")
    assert next(e for e in hq.eventos() if e["tipo"] == "mesa_aberta")["iniciativa"] is True
    with pytest.raises(mesa.AssuntoInvalido, match="teto de iniciativas"):
        hq.abrir_assunto("outro", "atlas")
    # A fala com que ele abriu já gastou o teto dele; a Iris segue com 3.
    assunto = mesa.carregar(primeiro["id"])
    assert not mesa.pode_falar(assunto, "atlas") and mesa.pode_falar(assunto, "iris")


def test_autonomia_se_edita_pela_ficha():
    from sentury.residentes import manifesto as _m

    registro.criar(ATLAS)
    editado = registro.editar("atlas", {"autonomia": {"iniciativas_por_dia": 0, "falas_por_assunto": 5}})
    assert editado.autonomia == {"iniciativas_por_dia": 0, "falas_por_assunto": 5}
    with pytest.raises(_m.ManifestoInvalido):
        registro.editar("atlas", {"autonomia": {"falas_por_assunto": -1}})
    with pytest.raises(mesa.AssuntoInvalido, match="teto de iniciativas"):
        hq.abrir_assunto("qualquer coisa", "atlas")


def test_a_pessoa_retoma_um_assunto_fechado_falando_nele():
    """A conversa continua na Mesa depois do resumo: a fala da pessoa reabre o
    assunto e chama a mesa de novo, sem precisar ir ao chat de cada residente."""
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    assunto = mesa.abrir("tema", "pessoa", "@atlas @iris")
    mesa.falar(assunto.id, "atlas", "proposta")
    mesa.fechar(assunto.id, "fechamos na proposta", por="atlas")

    retomado = mesa.falar(assunto.id, mesa.PESSOA, "e se o prazo cair pela metade?")
    assert retomado.estado == mesa.ABERTO and retomado.resumo == ""
    # A Íris ainda não tinha falado: ela vem antes do Atlas, que já falou uma vez.
    assert set(retomado.chamados) == {"atlas", "iris"} and mesa.proximo(retomado) == "iris"
    assert "mesa_reaberta" in [e["tipo"] for e in retomado.eventos]
    mesa.fechar(assunto.id, "de novo", por="atlas")
    with pytest.raises(mesa.AssuntoInvalido):
        mesa.falar(assunto.id, "atlas", "residente não reabre o que fechou")


def test_cada_um_fala_uma_vez_e_a_replica_vem_de_quem_foi_chamado():
    """Cada um fala uma vez por rodada, em texto mesmo; ninguém ganha uma segunda vez
    para recapitular. Quem foi chamado com @ responde, e a resposta dele entra."""
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    rodar, vistos = _turnos({
        "atlas": ["proposta: fonte B", "a A atrasa em agosto, por isso a B", {"passar": True},
                  "fonte B, por consenso"],
        "iris": ["discordo, a A é mais barata, @atlas"],
    })
    worker.configurar(rodar)

    async def cenario():
        aberto = hq.abrir_assunto("fonte?", texto="@atlas @iris")
        return await _pessoa_fecha(aberto["id"])

    fechado = asyncio.run(cenario())
    assert [f["texto"] for f in fechado.falas] == [
        "proposta: fonte B", "discordo, a A é mais barata, @atlas", "a A atrasa em agosto, por isso a B"]
    assert fechado.resumo == "fonte B, por consenso" and len(vistos) == 5
    assert "Iris chamou você" in vistos[2][1]


def test_resumo_fora_da_vez_de_fechar_entra_como_fala():
    """Quem manda `resumo` sem ser a vez de fechar quis falar: vira a fala dele,
    em vez de um erro que custa mais uma volta."""
    from sentury.harness.state import AnalysisState
    from sentury.residentes.ferramentas import executar

    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    assunto = mesa.abrir("tema", "pessoa", "@atlas @iris")
    vez = tarefas.enfileirar("atlas", "É a sua vez", f"{mesa.ORIGEM}{assunto.id}")
    state = AnalysisState(session_id=hq.sessao_do("atlas"), user_id="hq")
    agente = registro.carregar("atlas")
    with escopo.vestido(agente, vez):
        r = asyncio.run(executar("falar_na_mesa", {"resumo": "fico com a fonte B"}, state))
    assert r["ok"] and [f["texto"] for f in mesa.carregar(assunto.id).falas] == ["fico com a fonte B"]


def test_assunto_aberto_por_residente_ainda_fecha_sozinho():
    """A reunião que um residente convocou é dele: acabada a rodada, ele fecha com o resumo."""
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    rodar, _ = _turnos({"atlas": [{"texto": "@iris proposta: B"}, {"resumo": "B"}], "iris": [{"passar": True}]})
    worker.configurar(rodar)

    async def cenario():
        assunto = mesa.abrir("fonte?", "atlas", "@iris")
        hq.dar_a_vez(assunto.id)
        return await _esperar_fechar(assunto.id)

    assert asyncio.run(cenario()).resumo == "B"


def test_resumo_velho_some_quando_a_pessoa_volta_a_falar():
    """A pessoa falou enquanto o resumo era escrito: a conversa seguiu, e o resumo
    que chega depois não entra como fala de ninguém."""
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    assunto = mesa.abrir("tema", "pessoa", "@atlas @iris")
    mesa.falar(assunto.id, "atlas", "acho que B")
    vez = tarefas.enfileirar("atlas", "feche", f"{mesa.ORIGEM}{assunto.id}")
    mesa.marcar_fechando(assunto.id, vez.id)
    mesa.falar(assunto.id, mesa.PESSOA, "espera, e a C?")
    vez.estado, vez.resposta = tarefas.FEITA, "Resumo: ficou a B"
    hq.depois_da_fala(vez)
    textos = [f["texto"] for f in mesa.carregar(assunto.id).falas]
    assert "Resumo: ficou a B" not in textos and mesa.carregar(assunto.id).estado == mesa.ABERTO


def test_apagar_assunto_leva_a_vez_pendente_e_a_decisao():
    from sentury.memory import decisoes

    registro.criar(ATLAS)
    assunto = mesa.abrir("tema", "pessoa", "@atlas")
    vez = tarefas.enfileirar("atlas", "É a sua vez", f"{mesa.ORIGEM}{assunto.id}")
    decisoes.registrar(f"{mesa.ORIGEM}{assunto.id}", "tema", "ficou a B", ["atlas"])
    assert hq.apagar_assunto(assunto.id)["ok"]
    assert mesa.carregar(assunto.id) is None
    assert tarefas.carregar(vez.id).estado == tarefas.CANCELADA
    assert decisoes.listar() == []
    with pytest.raises(hq.NaoEncontrado):
        hq.apagar_assunto(assunto.id)


def _sem_desde(vez):
    """A vez sem a hora de início e sem o id da tarefa, que mudam a cada execução e
    têm testes próprios (`test_a_vez_diz_desde_quando_esta_rodando` e
    `test_vez_esperando_autorizacao_leva_a_tarefa`)."""
    return [{k: v for k, v in item.items() if k not in ("desde", "tarefa")} for item in vez]


def test_lista_de_assuntos_diz_quem_esta_com_a_vez():
    """A tela distingue a fala que espera na fila da que já está sendo escrita."""
    registro.criar(ATLAS)
    assunto = mesa.abrir("tema", "pessoa", "@atlas")
    tarefas.enfileirar("atlas", "É a sua vez", f"{mesa.ORIGEM}{assunto.id}")
    achado = next(a for a in hq.assuntos() if a["id"] == assunto.id)
    assert _sem_desde(achado["vez"]) == [{"agente": "atlas", "estado": tarefas.NA_FILA, "papel": "falando"}]


def test_na_mesa_a_resposta_e_a_fala_e_nao_um_relatorio():
    """Fora da Mesa, a resposta relata a tarefa; na Mesa, ela é a fala, no jeito de cada um."""
    agente = registro.criar({**ATLAS, "personalidade": "Fala curto e brinca com números."})
    na_mesa = identidade.identidade(agente, na_mesa=True)
    fora = identidade.identidade(agente)
    assert "a sua resposta é a sua fala" in na_mesa and "o que foi feito" not in na_mesa
    assert "o que foi feito" in fora
    assert na_mesa.index("## Como você fala") < na_mesa.index("## Objetivo")


def test_vez_na_mesa_roda_em_sessao_propria_sem_historico():
    """A vez na Mesa começa limpa: o pedido traz a conversa do assunto, e o histórico do
    residente (com as voltas antigas) não entra para ser imitado. Tarefa comum segue na
    conversa dele."""
    assert hq.sessao_da_vez("atlas", f"{mesa.ORIGEM}m1") == ("agente:atlas:mesa", True)
    assert hq.sessao_da_vez("atlas", "tela") == ("agente:atlas", False)
    assert hq.sessao_da_vez("atlas") == ("agente:atlas", False)


def test_mediacao_sintetiza_a_divergencia_e_depois_fecha_o_acordo():
    """Ficou divergência: quem conduz propõe a síntese e chama quem discordou; aceito o
    ajuste, a mediação seguinte fecha com o resumo, que vira decisão registrada."""
    from sentury.memory import decisoes

    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    rodar, vistos = _turnos({
        "atlas": ["fonte B", "síntese: B, com a A de reserva. @iris topa?", {"resumo": "B, com A de reserva"}],
        "iris": ["discordo, a A é mais barata", "topo, com a A de reserva"],
    })
    worker.configurar(rodar)

    async def cenario():
        aberto = hq.abrir_assunto("fonte?", texto="@atlas @iris decidam")
        return await _esperar_fechar(aberto["id"])

    fechado = asyncio.run(cenario())
    assert [f["texto"] for f in fechado.falas] == [
        "fonte B", "discordo, a A é mais barata", "síntese: B, com a A de reserva. @iris topa?",
        "topo, com a A de reserva"]
    assert fechado.resumo == "B, com A de reserva"
    assert decisoes.listar()[0]["resumo"] == "B, com A de reserva"
    assert "A rodada acabou e você conduz esta mesa" in vistos[2][1]
    assert "A rodada acabou e você conduz esta mesa" in vistos[4][1]


def test_mediacao_que_passa_devolve_a_vez_sem_insistir():
    """Conversa sem decisão a tomar: quem conduz passa, e a vez volta para a pessoa sem
    outra mediação na mesma rodada."""
    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    rodar, vistos = _turnos({"atlas": ["sou o Atlas", {"passar": True}], "iris": ["sou a Iris"]})
    worker.configurar(rodar)

    async def cenario():
        aberto = hq.abrir_assunto("apresentação", texto="@atlas @iris se apresentem")
        return await _esperar_a_pessoa(aberto["id"])

    assunto = asyncio.run(cenario())
    assert [f["texto"] for f in assunto.falas] == ["sou o Atlas", "sou a Iris"] and len(vistos) == 3
    assert "A rodada acabou e você conduz esta mesa" in vistos[2][1]


def test_arroba_da_pessoa_limita_a_rodada_a_quem_ela_chamou():
    """Com @, responde quem foi chamado, e não a mesa toda; sem mediador para uma resposta só."""
    for dados in (ATLAS, IRIS, FORGE):
        registro.criar(dados)
    rodar, vistos = _turnos({"atlas": ["sou o Atlas"], "iris": ["sou a Iris"], "forge": ["sou o Forge", "eu, Forge"]})
    worker.configurar(rodar)

    async def cenario():
        aberto = hq.abrir_assunto("apresentação", texto="@atlas @iris @forge oi")
        await _esperar_a_pessoa(aberto["id"])
        hq.falar_na_mesa(aberto["id"], "@forge e você, faz o quê?")
        for _ in range(400):
            assunto = mesa.carregar(aberto["id"])
            if assunto.eventos[-1].get("tipo") == "mesa_sua_vez" and assunto.falas[-1]["de"] != mesa.PESSOA:
                return assunto
            await asyncio.sleep(0.01)
        raise AssertionError(mesa.carregar(aberto["id"]).publico())

    assunto = asyncio.run(cenario())
    depois = assunto.falas[[f["de"] for f in assunto.falas].index(mesa.PESSOA) + 1:]
    assert [f["de"] for f in depois] == ["forge"]


def test_quem_estourou_o_orcamento_passa_a_vez_e_a_mesa_segue(monkeypatch):
    """Sem turnos hoje, o residente não trava a conversa: a vez passa com o motivo
    e os outros continuam."""
    registro.criar(ATLAS)
    registro.criar(IRIS)
    monkeypatch.setattr(worker._orcamento, "corte",
                        lambda agente: "os turnos de hoje acabaram (60 de 60)" if agente.nome == "atlas" else "")
    rodar, vistos = _turnos({"iris": ["sou a Iris"]})
    worker.configurar(rodar)

    async def cenario():
        aberto = hq.abrir_assunto("apresentação", texto="@atlas @iris se apresentem")
        return await _esperar_a_pessoa(aberto["id"])

    assunto = asyncio.run(cenario())
    assert [f["de"] for f in assunto.falas] == ["iris"]
    passou = [e for e in assunto.eventos if e["tipo"] == "mesa_passou" and e["agente"] == "atlas"]
    assert passou and "turnos" in passou[0]["motivo"]


def test_quem_ja_falou_nesta_vez_sai_do_digitando():
    """A fala entra antes de o turno terminar: quem já falou não aparece mais escrevendo,
    e a tela não mostra o mesmo residente digitando de novo antes de passar ao próximo."""
    registro.criar(ATLAS)
    assunto = mesa.abrir("tema", "pessoa", "@atlas")
    vez = tarefas.enfileirar("atlas", "É a sua vez", f"{mesa.ORIGEM}{assunto.id}")
    tarefas.comecar(vez.id)
    achado = next(a for a in hq.assuntos() if a["id"] == assunto.id)
    assert _sem_desde(achado["vez"]) == [{"agente": "atlas", "estado": tarefas.RODANDO, "papel": "falando"}]
    mesa.falar(assunto.id, "atlas", "acho que a B")
    achado = next(a for a in hq.assuntos() if a["id"] == assunto.id)
    assert achado["vez"] == []


def test_mediacao_encaminha_proximos_passos_sem_esperar_e_a_tela_os_mostra():
    """A mediação pede a cada dono o próximo passo e fecha na hora: a vez dela não espera os
    colegas. O assunto mostra quem media e o que saiu dele, com o estado de cada tarefa."""
    from types import SimpleNamespace

    from sentury.residentes import worker as _worker

    for dados in (ATLAS, IRIS):
        registro.criar(dados)
    assunto = mesa.abrir("tema", "pessoa", "@atlas @iris")
    vez = tarefas.enfileirar("atlas", "medie", f"{mesa.ORIGEM}{assunto.id}")
    mesa.marcar_mediando(assunto.id, "atlas", vez.id)
    achado = next(a for a in hq.assuntos() if a["id"] == assunto.id)
    assert achado["vez"][0]["papel"] == "mediando"
    tarefas.comecar(vez.id)
    passo = tarefas.enfileirar("iris", "levante os números", "agente:atlas", vez.id)
    fechada = _worker._fechar(tarefas.carregar(vez.id), {"message": "fechei"})
    assert fechada.estado == tarefas.FEITA and not fechada.aguardando
    achado = next(a for a in hq.assuntos() if a["id"] == assunto.id)
    assert [(s["id"], s["agente"], s["estado"]) for s in achado["encaminhadas"]] == [
        (passo.id, "iris", tarefas.NA_FILA)]
    assert achado["custo"]["vezes"] == 1


def test_a_rodada_responde_a_ultima_fala_da_pessoa():
    """Depois de um assunto fechado e reaberto, a vez destaca o que a pessoa acabou de dizer,
    para a rodada não continuar o consenso anterior."""
    registro.criar(ATLAS)
    assunto = mesa.abrir("tema", "pessoa", "@atlas")
    mesa.falar(assunto.id, "atlas", "fechamos na B")
    mesa.falar(assunto.id, mesa.PESSOA, "e alguém aqui já usou skill?")
    pedido = mesa.pedido_da_fala(mesa.carregar(assunto.id), "atlas")
    assert 'A pessoa acabou de dizer: "e alguém aqui já usou skill?"' in pedido
    assert pedido.index("A pessoa acabou de dizer") > pedido.index("fechamos na B")


def test_vez_que_falhou_passa_com_o_motivo_e_nao_vira_fala():
    """O provedor fora não fala por ninguém: a vez que falhou passa, com o motivo à vista."""
    registro.criar(ATLAS)
    assunto = mesa.abrir("tema", "pessoa", "@atlas")
    vez = tarefas.enfileirar("atlas", "É a sua vez", f"{mesa.ORIGEM}{assunto.id}")
    falhada = tarefas.carregar(vez.id)
    falhada.estado, falhada.motivo, falhada.resposta = tarefas.FALHOU, "nenhum provedor respondeu", ""
    hq.depois_da_fala(falhada)
    depois = mesa.carregar(assunto.id)
    assert depois.falas == []
    passou = [e for e in depois.eventos if e["tipo"] == "mesa_passou"]
    assert passou and passou[-1]["motivo"] == "nenhum provedor respondeu"


def test_vez_que_falha_passa_na_hora_sem_voltar_para_a_fila():
    """A tarefa comum tenta de novo; a vez na Mesa não, porque a conversa toda esperaria."""
    from sentury.residentes import worker as _worker

    registro.criar(ATLAS)
    assunto = mesa.abrir("tema", "pessoa", "@atlas")
    vez = tarefas.enfileirar("atlas", "É a sua vez", f"{mesa.ORIGEM}{assunto.id}")
    comum = tarefas.enfileirar("atlas", "olhe o disco")
    for tarefa in (vez, comum):
        tarefas.comecar(tarefa.id)
    falha = {"falhou": True, "erro": "nenhum provedor respondeu"}
    assert _worker._fechar(tarefas.carregar(vez.id), falha).estado == tarefas.FALHOU
    assert _worker._fechar(tarefas.carregar(comum.id), falha).estado == tarefas.NA_FILA


def test_fala_na_mesa_encerra_o_turno_sem_nova_chamada_ao_modelo():
    """Feita a fala, o turno acaba: devolver o resultado ao modelo custava uma chamada inteira
    só para ele narrar o que fez. A falha não encerra, para o modelo poder corrigir."""
    import asyncio as _asyncio

    from sentury.harness.anexo_do_resultado import anexo_do_resultado

    ok = {"ok": True, "resposta": "acho que a B", "proximo_passo": "termine o turno"}
    rumo, anexo, texto = _asyncio.run(anexo_do_resultado("falar_na_mesa", {}, ok, None, []))
    assert (rumo, anexo, texto) == ("encerrar", None, "acho que a B")
    falhou = {"ok": False, "erro": "você já falou nesta vez"}
    rumo, _, _ = _asyncio.run(anexo_do_resultado("falar_na_mesa", {}, falhou, None, []))
    assert rumo != "encerrar"
