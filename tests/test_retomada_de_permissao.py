"""Conceder a permissão tem que fazer a tarefa CONTINUAR, não recomeçar a conversa.

O que o benchmark pegou, em três turnos:

1. *"Dá uma olhada na pasta `…\\data`, me diz o que tem no banco e me entrega um
   `.md`"* → o agente propôs `listar_arquivos` no caminho certo e **parou**,
   pedindo autorização. Correto.
2. Permissão concedida, *"pode seguir"* → **"preciso saber qual ação você deseja
   que eu execute nela"**. O pedido original estava duas mensagens acima.
3. Repetindo o pedido à mão, ele seguiu.

Duas coisas faltavam. O `state` não guardava nada sobre a tarefa parada, e a
resposta do turno bloqueado não entrava no histórico: então a conversa ficava
com um buraco exatamente onde estaria o registro do que ficou pendente. A
retomada dependia de o modelo reler a primeira mensagem, e depender de o modelo
lembrar é o desenho que sempre perde.

E o texto não dizia o alvo: *"Parei aqui: `acessar_pasta` precisa da sua
autorização"*. `acessar_pasta` é nome interno de operação; o caminho ficava só no
`harness_reason`, que o chat não mostra.
"""
import pytest

from tests.fixtures.setor_teste.dados import StoreTeste
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.harness.pausa_do_turno import resultado_de_permissao

PASTA = r"C:\Users\alguem\Documentos\financeiro"
PEDIDO = "Abre o banco que está na pasta e me entrega um .md com as tabelas."


@pytest.fixture(autouse=True)
def _permissoes_isoladas(tmp_path, monkeypatch):
    from sentury.tools import permissoes

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.setattr(permissoes, "_DA_SESSAO", {})
    monkeypatch.setattr(permissoes, "_CREDITO_UNICO", {})


def _aprovar(alvo, sessao="s"):
    """O que o cartão faz antes da mensagem "pode seguir": grava a resposta."""
    from sentury.tools import permissoes

    permissoes.responder(alvo, "sessao", sessao)


class MockLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.last_model = "mock-model"

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return self.responses.pop(0) if self.responses else '{"action": "respond", "message": "ok"}'


def _orquestrador(planner_respostas=("",), responder_respostas=("ok",)):
    return SenturyOrchestrator(
        planner=MockLLM(planner_respostas),
        responder=MockLLM(responder_respostas),
        store=StoreTeste(),
        memory=None,
        skills=None,
    )


# ------------------------------------------------ o que o usuário lê

def test_o_texto_diz_qual_e_o_alvo():
    """Sem o alvo na frase, a pessoa aprova no escuro."""
    orq = _orquestrador()
    state = AnalysisState.new("s", "u")
    saida = resultado_de_permissao(orq,
        state, PEDIDO,
        {"chave": f"acessar_pasta {PASTA}", "comando": f"acessar_pasta {PASTA}",
         "motivo": "pasta fora da área liberada", "ferramenta": "listar_arquivos"},
        {}, {},
    )
    assert PASTA in saida["message"], saida["message"]


def test_sem_comando_o_texto_ainda_nomeia_algo():
    """O `comando` às vezes vem vazio; cair para a ferramenta é melhor que
    "Parei aqui: `` precisa da sua autorização"."""
    orq = _orquestrador()
    saida = resultado_de_permissao(orq,
        AnalysisState.new("s", "u"), PEDIDO,
        {"chave": "", "comando": "", "motivo": "", "ferramenta": "executar_comando"},
        {}, {},
    )
    assert "executar_comando" in saida["message"]


# ------------------------------------------------ o que fica guardado

def test_a_tarefa_parada_fica_no_state():
    orq = _orquestrador()
    state = AnalysisState.new("s", "u")
    resultado_de_permissao(orq,
        state, PEDIDO,
        {"chave": f"acessar_pasta {PASTA}", "comando": f"acessar_pasta {PASTA}",
         "motivo": "", "ferramenta": "listar_arquivos",
         "argumentos": {"caminho": PASTA}},
        {}, {},
    )
    pendente = state.tarefa_pendente
    assert pendente, "nada foi guardado: o próximo turno não tem o que retomar"
    assert pendente["pedido"] == PEDIDO
    assert pendente["ferramenta"] == "listar_arquivos"
    assert pendente["argumentos"] == {"caminho": PASTA}


