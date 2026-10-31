"""O que o turno guardou: lembranças e skills, para o chat mostrar e oferecer desfazer.

Sai dos resultados das próprias ferramentas (`memoria` e `aprender_skill`), então
o que aparece é o que foi gravado de fato, não uma promessa do texto da resposta.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

# Escritas de skill que o `desfazer` volta; "nada a mudar" e erro não entram.
_ESCRITAS_DE_SKILL = ("criada", "acrescentada", "corrigida", "anexado")


def do_turno(resultados: Iterable[Any], aprendido: Optional[str] = None) -> List[Dict[str, str]]:
    itens: List[Dict[str, str]] = []
    skills: Dict[str, Dict[str, str]] = {}
    for registro in resultados or []:
        if not isinstance(registro, dict) or not isinstance(registro.get("result"), dict):
            continue
        ferramenta, resultado = registro.get("tool"), registro["result"]
        if ferramenta in ("memoria", "salvar_memoria") and resultado.get("status") == "salvo" and resultado.get("fato"):
            itens.append({"tipo": "memoria", "texto": str(resultado["fato"])})
        elif ferramenta == "aprender_skill" and resultado.get("status") in _ESCRITAS_DE_SKILL and resultado.get("skill"):
            # Uma linha por skill: o desfazer volta a última escrita dela.
            nome = str(resultado["skill"])
            if nome not in skills:
                skills[nome] = {"tipo": "skill", "nome": nome}
                itens.append(skills[nome])
            skills[nome]["acao"] = str(resultado["status"])
    if aprendido and not any(item.get("texto") == aprendido for item in itens):
        itens.insert(0, {"tipo": "memoria", "texto": str(aprendido)})
    return itens


__all__ = ["do_turno"]
