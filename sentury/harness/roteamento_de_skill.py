"""Badge ou nome explícito ativa a skill; pedidos naturais cabem ao modelo."""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable, List, Optional, Set, Tuple

from .funcoes import skill_ligada

def explicita(user_message: str, procedurais: Set[str]) -> Optional[str]:
    """A skill citada pelo nome: pela interface (`[nome]`) ou pelo usuário."""
    texto = str(user_message or "").strip().lower()
    entre_colchetes = re.match(r"^\[([a-z0-9][a-z0-9_-]{1,80})\]", texto)
    if entre_colchetes:
        return entre_colchetes.group(1)
    # Do nome mais longo para o mais curto: `root-cause-analysis` antes de
    # `root-cause`, senão o prefixo rouba a skill mais específica.
    for nome in sorted(procedurais, key=len, reverse=True):
        if re.match(rf"^{re.escape(nome)}(?:\s|:|,|-)", texto):
            return nome
    # `/nome` em qualquer ponto da frase: é como o campo de texto insere a skill.
    for nome in sorted(procedurais, key=len, reverse=True):
        if re.search(rf"(?:^|\s)/{re.escape(nome)}(?=\s|$|[.,;:!?])", texto):
            return nome
    return None


def escolher(
    user_message: str,
    procedurais: Set[str],
    scan_skills: Callable[[], Iterable[Any]],
    funcoes: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """A skill explicitamente ativada (`funcao`, `explicit`)."""
    do_badge = skill_ligada(funcoes)
    if do_badge and do_badge in procedurais:
        return do_badge, "funcao"
    citada = explicita(user_message, procedurais)
    if citada:
        return citada, "explicit"
    return None, None
