"""Agentic Mutation: o agente alterando o próprio core, sob governança.

Nada aqui muda o runtime ao vivo. Toda mutação nasce numa cópia isolada, é
testada contra a baseline de onde partiu, e a promoção é decisão humana com
responsável registrado.

Três peças:

- `registro`: o que foi tentado, o que sobreviveu, o que morreu e por quê.
- `isolamento`: onde a mutação trabalha, via git worktree.
- `ciclo`: as duas juntas, para não existir registro sem cópia nem cópia sem
  registro.
- `replay`: repetir turnos que já aconteceram, contra baseline e candidata.
- `marcador`: liga um trecho de código à mutação que o criou.
"""
from . import ciclo, isolamento, marcador, registro, replay
from .ciclo import (
    avaliar,
    concluir_avaliacao,
    construida,
    estado_geral,
    limpar_copia,
    promover,
    propor,
    reverter,
)
from .registro import ESTADOS, Mutacao, carregar, historico, linhagem, listar

__all__ = [
    "ESTADOS", "Mutacao", "avaliar", "carregar", "ciclo", "concluir_avaliacao",
    "construida", "estado_geral", "historico", "isolamento", "limpar_copia",
    "linhagem", "listar", "marcador", "promover", "propor", "registro", "replay",
    "reverter",
]