def test_a_pendencia_atravessa_a_serializacao():
    """Ela é lida no turno SEGUINTE, então precisa sobreviver ao round-trip:
    o state vai para o Redis entre os dois."""
    state = AnalysisState.new("s", "u")
    state.tarefa_pendente = {"pedido": PEDIDO, "alvo": PASTA,
                             "ferramenta": "listar_arquivos", "argumentos": {}}
    de_volta = AnalysisState.from_dict(state.to_dict())
    assert de_volta.tarefa_pendente["pedido"] == PEDIDO


# ------------------------------------------------ o turno seguinte

@pytest.mark.asyncio
async def test_o_turno_seguinte_recebe_a_tarefa_de_volta():
    """Era aqui que o benchmark quebrava: "pode seguir" chegava sozinho."""
    orq = _orquestrador(planner_respostas=['{"action": "respond", "message": "segue"}'])
    state = AnalysisState.new("s", "u")
    state.tarefa_pendente = {"pedido": PEDIDO, "alvo": f"acessar_pasta {PASTA}",
                             "ferramenta": "listar_arquivos",
                             "argumentos": {"caminho": PASTA}}
    _aprovar(f"acessar_pasta {PASTA}")

    await orq.handle_message(state, "Liberei a pasta. Pode seguir.")

    retomadas = [m for m in state.history
                 if m.get("role") == "system" and "[TAREFA RETOMADA]" in str(m.get("content"))]
    assert len(retomadas) == 1, "a tarefa não voltou ao contexto"
    linha = retomadas[0]["content"]
    assert PEDIDO in linha, "voltou sem o pedido original"
    # A instrução nomeia a CHAMADA. Com um "continue de onde parou" vago, o
    # modelo respondeu "não tenho acesso à pasta nem ao resultado do passo
    # anterior" e não chamou ferramenta nenhuma: não havia passo anterior para
    # retomar, havia um passo que nunca rodou.
    assert "listar_arquivos" in linha, linha
    # Os argumentos vão como JSON, então a barra sai escapada: comparar o
    # caminho cru falharia por um detalhe de serialização, não por conteúdo.
    assert "financeiro" in linha, "a instrução não diz em que caminho chamar"
    assert "CONCEDIDA" in linha, "não deixa claro que o acesso já existe"


@pytest.mark.asyncio
async def test_a_pendencia_e_consumida_uma_vez_so():
    """Permissão negada não pode fazer o agente insistir para sempre."""
    orq = _orquestrador(planner_respostas=[
        '{"action": "respond", "message": "a"}',
        '{"action": "respond", "message": "b"}',
    ])
    state = AnalysisState.new("s", "u")
    state.tarefa_pendente = {"pedido": PEDIDO, "alvo": PASTA,
                             "ferramenta": "listar_arquivos", "argumentos": {}}
    _aprovar(PASTA)

    await orq.handle_message(state, "Liberei.")
    assert state.tarefa_pendente is None, "não foi consumida"

    await orq.handle_message(state, "E outra coisa, qual é a capital do Chile?")
    retomadas = [m for m in state.history
                 if m.get("role") == "system" and "[TAREFA RETOMADA]" in str(m.get("content"))]
    assert len(retomadas) == 1, "insistiu num turno que não tinha nada pendente"


@pytest.mark.asyncio
async def test_sem_aprovacao_a_mensagem_nova_nao_vira_retomada():
    """Quem fecha o cartão e pede outra coisa não aprovou nada. Dizer ao modelo
    que a autorização foi concedida, e pôr o passo antigo na frente do plano,
    devolvia o mesmo cartão com os argumentos antigos e atropelava o pedido novo."""
    orq = _orquestrador(planner_respostas=['{"action": "respond", "message": "ok"}'])
    state = AnalysisState.new("s", "u")
    state.tarefa_pendente = {"pedido": PEDIDO, "alvo": f"acessar_pasta {PASTA}",
                             "ferramenta": "listar_arquivos", "argumentos": {"caminho": PASTA}}
    vistos = []
    original = orq._injetar_passo_retomado
    orq._injetar_passo_retomado = lambda plano, retomar: (vistos.append(retomar), original(plano, retomar))[1]

    await orq.handle_message(state, "refaz, mas use a pasta de vendas")

    textos = [str(m.get("content")) for m in state.history if m.get("role") == "system"]
    assert not any("[TAREFA RETOMADA]" in x for x in textos), "contou aprovação que não houve"
    assert any("não foi aprovada" in x for x in textos), "o modelo não soube que o passo não rodou"
    assert all(r is None for r in vistos), "o passo antigo entrou no plano sem aprovação"
    assert state.tarefa_pendente is None


