"""A telemetria do turno diz do que é feita a última chamada do planejador.

As fatias somam exatamente o que foi enviado: sistema, esquema de ferramentas,
histórico e a última mensagem (pedido e contexto do turno). Turnos ao mesmo
tempo não misturam as medidas.
"""
import asyncio
import json

from sentury.harness import fatias
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState
from tests.test_descoberta_multilingue import _Nativo
from tests.test_orchestrator import EchoResponder, _store


def _tamanho(m):
    return len(m["content"] if isinstance(m["content"], str) else json.dumps(m["content"], ensure_ascii=False))


async def test_o_turno_traz_as_fatias_da_ultima_chamada():
    planner = _Nativo(["Pronto."])
    orq = SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())
    estado = AnalysisState.new("s", "u")
    estado.history = [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "Olá."}]
    resultado = await orq.handle_message(estado, "liste os arquivos da pasta")
    medida = resultado["telemetry"]["fatias"]
    chamada = planner.chamadas[-1]
    enviado = sum(_tamanho(m) for m in chamada["messages"])
    assert medida["sistema"] > 0 and medida["ferramentas"] > 0 and medida["pedido_e_contexto"] > 0
    assert medida["sistema"] + medida["historico"] + medida["pedido_e_contexto"] == enviado
    assert medida["ferramentas"] == len(json.dumps(chamada["tools"], ensure_ascii=False))


async def test_turnos_ao_mesmo_tempo_nao_misturam():
    async def turno(tamanho):
        fatias.medir([{"role": "system", "content": "x" * tamanho}])
        await asyncio.sleep(0)
        return fatias.da_ultima_chamada()["sistema"]

    assert await asyncio.gather(turno(10), turno(20)) == [10, 20]
