"""O que o Sentury notou no uso real e pode virar mutação.

Os sinais saem dos traços gravados do conjunto de desenvolvimento, que é o uso
de verdade; o de avaliação tem falhas plantadas de propósito. Pedir permissão é
o fluxo normal, não falha, então não conta. Cada sinal agrupa o que se repete
(mesma ferramenta, mesmo tipo de erro) e guarda o exemplo mais recente.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List

from . import replay

# Fluxo esperado, não sintoma.
_NAO_E_FALHA = {"EXEC_PRECISA_PERMISSAO"}
JANELA_DIAS = 30


def _falha(resultado: Any) -> str:
    """O tipo de falha do resultado, ou vazio quando deu certo."""
    if not isinstance(resultado, dict):
        return ""
    codigo = str(resultado.get("codigo_erro") or "")
    if codigo in _NAO_E_FALHA or resultado.get("precisa_permissao"):
        return ""
    if resultado.get("recusado"):
        return codigo or "recusado"
    if resultado.get("erro") or resultado.get("ok") is False:
        return codigo or "erro"
    return ""


def listar(limite: int = 8) -> List[Dict[str, Any]]:
    corte = time.time() - JANELA_DIAS * 86400
    grupos: Dict[tuple, Dict[str, Any]] = {}
    for traco in replay.listar("desenvolvimento"):
        if (traco.gravado_em or 0) < corte:
            continue
        for registro in traco.resultados_ferramentas or []:
            tipo = _falha(registro.get("resultado"))
            if not tipo:
                continue
            ferramenta = str(registro.get("tool") or "")
            chave = (ferramenta, tipo)
            resultado = registro["resultado"]
            grupo = grupos.setdefault(chave, {
                "id": hashlib.sha1(f"{ferramenta}:{tipo}".encode()).hexdigest()[:10],
                "ferramenta": ferramenta, "tipo": tipo, "vezes": 0, "quando": 0.0, "tracos": [],
            })
            grupo["vezes"] += 1
            grupo["tracos"].append(traco.id)
            if (traco.gravado_em or 0) >= grupo["quando"]:
                grupo["quando"] = traco.gravado_em or 0
                grupo["pedido"] = str(traco.mensagem or "")[:240]
                grupo["erro"] = str(resultado.get("erro") or resultado.get("motivo") or "")[:300]
    return sorted(grupos.values(), key=lambda g: (-g["vezes"], -g["quando"]))[:limite]


def por_id(sinal_id: str) -> Dict[str, Any]:
    return next((sinal for sinal in listar(limite=100) if sinal["id"] == sinal_id), {})


__all__ = ["listar", "por_id"]
