"""Resumo persistível do computer use, irmão do cartão do navegador."""
from __future__ import annotations

from typing import Any, Dict, Optional


def novo() -> Dict[str, Any]:
    return {"gestos": [], "status": "rodando", "parado": False, "prints": 0, "leituras": 0,
            "janela": "", "objetivo": "", "turno": 0, "limite": 0, "retomada": False, "vez": None}


def aplicar(cartao: Optional[Dict[str, Any]], evento: Dict[str, Any]) -> Dict[str, Any]:
    cartao = cartao or novo()
    fase = str(evento.get("fase") or "")
    if fase == "sessao":
        cartao["status"] = str(evento.get("status") or "pronta")
        cartao["parado"] = cartao["status"] == "parada"
        if evento.get("retomada"):
            cartao["retomada"] = True
        return cartao
    if fase == "vez":
        # A vez da pessoa fica no cartão guardado: é nele que ela devolve.
        cartao["vez"] = {"com": str(evento.get("com") or ""), "motivo": str(evento.get("motivo") or "")}
        return cartao
    if fase != "gesto":
        return cartao
    if isinstance(evento.get("prints"), int):
        cartao["prints"] = max(int(cartao.get("prints") or 0), int(evento["prints"]))
    if isinstance(evento.get("leituras"), int):
        cartao["leituras"] = max(int(cartao.get("leituras") or 0), int(evento["leituras"]))
    for campo in ("janela", "objetivo"):
        if evento.get(campo):
            cartao[campo] = str(evento[campo])
    for campo in ("turno", "limite"):
        if isinstance(evento.get(campo), int):
            cartao[campo] = int(evento[campo])
    gesto = {
        "acao": str(evento.get("acao") or ""),
        "titulo": str(evento.get("titulo") or evento.get("acao") or ""),
        "detalhe": str(evento.get("fala") or evento.get("descricao") or ""),
        "status": str(evento.get("status") or "rodando"),
    }
    if evento.get("tecla"):
        gesto["tecla"] = str(evento["tecla"])
    gestos = cartao["gestos"]
    ultimo = gestos[-1] if gestos else None
    if ultimo and ultimo.get("status") == "rodando" and ultimo.get("titulo") == gesto["titulo"] \
            and gesto["status"] != "rodando":
        gestos[-1] = gesto
    else:
        gestos.append(gesto)
    cartao["status"] = "rodando"
    if gesto["status"] == "parado":
        cartao["status"], cartao["parado"] = "parada", True
    return cartao


def para_guardar(cartao: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cartao:
        return None
    saida = dict(cartao)
    if saida.get("status") == "rodando":
        saida["status"] = "pronta"
    return saida


__all__ = ["aplicar", "novo", "para_guardar"]
