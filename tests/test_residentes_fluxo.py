"""Fluxo da HQ com worker, fila em disco e orquestrador reais."""

import asyncio
import json
import uuid

import pytest

from sentury.config import settings
from sentury.residentes import hq, manifesto, registro, tarefas, worker


class ModeloRoteirizado:
    supports_tools = True
    last_model = "modelo-falso"
    last_usage = None
    last_tool_calls = None

    def __init__(self, passos=(), resposta="Trabalho concluído pelo residente."):
        self.passos = list(passos)
        self.resposta = resposta
        self.chamadas = []

    async def complete(self, messages, tools=None, **kwargs):
        if tools is None:
            return json.dumps({"action": "respond", "message": self.resposta})
        self.chamadas.append(messages)
        self.last_tool_calls = None
        if not self.passos:
            return self.resposta
        ferramenta, argumentos = self.passos.pop(0)
        disponiveis = {s["function"]["name"] for s in tools}
        assert ferramenta in disponiveis
        self.last_tool_calls = [{
            "id": f"passo-{len(self.chamadas)}", "type": "function",
            "function": {"name": ferramenta, "arguments": json.dumps(argumentos)},
        }]
        return ""


class ModeloTexto:
    supports_tools = False
    last_model = "modelo-falso-texto"
    last_tool_calls = None

    def __init__(self, ferramenta, argumentos):
        self.ferramenta = ferramenta
        self.argumentos = argumentos
        self.chamadas = 0
        self.contextos = []

    async def complete(self, messages, **kwargs):
        self.chamadas += 1
        self.contextos.append(list(messages))
        if self.chamadas == 1:
            return json.dumps({"plan": [{"tool": self.ferramenta, "arguments": self.argumentos}]})
        return json.dumps({"plan": [], "message": "Não tenho essa ferramenta."})


@pytest.fixture
async def ambiente(tmp_path, monkeypatch):
    from sentury import main

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path / "trabalho"))
    (tmp_path / "trabalho").mkdir()
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setattr(settings, "SENTURY_GRAVAR_TRACOS", False)
    worker.configurar(main._rodar_turno_do_residente)
    nome = "agente-" + uuid.uuid4().hex[:8]
    yield main, tmp_path, nome
    await worker.parar_todos()
    worker.configurar(None)


def _criar(nome, ferramentas=("ler_arquivo",), orcamento=None):
    dados = {"nome": nome, "papel": "leitor", "objetivo": "resolver o pedido",
             "ferramentas": list(ferramentas)}
    if orcamento:
        dados["orcamento"] = orcamento
    return hq.criar(dados)


async def _esperar(tarefa_id, estado, timeout=8):
    async def ate():
        while True:
            atual = tarefas.carregar(tarefa_id)
            if atual.estado == estado and not worker.acordado(atual.agente):
                return atual
            await asyncio.sleep(0.02)
    try:
        return await asyncio.wait_for(ate(), timeout)
    except TimeoutError:
        atual = tarefas.carregar(tarefa_id)
        pytest.fail(f"esperava {estado}; ficou em {atual.estado}: {atual.motivo}")


async def test_pedido_roda_e_residente_dorme(ambiente, monkeypatch):
    main, tmp_path, nome = ambiente
    arquivo = tmp_path / "trabalho" / "nota.txt"
    arquivo.write_text("Este projeto guarda notas.", encoding="utf-8")
    modelo = ModeloRoteirizado([("search_tools", {"nomes": ["ler_arquivo"]}),
                                ("ler_arquivo", {"caminho": "nota.txt"})],
                               resposta="O projeto guarda notas.")
    monkeypatch.setattr(main.orchestrator, "planner", modelo)
    monkeypatch.setattr(main.orchestrator, "responder", modelo)
    _criar(nome)
    pedido = hq.pedir(nome, "Leia nota.txt e diga o que faz")
    feita = await _esperar(pedido["id"], tarefas.FEITA)
    assert "guarda notas" in feita.resposta
    assert registro.carregar(nome).estado == manifesto.DORMINDO
    assert feita.tentativas == 1
    assert len(modelo.chamadas) >= 2


