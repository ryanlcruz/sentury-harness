"""O que vale para QUALQUER dominio. O resto e do pacote.

Este corpus e o que `buscar_conhecimento` recupera para responder pergunta
conceitual sem a LLM inventar definicao. Entrada de um setor mora no
`conhecimento.yaml` do pacote, e o pacote ativo soma as dele em
`knowledge/retriever.py`: o que o agente recupera tambem nao pode carregar
vocabulario de dominio para o generalista.
"""
from typing import Dict, List

FAQ_SENTURY: List[Dict[str, str]] = [
    {
        "id": 'limites-sem-simulacao',
        "titulo": 'O que o Sentury NÃO faz',
        "texto": (
            'O Sentury não simula cenários hipotéticos nem projeta resultados futuros '
            '(não há dado nem ferramenta para isso) e nunca inventa número, percentual '
            'ou causa. Todo dado apresentado vem de uma fonte que ele leu ou de um '
            'cálculo que ele rodou. Se não há dado para o que foi pedido, ele diz que '
            'não há, em vez de estimar.'
        ),
    },
]
