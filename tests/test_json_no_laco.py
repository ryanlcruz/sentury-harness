"""O protocolo textual usa as mesmas guardas e retomada das chamadas nativas."""
import json

import pytest

from sentury.config import settings
from sentury.data.store import SemDados
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.tools import permissoes


class Texto:
    supports_tools = False
    last_model = "teste:texto"

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    async def complete(self, messages, **kwargs):
        self.chamadas.append(messages)
        if not self.respostas:
            pytest.fail("O turno pediu uma chamada de modelo que não estava prevista.")
        return json.dumps(self.respostas.pop(0))


class Resposta:
    last_model = "teste:resposta"

    async def complete(self, messages, **kwargs):
        return "O turno terminou com o resultado observado."


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setattr(permissoes, "_DA_SESSAO", {})
    monkeypatch.setattr(permissoes, "_CREDITO_UNICO", {})
    permissoes.definir_permitir_tudo(False)


def acao(nome, argumentos):
    return {"action": "tool_call", "tool": nome, "arguments": argumentos}


def orquestrador(respostas):
    planner = Texto(respostas)
    return SenturyOrchestrator(planner=planner, responder=Resposta(), store=SemDados()), planner


async def test_acao_no_primeiro_passo_abre_cartao_e_retoma(tmp_path):
    argumentos = {"caminho": "nota.txt", "conteudo": "Conteúdo aprovado."}
    orq, planner = orquestrador([
        acao("escrever_arquivo", argumentos),
        {"plan": [], "message": "Feito."},
        {"plan": [], "message": "Feito."},
    ])
    state = AnalysisState.new("json-permissao", "u")
    bloqueado = await orq.handle_message(state, "escreva a nota indicada")
    assert bloqueado.get("permissao"), "o resultado pendente precisa chegar ao cartão"
    assert state.tarefa_pendente["argumentos"] == argumentos
    assert len(planner.chamadas) == 1, "a ação já recebida não exige outro planejamento"
    assert not (tmp_path / "nota.txt").exists()
    permissoes.responder(bloqueado["permissao"]["comando"], "uma_vez", state.session_id)
    retomado = await orq.handle_message(state, "pode seguir")
    assert not retomado.get("permissao")
    assert state.tarefa_pendente is None
    assert (tmp_path / "nota.txt").read_text(encoding="utf-8") == argumentos["conteudo"]
    assert retomado["harness"]["ferramentas"] == ["escrever_arquivo"]


async def test_acao_json_respeita_o_orcamento_do_turno(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("primeiro", encoding="utf-8")
    (tmp_path / "b.txt").write_text("segundo", encoding="utf-8")
    from sentury.harness import laco_do_turno
    from sentury.harness.loop_budget import LoopBudget

    monkeypatch.setattr(laco_do_turno, "orcamento_do_turno", lambda *_: LoopBudget(max_tool_calls=1))
    orq, planner = orquestrador([
        acao("ler_arquivo", {"caminho": "a.txt"}), acao("ler_arquivo", {"caminho": "b.txt"}),
        {"action": "respond", "message": "fim"},
    ])
    resultado = await orq.handle_message(AnalysisState.new("json-limite", "u"), "leia as duas notas")
    assert resultado["harness"]["ferramentas"] == ["ler_arquivo"]
    # A ação gastou o orçamento; o mesmo modelo fecha, sem ferramenta.
    assert len(planner.chamadas) == 2
    assert "As voltas deste turno acabaram" in str(planner.chamadas[1])
    assert resultado.get("deliberation"), "a trilha precisa registrar o limite no laço principal"


async def test_falha_json_volta_ao_modelo_e_permite_outra_rota(tmp_path):
    (tmp_path / "presente.txt").write_text("conteúdo encontrado", encoding="utf-8")
    orq, planner = orquestrador([
        acao("ler_arquivo", {"caminho": "ausente.txt"}),
        acao("ler_arquivo", {"caminho": "presente.txt"}),
        {"plan": [], "message": "Li a nota disponível."},
    ])
    resultado = await orq.handle_message(AnalysisState.new("json-erro", "u"), "leia a nota disponível")
    assert resultado["harness"]["ferramentas"] == ["ler_arquivo", "ler_arquivo"]
    assert "ausente.txt" in str(planner.chamadas[1])
    assert "conteúdo encontrado" in str(planner.chamadas[2])
    assert len(resultado["deliberation"]["steps"]) >= 2


def test_nao_existe_segundo_motor_de_execucao():
    assert not hasattr(SenturyOrchestrator, "_run_legacy_flow")
    assert not hasattr(SenturyOrchestrator, "_write_reply")
    assert not hasattr(SenturyOrchestrator, "_run_turn")


async def test_plano_no_primeiro_passo_tambem_passa_pela_autorizacao():
    argumentos = {"caminho": "plano.txt", "conteudo": "conteúdo"}
    orq, planner = orquestrador([{"plan": [{"tool": "escrever_arquivo", "arguments": argumentos}]}])
    resultado = await orq.handle_message(AnalysisState.new("plano-no-primeiro-passo", "u"), "escreva a nota")
    assert resultado["permissao"]["argumentos"] == argumentos
    assert len(planner.chamadas) == 1
