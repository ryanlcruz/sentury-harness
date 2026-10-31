"""Fatos locais do turno e servidores MCP, sem presumir dados de um setor."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Servidores MCP mudam devagar; reler a cada turno pagaria I/O por nada.
_MCP_CACHE: Dict[str, Any] = {"quando": 0.0, "texto": None}

def ambiente_do_turno(session_id: str = "") -> Optional[str]:
    """Onde o comando vai rodar. Sem isto o agente supoe Linux.

    O rascunho entra aqui, e nao no prompt fixo, porque o caminho muda por
    sessao: no prompt ele seria uma instrucao sem endereco.
    """
    try:
        from ..tools.shell import agora as _linhas_de_agora, ambiente
    except Exception:
        return None
    amb = ambiente()
    linhas = [
        "### AMBIENTE",
        f"- sistema: {amb['sistema']}",
        f"- listar arquivos: `{amb['listar']}`",
        f"- diretorio de trabalho: {amb['diretorio']}",
    ]
    try:
        from ..tools.ambiente import _sistema

        local = _sistema()
        linhas.extend([
            f"- localização pelos sinais locais: {local['onde_roda']}",
            f"- container: {local['container']}; VM de nuvem: {local['vm_de_nuvem']}; serviço systemd: {local['servico_systemd']}",
            "A localização não concede permissão. Ações críticas pedem confirmação pontual, inclusive com Tudo liberado; recusas permanentes continuam valendo.",
        ])
    except (OSError, KeyError):
        linhas.append("- localização: indisponível aqui; isso não concede permissão")
    try:
        from ..tools.arquivos import pasta_de_rascunho

        linhas.append(
            f"- rascunho (escrita livre, nao e do usuario): {pasta_de_rascunho(session_id)}"
        )
    except Exception:
        pass
    linhas.append("Use o comando que existe NESTE sistema; nao suponha Linux.")
    linhas.extend(_linhas_de_agora())
    return "\n".join(linhas)


def mcp() -> Optional[str]:
    """Servidores MCP conectados, para o planner poder escolher.

    Só o registro é lido; conectar em cada servidor para listar ferramentas
    custaria segundos em todo turno. O nome da ferramenta o modelo descobre
    pelo erro do próprio servidor, que já diz quais existem.
    """
    agora = time.time()
    if agora - float(_MCP_CACHE.get("quando") or 0) < 120:
        return _MCP_CACHE.get("texto")

    try:
        from ..external import mcp_registry

        servidores = [s for s in mcp_registry.listar() if s.get("ativo", True)]
    except Exception:
        servidores = []

    if not servidores:
        _MCP_CACHE.update(quando=agora, texto=None)
        return None

    nomes = "\n".join(f'- {s.get("nome")}' for s in servidores)
    texto = (
        "### SERVIDORES MCP CONECTADOS\n"
        f"{nomes}\n"
        "Use `usar_mcp(servidor, ferramenta, argumentos)`. Se errar o nome da "
        "ferramenta, o servidor responde dizendo quais existem."
    )
    _MCP_CACHE.update(quando=agora, texto=texto)
    return texto


# O argumento que diz em que o passo mexe, na ordem em que vale mais.
_CHAVES_DE_ALVO = ("caminho", "path", "arquivo", "comando", "url", "nome", "id")


def _alvo(argumentos: Dict[str, Any]) -> str:
    for chave in _CHAVES_DE_ALVO:
        valor = str((argumentos or {}).get(chave) or "").strip()
        if valor:
            return f"{chave}: {valor[:80]}"
    return ""


def _ha_quanto(desde: float, agora: float) -> str:
    segundos = max(0, int(agora - desde))
    return f"há {segundos} s" if segundos < 60 else f"há {segundos // 60} min"


def outras_conversas(session_id: str = "", agora: Optional[float] = None) -> Optional[str]:
    """O que roda agora nas outras conversas. Sem isto, duas conversas podem
    repetir o mesmo trabalho ou gravar o mesmo arquivo sem saber uma da outra.
    É fato, não ordem: o modelo decide se avisa a pessoa."""
    from .registro_do_turno import em_curso_fora_de

    turnos = em_curso_fora_de(session_id)
    if not turnos:
        return None
    agora = time.time() if agora is None else agora
    linhas = ["### OUTRAS CONVERSAS RODANDO AGORA"]
    for turno in turnos[:5]:
        pedido = " ".join(str(turno.get("pedido") or "").split())
        pedido = pedido if len(pedido) <= 120 else pedido[:120] + "…"
        rodando = [p for p in turno.get("passos") or [] if p.get("status") == "rodando"]
        if rodando:
            passo = rodando[-1]
            alvo = _alvo(passo.get("argumentos") or {})
            agora_faz = f"agora em `{passo.get('ferramenta')}`" + (f" ({alvo})" if alvo else "")
        else:
            agora_faz = "entre uma ação e outra"
        desde = _ha_quanto(float(turno.get("iniciado_em") or agora), agora)
        linhas.append(f'- outra conversa, {desde}: "{pedido}"; {agora_faz}')
    linhas.append(
        "Elas rodam ao mesmo tempo que esta, na mesma máquina. Se este pedido for mexer no "
        "mesmo arquivo ou repetir o que já roda lá, considere dizer isso à pessoa antes de "
        "seguir: duas conversas gravando o mesmo arquivo perdem uma das escritas."
    )
    return "\n".join(linhas)


def pedido_do_turno(state: Any) -> str:
    return next((str(m.get("content") or "") for m in reversed(getattr(state, "history", None) or [])
                 if isinstance(m, dict) and m.get("role") == "user"), "")


async def memoria_da_pessoa(memoria: Any, state: Any) -> Optional[str]:
    """O que o Sentury sabe da pessoa, com as lembranças antigas que o pedido toca."""
    if not memoria:
        return None
    from ..memory.user_memory import build_memory_context

    return build_memory_context(await memoria.all(state.user_id), pedido=pedido_do_turno(state))


def decisoes(state: Any) -> Optional[str]:
    """As decisões da equipe que o pedido pode tocar: as recentes e as antigas
    parecidas com ele. É fato com data, não ordem."""
    pedido = pedido_do_turno(state)
    try:
        from ..memory.decisoes import para_o_turno
        from ..residentes.escopo import agente_do_turno

        # O residente lembra só do que viveu; o Sentury principal vê a equipe toda.
        agente = agente_do_turno()
        return para_o_turno(pedido, agente=agente.nome if agente else "")
    except Exception:
        logger.warning("Não consegui ler as decisões da equipe.", exc_info=True)
        return None


def equipe(state: Any) -> Optional[str]:
    """A equipe de residentes, no turno do Sentury principal. O residente não recebe:
    ele fala com os colegas e a equipe dele já está na identidade."""
    try:
        from ..residentes.cliente import url_da_hq
        from ..residentes.escopo import agente_do_turno

        # Com a HQ remota o estado mora lá; o Sentury consulta com `pedir_ao_agente`.
        if agente_do_turno() is not None or url_da_hq():
            return None
        from ..residentes.hq import retrato_para_o_sentury

        return retrato_para_o_sentury() or None
    except Exception:
        logger.warning("Não consegui montar o retrato da equipe.", exc_info=True)
        return None


__all__ = ["ambiente_do_turno", "decisoes", "equipe", "mcp", "outras_conversas"]
