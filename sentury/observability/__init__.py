"""Guarda traces locais em memória sem interferir no turno.

O buffer tem limite e reduz payloads grandes. Falhas de observabilidade não
derrubam o agente, e os dados não são enviados para fora da máquina.
"""
from .tracer import record_turn_trace, get_recent_traces, clear_traces
from .interventions import record_intervention, get_interventions, clear_interventions

__all__ = [
    "record_turn_trace", "get_recent_traces", "clear_traces",
    "record_intervention", "get_interventions", "clear_interventions",
]
