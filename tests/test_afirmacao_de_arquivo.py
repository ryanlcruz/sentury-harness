import base64

import pytest

from sentury.config import settings
from sentury.harness.afirmacao_de_arquivo import avisar
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.test_chamada_em_texto import _Nativo, _NativoComChamadas
from tests.test_orchestrator import EchoResponder, _store


@pytest.fixture
def nativo(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)


async def test_arquivo_sem_lastro_volta_ao_mesmo_agente_uma_vez(nativo):
    modelo = _Nativo(["Gerei resultado.pdf.", "Não cheguei a criar o arquivo."])
    orq = SenturyOrchestrator(planner=modelo, responder=EchoResponder(), store=_store())
    resposta = await orq.handle_message(AnalysisState("s", "u"), "gere o relatório")
    assert len(modelo.vistas) == 2
    assert "confirma esses arquivos" in str(modelo.vistas[1])
    assert resposta["message"] == "Não cheguei a criar o arquivo."
    assert resposta["attachment"] is None
    assert resposta["harness"]["ferramentas"] == []


async def test_repetir_afirmacao_nao_cria_anexo_nem_terceira_chamada(nativo):
    modelo = _Nativo(["Gerei resultado.pdf."] * 3)
    orq = SenturyOrchestrator(planner=modelo, responder=EchoResponder(), store=_store())
    resposta = await orq.handle_message(AnalysisState("s", "u"), "gere o relatório")
    assert len(modelo.vistas) == 2
    assert resposta["message"] == "Gerei resultado.pdf."
    assert resposta["attachment"] is None


async def test_agente_pode_criar_arquivo_pelo_canal_nativo(nativo, monkeypatch):
    from sentury.harness import orchestrator

    anexo = {"type": "txt", "filename": "resultado.txt", "mime_type": "text/plain",
             "content_base64": base64.b64encode(b"arquivo real").decode("ascii")}
    chamadas = []

    async def ferramenta(*args, **kwargs):
        chamadas.append(args[2])
        return {"ok": True, "attachment": anexo}

    monkeypatch.setattr("sentury.harness.execucao_do_passo.execute_tool", ferramenta)
    modelo = _NativoComChamadas(["Gerei resultado.txt.",
                                 ("entregar_arquivo", {"caminho": "resultado.txt"}),
                                 "Aqui está resultado.txt."])
    orq = SenturyOrchestrator(planner=modelo, responder=EchoResponder(), store=_store())
    resposta = await orq.handle_message(AnalysisState("s", "u"), "entregue o arquivo")
    assert chamadas == ["entregar_arquivo"]
    assert resposta["attachment"]["content_base64"] == anexo["content_base64"]
    assert len(modelo.vistas) == 3


def test_anexo_real_e_arquivo_lido_nao_geram_aviso():
    estado = AnalysisState("s", "u")
    assert not avisar(estado, "Aqui está resultado.pdf.", {"filename": "resultado.pdf"}, [], {})
    assert not avisar(estado, "Li dados.csv.", None,
                     [{"result": {"ok": True, "caminho": "C:/dados.csv"}}], {})
    assert estado.history == []


def test_nome_que_a_listagem_devolveu_tem_lastro():
    """Repetir os nomes que `listar_arquivos` achou não é alegar entrega."""
    listagem = {"result": {"ok": True, "caminho": "C:/pasta", "itens": [
        {"nome": "notas.txt", "caminho": "notas.txt", "tipo": "arquivo"}]}}
    estado = AnalysisState("s", "u")
    assert not avisar(estado, "A pasta tem notas.txt.", None, [listagem], {})
    assert avisar(estado, "A pasta tem outro.txt.", None, [listagem], {})


def test_anexo_diferente_nao_acoberta_arquivo_inventado():
    assert avisar(AnalysisState("s", "u"), "Gerei outro.pdf.",
                  {"filename": "real.pdf"}, [], {})


def test_exemplo_de_codigo_nao_pede_exportacao():
    assert not avisar(AnalysisState("s", "u"), '```python\nabrir("exemplo.csv")\n```', None, [], {})


async def test_pos_resposta_nao_chama_exportacao(monkeypatch):
    from sentury.harness.pos_resposta import aplicar

    base = SenturyOrchestrator(planner=object(), responder=object(), store=object())
    estado = AnalysisState("s", "u")
    estado.register_result("analise", {}, {"valor": 10}, 1)
    resultados = []
    anexo, texto = await aplicar(base, user_message="gere um dashboard html", state=estado,
                                attachment=None, reply_text="Gerei resultado.html.",
                                tool_results=resultados, pre_turn_had_data=True)
    assert anexo is None
    assert texto == "Gerei resultado.html."
    assert resultados == []


def test_qualquer_tipo_de_arquivo_precisa_de_lastro():
    """Código também é entrega: `conversor.py` pronto sem gravação nenhuma é a
    mesma promessa vazia de um relatório que não existe."""
    assert avisar(AnalysisState("s", "u"), "Criei conversor.py e test_conversor.py.", None, [], {})
    gravado = [{"result": {"ok": True, "caminho": "C:/demo/conversor.py"}}]
    assert not avisar(AnalysisState("s", "u"), "Criei conversor.py.", None, gravado, {})


def test_site_versao_e_nome_de_codigo_nao_sao_arquivo():
    texto = ("Veja github.com e a versão 3.12; mande para fulano@exemplo.com. "
             "Use json.dumps e os.remove para isso.")
    assert not avisar(AnalysisState("s", "u"), texto, None, [], {})
