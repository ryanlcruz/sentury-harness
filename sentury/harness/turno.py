"""O que é de um turno só e não pode vazar para outro.

O orquestrador é um para o processo inteiro, e a conversa da pessoa, o
residente e o agendamento rodam turnos ao mesmo tempo nele. O estado do turno
mora numa variável de contexto: cada tarefa assíncrona enxerga o próprio. O
turno que terminou continua legível por quem o chamou, até o próximo começar.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class Turno:
    # Um modelo, um laço: a ferramenta vai pela chamada nativa do provedor.
    passo_unico: bool = False
    # O texto da volta que já é a resposta.
    resposta_direta: Optional[str] = None
    # A resposta que passou pela conferência de afirmação de arquivo.
    resposta_conferida: Optional[str] = None
    # O "vou fazer X" que veio junto das chamadas, e a fala que vai à tela.
    narracao: Optional[str] = None
    fala_da_volta: Optional[str] = None
    # A última chamada ao modelo, como chegou e como foi lida.
    resposta_bruta: Optional[str] = None
    dados_do_plano: Any = None
    contrato: Optional[str] = None
    chamada_em_texto: bool = False
    reparos_json: int = 0
    prompt_do_passo: str = ""
    # O que a descoberta pôs na mesa nesta volta.
    capacidades_achadas: List[Any] = field(default_factory=list)
    capacidades: Set[str] = field(default_factory=set)
    # A conferência de números da resposta, para a telemetria.
    grounding: Optional[Dict[str, Any]] = None
    grounding_avisou: bool = False


_ATUAL: contextvars.ContextVar[Optional[Turno]] = contextvars.ContextVar("turno_do_orquestrador", default=None)


def atual() -> Turno:
    turno = _ATUAL.get()
    if turno is None:
        turno = Turno()
        _ATUAL.set(turno)
    return turno


def novo() -> Turno:
    turno = Turno()
    _ATUAL.set(turno)
    return turno