@pytest.mark.asyncio
async def test_sessao_sem_pendencia_nao_ganha_linha_nenhuma():
    orq = _orquestrador(planner_respostas=['{"action": "respond", "message": "oi"}'])
    state = AnalysisState.new("s", "u")
    await orq.handle_message(state, "bom dia")
    assert not [m for m in state.history if "[TAREFA RETOMADA]" in str(m.get("content"))]


# --------------------------------- executar, em vez de pedir de novo

def test_o_passo_autorizado_volta_ao_plano():
    """Instrução de texto não bastou.

    Com ela, o modelo do Router reconheceu o acesso e a tarefa (*"já estou com
    acesso aos dados e vou mapear esse banco para você agora mesmo"*) e encerrou
    o turno com `tool_calls: 0`. Anunciou a ação em vez de tomá-la, que é o mesmo
    padrão que derrubou o benchmark original.

    A ferramenta e os argumentos bloqueados são conhecidos, então o harness
    executa. Depender de o modelo obedecer a uma linha de sistema era transformar
    uma garantia em pedido.
    """
    orq = _orquestrador()
    plano = orq._injetar_passo_retomado([], {
        "ferramenta": "listar_arquivos", "argumentos": {"caminho": PASTA},
    })
    assert plano and plano[0]["tool"] == "listar_arquivos"
    assert plano[0]["arguments"] == {"caminho": PASTA}


def test_nao_duplica_o_que_o_planner_ja_propos():
    orq = _orquestrador()
    ja_tem = [{"tool": "listar_arquivos", "arguments": {"caminho": PASTA}}]
    assert orq._injetar_passo_retomado(ja_tem, {
        "ferramenta": "listar_arquivos", "argumentos": {"caminho": PASTA},
    }) == ja_tem


def test_o_passo_retomado_nao_apaga_o_resto_do_plano():
    """O planner pode ter proposto bem o resto da tarefa."""
    orq = _orquestrador()
    resto = [{"tool": "executar_python", "arguments": {"codigo": "x=1"}}]
    plano = orq._injetar_passo_retomado(resto, {
        "ferramenta": "listar_arquivos", "argumentos": {"caminho": PASTA},
    })
    assert [p["tool"] for p in plano] == ["listar_arquivos", "executar_python"]


def test_ferramenta_fantasma_nao_entra_no_plano():
    """Pacote trocado entre os dois turnos: o nome pode não existir mais, e o
    plano falharia por um passo impossível."""
    orq = _orquestrador()
    assert orq._injetar_passo_retomado([], {
        "ferramenta": "ferramenta_que_nao_existe", "argumentos": {},
    }) == []


def test_sem_pendencia_o_plano_passa_intacto():
    orq = _orquestrador()
    plano = [{"tool": "executar_python", "arguments": {}}]
    assert orq._injetar_passo_retomado(plano, None) == plano


# ------------------------- o esclarecimento nao atropela a retomada

