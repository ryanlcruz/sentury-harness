"""Repetir a chamada devolve a observação anterior, não o silêncio.

Cortar a chamada repetida em silêncio deixa o modelo sem a observação que pediu,
e ele propõe a mesma coisa de novo ou conclui sem ter olhado. Como o resultado da
primeira vez já existe e é o mesmo, ele volta junto com um lembrete de que a
chamada se repetiu: nem custo de rodar de novo, nem silêncio. A decisão de
continuar, mudar ou parar fica com o modelo.

O silêncio é que causava o erro, não a economia.
"""
import pytest

from sentury.harness.repeticao import Repetidas, assinatura, lembrete


# --------------------------------------------------- a identidade da chamada

def test_mesma_chamada_mesma_assinatura():
    assert assinatura("listar", {"a": 1, "b": 2}) == assinatura("listar", {"b": 2, "a": 1})


def test_argumento_diferente_e_outra_chamada():
    assert assinatura("listar", {"caminho": "x"}) != assinatura("listar", {"caminho": "y"})


def test_argumento_que_nao_serializa_ainda_tem_identidade():
    """Sumir com a chave seria pior que uma chave feia."""
    class Esquisito:
        pass

    sig = assinatura("listar", {"obj": Esquisito()})
    assert sig[0] == "listar" and sig[1]


# --------------------------------------------------- o registro

def test_a_primeira_chamada_nao_e_repeticao():
    r = Repetidas()
    assert r.repetida("listar", {"caminho": "data"}) is None


def test_a_segunda_devolve_o_resultado_da_primeira():
    r = Repetidas()
    r.registrar("listar", {"caminho": "data"}, {"itens": ["demo"]})
    achado = r.repetida("listar", {"caminho": "data"})
    assert achado["resultado"] == {"itens": ["demo"]}
    assert achado["vezes"] == 1


def test_a_contagem_sobe_a_cada_insistencia():
    r = Repetidas()
    r.registrar("listar", {}, {"ok": True})
    vezes = [r.repetida("listar", {})["vezes"] for _ in range(3)]
    assert vezes == [1, 2, 3]


def test_perguntar_usuario_fica_de_fora():
    """Cada pergunta é única e não "roda": contar repetição ali não faz sentido."""
    r = Repetidas()
    r.registrar("perguntar_usuario", {"questions": []}, {"ok": True})
    assert r.repetida("perguntar_usuario", {"questions": []}) is None


# --------------------------------------------------- o texto que volta

def test_o_lembrete_carrega_o_resultado_anterior():
    """Sem o resultado, o lembrete seria só uma reclamação: e era justamente a
    observação que faltava ao modelo."""
    texto = lembrete("consultar_sql", {"linhas": 120, "tabela": "pedidos"}, vezes=1)
    assert "120" in texto or "pedidos" in texto, texto
    assert "[CHAMADA REPETIDA]" in texto


def test_o_lembrete_escala_com_a_insistencia():
    """Texto igual nas cinco vezes vira ruído que o modelo aprende a ignorar."""
    primeiro = lembrete("x", {"a": 1}, vezes=1)
    terceiro = lembrete("x", {"a": 1}, vezes=2)
    muito = lembrete("x", {"a": 1}, vezes=9)
    assert primeiro != terceiro != muito
    assert "responda" in muito.lower()


def test_o_lembrete_manda_mudar_de_abordagem_ou_terminar():
    """É a instrução do repeat-tool-reminder: analisar e mudar, ou concluir."""
    texto = lembrete("x", {"a": 1}, vezes=1).lower()
    assert "mude a abordagem" in texto or "mude" in texto
    assert "responda" in texto


# --------------------------------------------------- no turno de verdade

@pytest.mark.asyncio
async def test_o_modelo_recebe_a_observacao_quando_repete(monkeypatch, setor_teste):
    from sentury.config import settings
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState
    from tests.test_orchestrator import (
        EchoResponder, ScriptedPlanner, _respond, _store, _tool_call,
    )

    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True, raising=False)
    orq = SenturyOrchestrator(
        planner=ScriptedPlanner([_tool_call("consultar_medida"), _tool_call("consultar_medida"),
                                 _respond("pronto")]),
        responder=EchoResponder(),
        store=_store(),
    )
    state = AnalysisState.new("s-rep", "u")
    await orq.handle_message(state, "como esta o medida?")

    avisos = [m for m in state.history
              if m.get("role") == "system" and "[CHAMADA REPETIDA]" in str(m.get("content"))]
    assert avisos, "o modelo repetiu e não recebeu nada de volta"


def test_ferramenta_que_le_o_mundo_roda_de_novo():
    """O mesmo `ver` depois de um clique vê outra tela: devolver o print velho
    esconderia do agente o que mudou. Vale para toda ferramenta declarada
    `determinista: false`."""
    from sentury.harness.repeticao import Repetidas
    from sentury.tools.registry import com_propriedade

    repetidas = Repetidas()
    for tool in sorted(com_propriedade("determinista", False)):
        repetidas.registrar(tool, {"acao": "ver"}, {"ok": True})
        assert repetidas.repetida(tool, {"acao": "ver"}) is None, tool
    repetidas.registrar("listar_arquivos", {"caminho": "."}, {"ok": True})
    assert repetidas.repetida("listar_arquivos", {"caminho": "."}) is not None
