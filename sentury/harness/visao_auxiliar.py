"""O print do computer use descrito em texto por um modelo que enxerga.

Com o print anexado como imagem, o Router passa a usar só quem enxerga, e a
imagem vai em toda chamada seguinte do turno. Quando o provedor da frente da
cadeia não enxerga (a pessoa escolheu um modelo de texto, ou é o mais barato),
isso troca o modelo da conversa por causa de um print. Então um modelo de
visão auxiliar descreve a tela, e o turno segue em texto. O auxiliar é a
própria cadeia do Router com a imagem: ela escolhe
quem enxerga só para essa chamada.

`SENTURY_COMPUTADOR_VISAO`: `imagem`, `descricao` ou `auto` (padrão). No
`auto`, descrição quando o provedor da frente não enxerga e outro da cadeia
enxerga; sem ninguém que enxergue, fica a imagem, e o Router diz que não há.

No Reforçado e no Dedicado, "o da frente" é a conta escolhida. Dedicado com
conta que não enxerga: quem descreve é o Router, fora da conta, e a conta
segue o turno em texto.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_llm: Any = None

_PROMPT = (
    "Descreva este print de tela para quem não pode vê-lo e vai agir nela. Diga o app e a janela, o que "
    "está aberto, os textos importantes, botões, campos, listas e mensagens de erro, e onde cada coisa "
    "fica em coordenadas deste print ({largura} x {altura}, origem no canto de cima à esquerda). Não "
    "invente o que não aparece; se algo estiver ilegível, diga."
)
_TETO = 4000


def registrar(llm: Any) -> None:
    """A cadeia do Router que descreve. O `main` registra a do responder."""
    global _llm
    _llm = llm


def _nome(provedor: Any) -> str:
    return getattr(provedor, "name", type(provedor).__name__)


def _enxerga(router: Any, provedor: Any) -> bool:
    """O Router declara quem enxerga; o `RobinGateway` guarda isso no roteador de dentro."""
    for alvo in (router, getattr(router, "router", None)):
        capacidades = getattr(alvo, "_capabilities", None)
        if callable(capacidades):
            try:
                return "vision" in capacidades(_nome(provedor))
            except Exception:
                return False
    return False


def _escolhida_enxerga() -> Optional[bool]:
    """None no Router; no Reforçado/Dedicado, se a conta escolhida enxerga."""
    try:
        from robinbandit.sentury import ultra_capabilities
    except Exception:
        return None
    capacidades = ultra_capabilities()
    return None if capacidades is None else "vision" in capacidades


def modo() -> str:
    """`imagem` ou `descricao` para o próximo print."""
    from ..config import settings

    escolha = str(getattr(settings, "SENTURY_COMPUTADOR_VISAO", "auto") or "auto").strip().lower()
    if escolha == "imagem" or _llm is None:
        return "imagem"
    if escolha == "descricao":
        return "descricao"
    router = getattr(_llm, "router", None)
    provedores: List[Any] = list(getattr(_llm, "providers", None) or [])
    if router is None or not provedores:
        return "imagem"
    escolhida = _escolhida_enxerga()
    if escolhida is True:
        return "imagem"
    if escolhida is None:
        try:
            ordem = router.order(provedores)
        except Exception:
            ordem = provedores
        if not ordem or _enxerga(router, ordem[0]):
            return "imagem"
    return "descricao" if any(_enxerga(router, p) for p in provedores) else "imagem"


async def descrever(data_url: str, largura: int, altura: int, elementos: str = "",
                    fora_da_conta: bool = False) -> Optional[str]:
    """A descrição do print, ou None (sem cadeia, ou ninguém respondeu):
    quem chama volta para a imagem. `fora_da_conta`: quem descreve é o
    Router, mesmo que a conta escolhida enxergue (ela acabou de falhar)."""
    if _llm is None or not str(data_url or "").startswith("data:image/"):
        return None
    texto = _PROMPT.format(largura=largura, altura=altura)
    if elementos:
        texto += "\n\nOs elementos que a acessibilidade numerou nesta tela, para você citar pelo número:\n" + elementos
    mensagens = [{"role": "user", "content": texto, "imagens": [{"nome": "tela.png", "data_url": data_url}]}]
    try:
        por_fora = getattr(_llm, "descrever_com_quem_ve", None)
        if (fora_da_conta or _escolhida_enxerga() is False) and callable(por_fora):
            # A conta escolhida não enxerga: o Router descreve, sem passar a
            # descrição pela conta só para ela repetir.
            resposta = await por_fora(texto, [data_url])
        else:
            resposta = await _llm.complete(mensagens, temperature=0.1)
    except Exception:
        logger.warning("A descrição do print falhou; o print vai como imagem.", exc_info=True)
        return None
    resposta = str(resposta or "").strip()
    return resposta[:_TETO] or None


__all__ = ["descrever", "modo", "registrar"]
