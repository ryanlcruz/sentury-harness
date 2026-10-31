"""O turno sabe o que roda agora nas outras conversas.

Sem isso, duas conversas repetem o mesmo trabalho ou gravam o mesmo arquivo sem
saber uma da outra. O aviso é fato no contexto, não ordem.
"""
import json
from types import SimpleNamespace

import pytest

from sentury.harness import registro_do_turno
from sentury.harness.contexto_do_mundo import outras_conversas


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setattr(registro_do_turno, "_abertos", {})


def _abrir(sessao, pedido):
    state = SimpleNamespace(session_id=sessao, funcoes_ativas=[], history=[])
    registro_do_turno.abrir(state, pedido)


def test_mostra_pedido_ferramenta_e_alvo_da_outra_conversa():
    _abrir("a", "resume o relatório")
    _abrir("b", "atualiza as notas da reunião")
    registro_do_turno.passo_comecou("b", "escrever_arquivo", {"caminho": "notas.txt", "conteudo": "x" * 500}, True)

    texto = outras_conversas("a", agora=registro_do_turno._abertos["b"]["iniciado_em"] + 90)
    assert "### OUTRAS CONVERSAS RODANDO AGORA" in texto
    assert '"atualiza as notas da reunião"' in texto
    assert "agora em `escrever_arquivo` (caminho: notas.txt)" in texto
    assert "há 1 min" in texto
    assert "resume o relatório" not in texto, "a própria conversa não entra"
    assert "x" * 100 not in texto, "conteúdo do arquivo não vai para o contexto"


def test_sem_outra_conversa_nao_ha_secao():
    _abrir("a", "oi")
    assert outras_conversas("a") is None


def test_turno_fechado_sai_e_passo_acabado_nao_conta_como_em_andamento():
    _abrir("a", "oi")
    _abrir("b", "roda os testes")
    registro_do_turno.passo_comecou("b", "executar_comando", {"comando": "pytest"}, True)
    registro_do_turno.passo_acabou("b", "ok")
    assert "entre uma ação e outra" in outras_conversas("a")
    registro_do_turno.fechar("b", "concluido")
    assert outras_conversas("a") is None


async def test_o_modelo_recebe_a_secao_no_turno(monkeypatch):
    from sentury.data.store import SemDados
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState

    class Modelo:
        supports_tools = False
        last_model = "teste"

        def __init__(self):
            self.vistos = []

        async def complete(self, messages, **kwargs):
            self.vistos.append(json.dumps(messages, ensure_ascii=False))
            return '{"plan": []}'

    _abrir("outra", "gera a planilha de setembro")
    registro_do_turno.passo_comecou("outra", "executar_script", {"caminho": "setembro.py"}, True)
    modelo = Modelo()
    orq = SenturyOrchestrator(planner=modelo, responder=modelo, store=SemDados())
    await orq.handle_message(AnalysisState.new("esta", "u"), "o que você consegue fazer?")
    assert any("OUTRAS CONVERSAS RODANDO AGORA" in visto and "setembro.py" in visto for visto in modelo.vistos)
