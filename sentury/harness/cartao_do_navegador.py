"""O cartão do navegador no chat, montado a partir dos eventos `navegador`.

O mesmo cálculo roda nos dois lados: aqui, para guardar o resumo na
mensagem (o cartão volta igual ao recarregar), e no client
(`features/chat/navegador.ts`), para mostrar ao vivo. Um turno tem um cartão
só: cada chamada ao `browser` acrescenta os passos dela.

Eventos (emitidos por `tools/browser_registry.py`):
    {"type": "navegador", "fase": "inicio", "site": ..., "passos": [{"acao", "rotulo"}]}
    {"type": "navegador", "fase": "passo", "indice": i, "status": "running"|"ok"|"error", "leitura": ...}
    {"type": "navegador", "fase": "fim", "status": "ok"|"parou"|"erro", "motivo": ..., "site": ...}
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional


def novo() -> Dict[str, Any]:
    return {"site": "", "passos": [], "status": "rodando", "motivo": "",
            "textos": 0, "prints": 0, "inicio": None, "duracao_ms": 0,
            "retomada": False, "_base": 0}


def aplicar(cartao: Optional[Dict[str, Any]], evento: Dict[str, Any],
            agora: Optional[float] = None) -> Dict[str, Any]:
    cartao = cartao or novo()
    agora = time.time() if agora is None else agora
    fase = evento.get("fase")
    if fase == "inicio":
        if cartao["inicio"] is None:
            cartao["inicio"] = agora
        cartao["_base"] = len(cartao["passos"])
        cartao["site"] = str(evento.get("site") or cartao["site"])
        cartao["status"], cartao["motivo"] = "rodando", ""
        if evento.get("retomada"):
            cartao["retomada"] = True
        for p in evento.get("passos") or []:
            cartao["passos"].append({"acao": str(p.get("acao") or ""), "rotulo": str(p.get("rotulo") or ""),
                                     "status": "pendente", "leitura": ""})
    elif fase == "passo":
        i = cartao["_base"] + int(evento.get("indice") or 0)
        if 0 <= i < len(cartao["passos"]):
            passo = cartao["passos"][i]
            passo["status"] = str(evento.get("status") or "ok")
            leitura = str(evento.get("leitura") or "")
            if leitura and not passo["leitura"] and passo["status"] != "running":
                passo["leitura"] = leitura
                cartao["textos" if leitura == "texto" else "prints"] += 1
    elif fase == "fim":
        cartao["status"] = str(evento.get("status") or "ok")
        cartao["motivo"] = str(evento.get("motivo") or "")
        cartao["site"] = str(evento.get("site") or cartao["site"])
        # Passo que nao chegou a rodar fica como estava (pendente): e o que
        # sobrou do roteiro, e o cartao mostra onde parou.
        for passo in cartao["passos"]:
            if passo["status"] == "running":
                passo["status"] = "error" if cartao["status"] != "ok" else "ok"
    if cartao["inicio"] is not None:
        cartao["duracao_ms"] = int((agora - cartao["inicio"]) * 1000)
    return cartao


def para_guardar(cartao: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """O que vai para a mensagem: sem os campos de trabalho."""
    if not cartao or not cartao.get("passos"):
        return None
    saida = {k: v for k, v in cartao.items() if not k.startswith("_") and k != "inicio"}
    if saida.get("status") == "rodando":
        saida["status"] = "ok"
    return saida


__all__ = ["aplicar", "novo", "para_guardar"]