async def test_espera_aprovacao_e_retorna_sem_pedir_de_novo(ambiente, monkeypatch):
    main, tmp_path, nome = ambiente
    fora = tmp_path / "fora"
    fora.mkdir()
    arquivo = fora / "nota.txt"
    arquivo.write_text("conteúdo autorizado", encoding="utf-8")
    modelo = ModeloRoteirizado([("search_tools", {"nomes": ["ler_arquivo"]}),
                                ("ler_arquivo", {"caminho": str(arquivo)})],
                               resposta="Li o conteúdo autorizado.")
    monkeypatch.setattr(main.orchestrator, "planner", modelo)
    monkeypatch.setattr(main.orchestrator, "responder", modelo)
    _criar(nome)
    pedido = hq.pedir(nome, "Leia a nota fora do workspace")
    esperando = await _esperar(pedido["id"], tarefas.ESPERANDO)
    assert esperando.pendente.startswith("acessar_pasta ")
    hq.responder(pedido["id"], "uma_vez")
    feita = await _esperar(pedido["id"], tarefas.FEITA)
    assert feita.tentativas == 1
    assert "autorizado" in feita.resposta
    estado = await main.session_store.get(hq.sessao_do(nome))
    assert any("conteúdo autorizado" in str(m.get("content") or "")
               for m in estado["history"] if m.get("role") == "system")


async def test_negar_cancela(ambiente, monkeypatch):
    main, tmp_path, nome = ambiente
    fora = tmp_path / "fora"
    fora.mkdir()
    arquivo = fora / "nota.txt"
    arquivo.write_text("não ler", encoding="utf-8")
    modelo = ModeloRoteirizado([("search_tools", {"nomes": ["ler_arquivo"]}),
                                ("ler_arquivo", {"caminho": str(arquivo)})])
    monkeypatch.setattr(main.orchestrator, "planner", modelo)
    monkeypatch.setattr(main.orchestrator, "responder", modelo)
    _criar(nome)
    pedido = hq.pedir(nome, "Leia a nota fora do workspace")
    await _esperar(pedido["id"], tarefas.ESPERANDO)
    resposta = hq.responder(pedido["id"], "negar")
    assert resposta["estado"] == tarefas.CANCELADA
    assert "negou" in tarefas.carregar(pedido["id"]).motivo


async def test_ferramenta_fora_do_manifesto_e_recusada(ambiente, monkeypatch):
    main, tmp_path, nome = ambiente
    arquivo = tmp_path / "trabalho" / "negado.txt"
    planner = ModeloTexto("listar_arquivos", {"caminho": str(tmp_path / "trabalho")})
    monkeypatch.setattr(main.orchestrator, "planner", planner)
    monkeypatch.setattr(main.orchestrator, "responder", ModeloRoteirizado(resposta="Não tenho essa ferramenta."))
    _criar(nome)
    pedido = hq.pedir(nome, "Liste os arquivos")
    feita = await _esperar(pedido["id"], tarefas.FEITA)
    assert "Não tenho" in feita.resposta
    assert planner.chamadas == 2
    assert any("não está entre as ferramentas" in str(m.get("content") or "")
               for m in planner.contextos[1])
    assert not arquivo.exists()
    estado = await main.session_store.get(hq.sessao_do(nome))
    assert any("não está entre as ferramentas" in str(m.get("content") or "")
               for m in estado["history"] if m.get("role") == "system")


async def test_recuperar_tarefa_rodando_conta_tentativas(ambiente):
    _, _, nome = ambiente
    _criar(nome)
    tarefa = tarefas.enfileirar(nome, "continue")
    for tentativa in range(1, 4):
        tarefas.comecar(tarefa.id)
        assert tarefas.recuperar() == 1
        atual = tarefas.carregar(tarefa.id)
        assert atual.tentativas == tentativa
        assert atual.estado == (tarefas.FALHOU if tentativa == 3 else tarefas.NA_FILA)


async def test_orcamento_mantem_pedido_na_fila(ambiente, monkeypatch):
    main, _, nome = ambiente
    modelo = ModeloRoteirizado()
    monkeypatch.setattr(main.orchestrator, "planner", modelo)
    monkeypatch.setattr(main.orchestrator, "responder", modelo)
    _criar(nome, orcamento={"turnos_por_dia": 1})
    anterior = tarefas.enfileirar(nome, "anterior")
    tarefas.comecar(anterior.id)
    tarefas.concluir(anterior.id, "feito")
    pedido = hq.pedir(nome, "novo pedido")
    await _esperar(pedido["id"], tarefas.NA_FILA)
    guardada = tarefas.carregar(pedido["id"])
    assert "turnos de hoje" in guardada.motivo
    assert guardada.tentativas == 0
    assert not modelo.chamadas
