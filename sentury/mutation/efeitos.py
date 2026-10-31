"""Dependências do turno só de leitura, para o replay repetir sem agir.

Ferramenta que age no mundo o catálogo já recusa no replay. Sobram as escritas
que o próprio turno faz nas dependências: lembrar um fato, salvar a
experiência, gravar ou apagar uma skill, criar uma ação no store. Aqui elas
são recusadas e anotadas. A leitura segue igual, e o relatório diz o que o
turno teria escrito.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Tuple

# O que cada dependência escreve, e o que a recusa devolve no lugar: o mesmo
# formato do "não escreveu", para o turno seguir pelo caminho de sempre.
ESCRITAS: Dict[str, Dict[str, Any]] = {
    "memory": {"remember": False, "forget": False, "delete": 0, "clear": None},
    "experience_library": {"save": None},
    "skills": {"save": None, "delete": 0},
    "store": {
        "criar_acao": {"erro": "escrita recusada no replay"},
        "atualizar_acao": None,
    },
}


class SomenteLeitura:
    """Repassa tudo ao alvo, menos as escritas declaradas em `ESCRITAS`."""

    def __init__(self, alvo: Any, nome: str, anotar: Callable[[Dict[str, Any]], None]):
        object.__setattr__(self, "_alvo", alvo)
        object.__setattr__(self, "_nome", nome)
        object.__setattr__(self, "_anotar", anotar)
        object.__setattr__(self, "_escritas", ESCRITAS.get(nome, {}))

    def __getattr__(self, atributo: str) -> Any:
        valor = getattr(self._alvo, atributo)
        if atributo not in self._escritas or not callable(valor):
            return valor
        neutro = self._escritas[atributo]
        efeito = {"dependencia": self._nome, "metodo": atributo}
        if inspect.iscoroutinefunction(valor):
            async def recusar_async(*_a: Any, **_k: Any) -> Any:
                self._anotar(efeito)
                return neutro
            return recusar_async

        def recusar(*_a: Any, **_k: Any) -> Any:
            self._anotar(efeito)
            return neutro
        return recusar

    def __setattr__(self, atributo: str, valor: Any) -> None:
        setattr(self._alvo, atributo, valor)


def somente_leitura(**dependencias: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Embrulha cada dependência pelo nome e devolve a lista onde as recusas caem.

    Dependência ausente (`None`) passa como está: o orquestrador já sabe
    trabalhar sem ela.
    """
    recusadas: List[Dict[str, Any]] = []
    embrulhadas = {
        nome: (SomenteLeitura(alvo, nome, recusadas.append) if alvo is not None else None)
        for nome, alvo in dependencias.items()
    }
    return embrulhadas, recusadas
