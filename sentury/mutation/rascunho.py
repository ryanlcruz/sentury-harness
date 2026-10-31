"""Uma frase vira mutação: o modelo redige alvo e hipótese, a pessoa confere.

Sem modelo disponível, o rascunho sai da própria frase e do sinal: a tela nunca
trava esperando o modelo, e a pessoa ajusta o texto antes de abrir a cópia.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _pedido(texto: str, sinal: Dict[str, Any]) -> str:
    partes = [f"O que a pessoa escreveu: {texto or '(nada; parta do sinal)'}"]
    if sinal:
        partes.append(
            f"Sinal do uso real: a ferramenta `{sinal.get('ferramenta')}` falhou {sinal.get('vezes')} vez(es) "
            f"({sinal.get('tipo')}). Último pedido: {sinal.get('pedido', '')}. Erro: {sinal.get('erro', '')}")
    return "\n\n".join(partes)


def _sem_modelo(texto: str, sinal: Dict[str, Any]) -> Dict[str, str]:
    if sinal:
        alvo = f"falha de {sinal.get('ferramenta')}"
        observacao = f"{sinal.get('ferramenta')} falhou {sinal.get('vezes')} vez(es): {sinal.get('erro', '')}"[:300]
    else:
        alvo, observacao = " ".join((texto or "").split()[:6]), ""
    return {"alvo": alvo, "hipotese": texto or f"O turno deixa de falhar em {sinal.get('ferramenta')}.",
            "observacao": observacao}


def _ler(bruto: Any) -> Optional[Dict[str, str]]:
    from ..llm.action_parser import _first_json_object, _repair_json, _strip_reasoning

    candidato = _first_json_object(_strip_reasoning(str(bruto or "")))
    if not candidato:
        return None
    try:
        dados = json.loads(candidato)
    except ValueError:
        try:
            dados = json.loads(_repair_json(candidato))
        except ValueError:
            return None
    if not isinstance(dados, dict) or not str(dados.get("alvo") or "").strip() or not str(dados.get("hipotese") or "").strip():
        return None
    return {chave: " ".join(str(dados.get(chave) or "").split())[:600] for chave in ("alvo", "hipotese", "observacao")}


async def redigir(texto: str, sinal: Dict[str, Any], modelo: Any) -> Dict[str, Any]:
    texto = " ".join(str(texto or "").split())
    if modelo is not None:
        from ..context.base import _texto_base

        mensagens = [{"role": "system", "content": _texto_base("MUTACAO_RASCUNHO")},
                     {"role": "user", "content": _pedido(texto, sinal)}]
        try:
            lido = _ler(await modelo.complete(mensagens, temperature=0.2, complexity="simple"))
            if lido:
                return {**lido, "pelo_modelo": True}
        except Exception:
            logger.info("O rascunho da mutacao saiu sem modelo.", exc_info=True)
    return {**_sem_modelo(texto, sinal), "pelo_modelo": False}


__all__ = ["redigir"]
