"""A resposta do turno que acabou sem texto, nos dois caminhos (nativo e em texto).

Quando as voltas acabam com o modelo ainda pedindo ferramenta, uma chamada a
mais, na mesma conversa e sem ferramentas, pede o que ja foi achado. Se nem
assim vier texto, a resposta diz que parou e por que. Nunca vazia.
"""
from __future__ import annotations

import json

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PEDIDO_DE_FECHAMENTO = (
    "As voltas deste turno acabaram. Responda agora à pessoa, sem chamar ferramenta, "
    "com o que você já encontrou e fez. Se algo ficou faltando, diga o quê."
)


def _rodou(ferramentas: List[str]) -> str:
    feitas = ", ".join(dict.fromkeys(f for f in ferramentas if f))
    return f" Cheguei a rodar: {feitas}." if feitas else ""


def _sem_texto(ferramentas: List[str]) -> str:
    return (f"Parei no limite de passos deste turno sem fechar a resposta.{_rodou(ferramentas)} "
            "Se quiser, peça para eu continuar de onde parei.")


_MOTIVO_POR_TIPO = {
    "rate_limit": "o provedor limitou o uso por agora",
    "credit": "a conta do provedor está sem crédito",
    "auth": "a chave do provedor foi recusada",
    "network": "o provedor demorou demais para responder",
    "content_policy": "o modelo recusou o pedido pela política de conteúdo dele",
}

RECUSA_DE_CONTEUDO = ("O modelo recusou este pedido pela política de conteúdo dele, e nenhum outro "
                      "modelo do modo aceitou. Tentar de novo dá o mesmo resultado: reformule o pedido "
                      "ou troque o modelo do modo.")


def recusou_por_conteudo(exc: BaseException) -> bool:
    """Todos os provedores do modo recusaram por política de conteúdo."""
    from .pedido_grande import _falha_da_cadeia

    tipos = getattr(_falha_da_cadeia(exc), "tipos", None) or []
    return bool(tipos) and all(t == "content_policy" for t in tipos)


def falha_ao_responder(exc: BaseException) -> str:
    if recusou_por_conteudo(exc):
        return RECUSA_DE_CONTEUDO
    from .pedido_grande import _falha_da_cadeia
    falha = _falha_da_cadeia(exc)
    if (getattr(exc, "motivo_publico", None) or
            any(d.get("motivo") for d in (getattr(falha, "falhas", None) or {}).values())):
        return _provedor_falhou(exc, [])
    return "Desculpe, tive um problema ao processar a resposta. Pode tentar novamente?"


def recusas_do_turno() -> Optional[List[Dict[str, Any]]]:
    """Quem recusou neste turno e foi trocado por outro modelo, para a tela avisar."""
    try:
        from robinbandit.chain import recusas_do_turno as _recusas
    except Exception:
        return None
    return _recusas() or None


def _motivo_do_provedor(exc: Exception) -> str:
    from .pedido_grande import _falha_da_cadeia

    falha = _falha_da_cadeia(exc) or exc
    motivos = [d.get("motivo") for d in (getattr(falha, "falhas", None) or {}).values() if d.get("motivo")]
    if motivos:
        return "; ".join(dict.fromkeys(motivos))
    if getattr(falha, "motivo_publico", None):
        return falha.motivo_publico
    # A cadeia ja classificou cada falha (FalhaDaCadeia.tipos); o texto dela
    # ("todos os provedores falharam") nao traz o 429.
    for tipo in reversed(list(getattr(exc, "tipos", None) or [])):
        if tipo in _MOTIVO_POR_TIPO:
            return _MOTIVO_POR_TIPO[tipo]
    texto = str(exc).lower()
    for marca, motivo in (("429", "o provedor limitou o uso por agora"),
                          ("402", "a conta do provedor está sem crédito"),
                          ("401", "a chave do provedor foi recusada"),
                          ("403", "a chave do provedor foi recusada"),
                          ("timeout", "o provedor demorou demais para responder")):
        if marca in texto:
            return motivo
    return "o provedor falhou"


def identificar_modelo(orquestrador, telemetria):
    motor = orquestrador.responder if getattr(orquestrador.responder, "last_model", None) else orquestrador.planner
    telemetria["model"] = telemetria.get("model") or getattr(motor, "last_model", None)
    telemetria["provider"] = telemetria.get("provider") or getattr(motor, "last_provider", None) or telemetria["model"]


def _provedor_falhou(exc: Exception, ferramentas: List[str]) -> str:
    """Quem parou foi o provedor, nao o limite de passos: a mensagem diz o motivo."""
    return (f"O modelo não respondeu agora: {_motivo_do_provedor(exc)}.{_rodou(ferramentas)} "
            "Tente de novo em instantes ou troque o modelo do modo.")


async def responder_no_limite(orquestrador: Any, state: Any, user_message: str,
                              ferramentas: List[str]) -> str:
    """Uma chamada sem ferramentas na conversa do laco; senao, a frase honesta."""
    from ..llm.action_parser import extract_plain_text
    from .conversa import historico_para_o_modelo, montar
    from .resposta_direta import sem_chamada_vazada

    prompt = orquestrador.turno.prompt_do_passo or ""
    if not prompt:
        return _sem_texto(ferramentas)
    mensagens = montar(prompt, historico_para_o_modelo(state.history, user_message),
                       user_message, "", nativo=True)
    mensagens.append({"role": "user", "content": PEDIDO_DE_FECHAMENTO})
    try:
        try:
            bruto = await orquestrador.planner.complete(mensagens, temperature=0.2)
        except TypeError:
            # Provedor que não recebe `temperature`, como no planejamento.
            bruto = await orquestrador.planner.complete(mensagens)
    except Exception as exc:
        logger.warning("Chamada de fechamento falhou: %s", exc)
        return _provedor_falhou(exc, ferramentas)
    # No caminho em texto o modelo responde no envelope `action: respond`.
    from .resposta_direta import desembrulhar
    from ..llm.action_parser import _first_json_object

    try:
        dentro = desembrulhar(json.loads(_first_json_object(str(bruto or "")) or "null"))
    except ValueError:
        dentro = None
    texto, _ = sem_chamada_vazada(dentro if dentro is not None else extract_plain_text(bruto or ""))
    return texto or _sem_texto(ferramentas)
