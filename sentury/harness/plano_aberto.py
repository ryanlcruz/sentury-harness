"""O plano recente entra como estado; o modelo decide se ele serve ao pedido."""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)
DIAS_DE_VALIDADE = 14
_PREFIXO = "Há trabalho em aberto:"


def planos_em_aberto(trabalho: Any = None) -> list[dict[str, Any]]:
    from ..memory import plano

    try:
        todos = plano.listar(trabalho)
        abertos = [p for p in todos if int(p.get("faltam") or 0) > 0]
        return sorted(abertos, key=lambda p: _mexido_em(p.get("plano"), trabalho), reverse=True)
    except Exception:
        logger.debug("Falha ao listar os planos", exc_info=True)
        return []


def _mexido_em(nome: Any, trabalho: Any = None) -> float:
    from ..memory import plano

    try:
        return (plano.raiz_dos_planos(trabalho) / str(nome) / "tarefas.md").stat().st_mtime
    except (OSError, TypeError, ValueError):
        return 0.0


def _curto(valor: Any, limite: int = 120) -> str:
    return " ".join(str(valor or "").split())[:limite]


def linha_de_contexto(trabalho: Any = None) -> str | None:
    abertos = planos_em_aberto(trabalho)
    if not abertos:
        return None
    alvo = abertos[0]
    quando = _mexido_em(alvo.get("plano"), trabalho)
    if not quando or (time.time() - quando) / 86400 > DIAS_DE_VALIDADE:
        return None
    feitas = int(alvo.get("feitas") or 0)
    faltam = int(alvo.get("faltam") or 0)
    partes = [f"{_PREFIXO} plano `{_curto(alvo.get('plano'))}`, {feitas} de {feitas + faltam} tarefas fechadas."]
    proxima = alvo.get("proxima") or {}
    if proxima:
        partes.append(f"Próxima: {_curto(proxima.get('id'), 24)} — {_curto(proxima.get('titulo'))}.")
        if proxima.get("gate"):
            partes.append("Portão pendente; as etapas posteriores aguardam aprovação da pessoa.")
            opcoes = [_curto(o, 60) for o in (proxima.get("opcoes") or [])[:4]]
            if opcoes:
                partes.append("Opções previstas: " + "; ".join(opcoes) + ".")
        if proxima.get("agenda"):
            partes.append(f"Agenda registrada: {_curto(proxima['agenda'], 80)}.")
        if proxima.get("tentativas"):
            partes.append(f"Tentativas registradas: {int(proxima['tentativas'])}.")
    if len(abertos) > 1:
        partes.append(f"Outros planos abertos: {len(abertos) - 1}.")
    partes.append("Detalhes em ver_plano. A relação com o pedido atual não foi determinada.")
    return " ".join(partes)


def aplicar_no_turno(state: Any, mensagem: Any = None, trabalho: Any = None) -> bool:
    try:
        linha = linha_de_contexto(trabalho)
    except Exception:
        logger.debug("Falha ao ler o estado do plano", exc_info=True)
        return False
    existentes = [m for m in state.history if m.get("role") == "system"
                  and str(m.get("content") or "").startswith(_PREFIXO)]
    if linha and len(existentes) == 1 and existentes[0].get("content") == linha:
        return False
    # Uma atualização substitui o fato antigo, inclusive quando o plano fecha.
    state.history[:] = [m for m in state.history if m not in existentes]
    if not linha:
        return False
    state.history.append({"role": "system", "content": linha, "priority": "NORMAL"})
    return True