@pytest.mark.asyncio
async def test_nao_pergunta_o_que_fazer_para_quem_acabou_de_autorizar(setor_teste):
    """O ultimo elo, e o mais teimoso.

    Verificado ao vivo: a linha de retomada ia, o injetor disparava
    (*"Retomada: injetando listar_arquivos no plano"*), e a resposta continuava
    sendo **"indique qual ação você deseja que eu execute nela"**.

    O planner propunha `perguntar_usuario` JUNTO do passo retomado, e o caminho
    de esclarecimento encerra o turno antes de executar qualquer passo. Então o
    plano certo existia, na ordem certa, e morria na frente da porta.

    A guarda de re-pergunta que já existia só pega o caso repetido
    (`perguntas_seguidas >= MAX`). Este é o primeiro, e já é demais: quem acabou
    de conceder a permissão já disse o que quer.
    """
    from sentury.harness.loop_budget import StopReason
    from tests.test_orchestrator import (
        EchoResponder, ScriptedPlanner, _store,
    )
    import json as _json

    # O formato real: `questions` / `question` / `options`, em ingles.
    pergunta = _json.dumps({"action": "tool_call", "plan": [
        {"tool": "perguntar_usuario", "arguments": {
            "questions": [{"question": "Qual operacao?", "options": ["a", "b"]}]}},
    ]})
    orq = SenturyOrchestrator(
        planner=ScriptedPlanner([pergunta, '{"action": "respond", "message": "pronto"}']),
        responder=EchoResponder(),
        store=_store(),
    )
    state = AnalysisState.new("s-clar", "u")
    state.tarefa_pendente = {
        "pedido": PEDIDO, "alvo": f"acessar_pasta {PASTA}",
        "ferramenta": "consultar_medida", "argumentos": {},
    }
    _aprovar(f"acessar_pasta {PASTA}", "s-clar")

    saida = await orq.handle_message(state, "Liberei. Pode seguir.")

    assert (saida.get("harness") or {}).get("proposed_tool") != "perguntar_usuario", saida["message"]
    stats = (saida.get("harness") or {}).get("loop_stats") or {}
    assert stats.get("tool_calls", 0) >= 1, f"o passo retomado nao rodou: {stats}"


@pytest.mark.asyncio
async def test_sem_retomada_o_esclarecimento_continua_valendo():
    """A regressão a evitar: matar o AskUserQuestion junto com o conserto."""
    from tests.test_orchestrator import (
        EchoResponder, ScriptedPlanner, _store,
    )
    import json as _json

    pergunta = _json.dumps({"action": "tool_call", "plan": [
        {"tool": "perguntar_usuario", "arguments": {
            "questions": [{"question": "Qual periodo?", "options": ["mes", "ano"]}]}},
    ]})
    orq = SenturyOrchestrator(
        planner=ScriptedPlanner([pergunta]),
        responder=EchoResponder(),
        store=_store(),
    )
    saida = await orq.handle_message(AnalysisState.new("s-clar2", "u"), "como esta o medida?")
    assert (saida.get("harness") or {}).get("proposed_tool") == "perguntar_usuario"


def test_retomada_bloqueada_de_novo_guarda_o_pedido_original():
    """Negar o "só desta vez" e dizer "pode seguir" não pode trocar o pedido."""
    orq = _orquestrador()
    state = AnalysisState.new("s", "u")
    resultado_de_permissao(orq,
        state, "pode seguir",
        {"chave": "x", "comando": "x", "motivo": "", "ferramenta": "listar_arquivos"},
        {"pedido_retomado": PEDIDO}, {},
    )
    assert state.tarefa_pendente["pedido"] == PEDIDO


def test_outra_acao_da_mesma_ferramenta_nao_esconde_o_passo_aprovado():
    """Com `computador digitar` no plano, o `computador clicar` aprovado sumia:
    nunca rodava, e o digitar gastava a aprovacao."""
    from sentury.harness.retomada import injetar_passo

    aprovado = {"ferramenta": "computador", "argumentos": {"acao": "clicar", "x": 1, "y": 2}}
    plano = [{"tool": "computador", "arguments": {"acao": "digitar", "texto": "oi"}}]
    assert injetar_passo(plano, aprovado) == [
        {"tool": "computador", "arguments": {"acao": "clicar", "x": 1, "y": 2}}] + plano


def test_a_mesma_acao_refeita_nao_duplica():
    """O planner refez o clique um pixel ao lado: roda uma vez, nao duas."""
    from sentury.harness.retomada import injetar_passo

    aprovado = {"ferramenta": "computador", "argumentos": {"acao": "clicar", "x": 1, "y": 2}}
    plano = [{"tool": "computador", "arguments": {"acao": "clicar", "x": 2, "y": 2}}]
    assert injetar_passo(plano, aprovado) == plano
