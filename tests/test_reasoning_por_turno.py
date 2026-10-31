"""Raciocínio interno não atravessa o contrato público do turno.

Planner, responder e classificador são objetos compartilhados entre turnos e
entre requisições. `last_reasoning_summary` fica neles até alguém sobrescrever,
então um turno que não chame um deles herdaria a narração do turno passado. A
interface recebe estágios operacionais e o raciocínio por um evento próprio,
nunca misturado à resposta.
"""
import inspect

from sentury.harness.canal_do_turno import CanalDoTurno
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.state import AnalysisState


class _Motor:
    last_model = "do turno passado"
    last_reasoning_summary = "pensei na pergunta anterior"


class _Orq:
    def __init__(self):
        self.planner, self.responder = _Motor(), _Motor()
        self._clean_reasoning_for_stream = SenturyOrchestrator._clean_reasoning_for_stream


def test_motores_sao_zerados_ao_abrir_o_canal_do_turno():
    orq = _Orq()
    CanalDoTurno(orq, AnalysisState("s", "u"))
    for motor in (orq.planner, orq.responder):
        assert motor.last_model is None
        assert motor.last_reasoning_summary is None


def test_reasoning_vai_por_canal_proprio_com_um_stage_e_sem_repetir():
    """O primeiro raciocínio vem com um stage, para a tela não ficar muda; o
    texto do stage não entra no teste. O mesmo trecho não se repete quando o
    laço replaneja."""
    eventos = []
    canal = CanalDoTurno(_Orq(), AnalysisState("s", "u"), eventos.append)
    pensamento = "Vou conferir o arquivo antes de responder, porque o nome pode estar errado."
    canal.emit_reasoning(pensamento)
    canal.emit_reasoning(pensamento)
    canal.emit_reasoning("Agora comparo as duas versões do resultado para ver o que mudou.")

    tipos = [e["type"] for e in eventos]
    assert tipos == ["stage", "reasoning", "reasoning"]
    assert all(e["type"] != "message" for e in eventos)


def test_harness_remove_todos_os_campos_de_reasoning_bruto():
    fonte = inspect.getsource(SenturyOrchestrator._decorate_harness)
    for campo in (
        "planner_reasoning_summary",
        "responder_reasoning_summary",
        "council_reasoning_summary",
        "reasoning_summary",
    ):
        assert campo in fonte
    assert 'harness.pop(key, None)' in fonte
