"""Vários residentes no mesmo plano: um cartão para a equipe, um passo por aprovado.

Com um cartão por residente, três agentes eram três idas e voltas, e uma
recusa no meio parava as outras. A pessoa marca quem entra; só esses nascem, e
o modelo fica sabendo quem ficou de fora.
"""
import json

import pytest

from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from sentury.residentes import registro, worker
from sentury.tools import permissoes
from tests.test_orchestrator import EchoResponder, _store


def _membro(nome, papel):
    return {"nome": nome, "papel": papel, "objetivo": f"{papel} sem parar",
            "ferramentas": ["ler_arquivo"]}


EQUIPE = [_membro("alfa", "pesquisa"), _membro("nina", "escreve"), _membro("tito", "revisa")]


class _Planner:
    supports_tools = True
    last_model = "teste"
    last_usage = None

    def __init__(self, roteiro):
        self.roteiro, self.last_tool_calls = iter(roteiro), None

    async def complete(self, messages, tools=None, **kwargs):
        item = next(self.roteiro, "Pronto.")
        self.last_tool_calls = None
        if isinstance(item, list):
            self.last_tool_calls = [{"id": f"c{i}", "type": "function", "function": {
                "name": "criar_agente", "arguments": json.dumps(args)}} for i, args in enumerate(item)]
            return ""
        return item


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.delenv("SENTURY_HQ_URL", raising=False)
    monkeypatch.setattr(permissoes, "_DA_SESSAO", {})
    monkeypatch.setattr(permissoes, "_CREDITO_UNICO", {})
    worker.configurar(None)
    yield
    worker.configurar(None)


async def test_a_pausa_leva_a_equipe_inteira():
    orq = SenturyOrchestrator(planner=_Planner([EQUIPE]), responder=EchoResponder(), store=_store())
    state = AnalysisState.new("equipe", "u")
    saida = await orq.handle_message(state, "monte uma equipe para o relatório")
    pedido = saida.get("permissao") or {}
    assert [m["nome"] for m in pedido.get("equipe") or []] == ["alfa", "nina", "tito"]
    assert state.tarefa_pendente["equipe"] and not registro.listar()


async def test_so_os_marcados_nascem_e_o_modelo_sabe_quem_ficou_de_fora():
    orq = SenturyOrchestrator(planner=_Planner([EQUIPE, "Equipe criada."]), responder=EchoResponder(),
                              store=_store())
    state = AnalysisState.new("equipe", "u")
    await orq.handle_message(state, "monte uma equipe para o relatório")

    for nome in ("alfa", "nina"):
        permissoes.responder(f"criar_agente {nome}", "uma_vez", "equipe")
    await orq.handle_message(state, "Autorizado. Pode rodar `criar_agente alfa, nina`.")

    assert sorted(a.nome for a in registro.listar()) == ["alfa", "nina"]
    notas = [str(m.get("content")) for m in state.history if m.get("role") == "system"]
    assert any("Ficaram de fora" in n and "tito" in n for n in notas), notas
    assert state.tarefa_pendente is None


async def test_um_residente_so_continua_com_o_cartao_de_sempre():
    orq = SenturyOrchestrator(planner=_Planner([[EQUIPE[0]]]), responder=EchoResponder(), store=_store())
    saida = await orq.handle_message(AnalysisState.new("um", "u"), "crie um pesquisador")
    pedido = saida.get("permissao") or {}
    assert pedido.get("comando") == "criar_agente alfa" and "equipe" not in pedido


# Uma chamada só, como manda o provedor que entrega uma chamada de ferramenta por resposta.
NUMA_CHAMADA = [{**EQUIPE[0], "colegas": EQUIPE[1:]}]


async def test_uma_chamada_com_colegas_leva_a_equipe_inteira():
    orq = SenturyOrchestrator(planner=_Planner([NUMA_CHAMADA]), responder=EchoResponder(), store=_store())
    state = AnalysisState.new("colegas", "u")
    saida = await orq.handle_message(state, "monte uma equipe para o relatório")
    equipe = (saida.get("permissao") or {}).get("equipe") or []
    assert [m["nome"] for m in equipe] == ["alfa", "nina", "tito"]
    assert all("colegas" not in m for m in equipe) and not registro.listar()


async def test_os_colegas_marcados_nascem():
    orq = SenturyOrchestrator(planner=_Planner([NUMA_CHAMADA, "Equipe criada."]), responder=EchoResponder(),
                              store=_store())
    state = AnalysisState.new("colegas", "u")
    await orq.handle_message(state, "monte uma equipe para o relatório")

    for nome in ("alfa", "tito"):
        permissoes.responder(f"criar_agente {nome}", "uma_vez", "colegas")
    await orq.handle_message(state, "Autorizado. Pode rodar `criar_agente alfa, tito`.")

    assert sorted(a.nome for a in registro.listar()) == ["alfa", "tito"]


def test_colegas_tem_os_mesmos_campos_do_residente():
    """O modelo descreve cada colega com o mesmo manifesto do primeiro."""
    from sentury.tools.registry import TOOL_REGISTRY

    parametros = TOOL_REGISTRY["criar_agente"]["parametros"]
    campos = {k: v for k, v in parametros["properties"].items() if k != "colegas"}
    itens = parametros["properties"]["colegas"]["items"]
    assert itens["properties"] == campos and itens["required"] == parametros["required"]


def test_aprovar_um_nome_nao_libera_outro():
    """A chave carrega o nome: a aprovação de `alfa` não cria `beta` se o modelo
    trocar o nome, e cada membro da equipe tem o próprio crédito."""
    from sentury.exec.politica import avaliar

    permissoes.responder("criar_agente alfa", "uma_vez", "s")
    assert avaliar("criar_agente beta", "s", checar_alvo=False, na_hora=True, consumir=False)["permitido"] is False
    assert avaliar("criar_agente alfa", "s", checar_alvo=False, na_hora=True, consumir=False)["permitido"] is True


def test_tela_mostra_a_equipe_e_registra_os_aprovados():
    """O cartão da equipe aparece quando a permissão traz mais de um residente, e o
    registro diz quem foi aprovado, no plural."""
    import shutil
    import subprocess
    from pathlib import Path

    cliente = Path("sentury/client")
    folha = (cliente / "src/features/chat/PermissionSheet.tsx").read_text(encoding="utf-8")
    assert "<EquipeDeResidentes" in folha and "`criar_agente ${nome}`" in folha
    node = shutil.which("node")
    if not node or not (cliente / "node_modules/typescript").exists():
        pytest.skip("o resto precisa de Node e npm install")
    script = """
    const fs = require('fs'), ts = require('typescript'), assert = require('node:assert/strict');
    const codigo = ts.transpileModule(fs.readFileSync('src/features/chat/autorizacao.ts', 'utf8'), {
      compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
    const m = {exports: {}}; new Function('exports', codigo)(m.exports);
    assert.deepEqual(m.exports.residenteAprovado('criar_agente alfa, nina'), ['Alfa', 'Nina']);
    assert.deepEqual(m.exports.residenteAprovado('criar_agente vigia'), ['Vigia']);
    assert.equal(m.exports.residenteAprovado('git push'), null);
    """
    resultado = subprocess.run([node, "-e", script], cwd=cliente, capture_output=True, text=True, timeout=30)
    assert resultado.returncode == 0, resultado.stderr
