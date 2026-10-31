"""Observações anteriores ficam disponíveis sem classificar a intenção do pedido."""
from __future__ import annotations

from typing import Any

from ..llm.prompts import build_tool_result_instruction

MAX_RESULTADOS = 8
MAX_CARACTERES = 1200


def extrair(state: Any, mensagem: str | None = None) -> list[dict[str, str]]:
    historico = list(state.history)
    cortes = [i for i, item in enumerate(historico)
              if item.get("role") == "user" and item.get("content") == mensagem]
    corte = cortes[-1] if mensagem is not None and cortes else len(historico)
    anteriores = [item for item in historico[:corte]
                  if item.get("role") == "system"
                  and "RESULTADO DA FERRAMENTA" in str(item.get("content", ""))]
    posteriores = "\n".join(str(item.get("content", "")) for item in historico[corte + 1:])
    persistidos = []
    ferramentas = set()
    for rid, resultado in sorted(state.results.items(), key=lambda par: (
            float(par[1].get("created_at") or 0), par[0])):
        ferramenta = str(resultado.get("tool") or "")
        # Um resumo substituído nesta volta não representa a observação anterior.
        if rid in posteriores or (ferramenta and ferramenta in posteriores):
            continue
        if not ferramenta:
            continue
        conteudo = build_tool_result_instruction(ferramenta, resultado.get("summary") or {})
        persistidos.append({"role": "system", "content": f"ID DO RESULTADO NA SESSÃO: '{rid}'\n{conteudo}"})
        ferramentas.add(ferramenta)
    mensagens = [item for item in anteriores
                 if not any(f in str(item.get("content", "")) for f in ferramentas)] + persistidos
    vistos = set()
    saida = []
    for item in mensagens:
        texto = str(item.get("content") or "")[:MAX_CARACTERES]
        if texto and texto not in vistos:
            vistos.add(texto)
            saida.append({"role": "system", "content": texto})
    return saida[-MAX_RESULTADOS:]
