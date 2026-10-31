"""O cérebro do residente: um provedor e um modelo fixos, e o que fazer se cair.

`parar` termina a tarefa quando o modelo falha, como o Dedicado; `robinbandit`
devolve ao Router, como o Reforçado. Sem cérebro no manifesto, o turno usa o
Router inteiro.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

SE_CAIR = ("parar", "robinbandit")


class CerebroInvalido(ValueError):
    pass


def validar(cerebro: Any) -> Dict[str, str]:
    if cerebro in (None, "", {}):
        return {}
    if not isinstance(cerebro, dict):
        raise CerebroInvalido("o cérebro vai como {provedor, modelo, se_cair}")
    provedor = str(cerebro.get("provedor") or "").strip().lower()
    modelo = str(cerebro.get("modelo") or "").strip()
    se_cair = str(cerebro.get("se_cair") or "parar").strip().lower()
    if not provedor or not modelo:
        raise CerebroInvalido("o cérebro precisa de `provedor` e `modelo`")
    if se_cair not in SE_CAIR:
        raise CerebroInvalido(f"`se_cair` vai de {' ou '.join(SE_CAIR)}")
    # O esforço do turno do residente: um colega de tarefa simples roda no leve e custa menos.
    from ..llm.effort import LEVELS

    esforco = str(cerebro.get("esforco") or "").strip().lower()
    if esforco and esforco not in LEVELS:
        raise CerebroInvalido(f"`esforco` vai de {', '.join(LEVELS)}")
    conhecidos = provedores_conhecidos()
    if conhecidos and provedor not in conhecidos:
        raise CerebroInvalido(f"provedor '{provedor}' não existe no RobinBandit")
    return {"provedor": provedor, "modelo": modelo, "se_cair": se_cair, **({"esforco": esforco} if esforco else {})}


def _config():
    from pathlib import Path

    from robinbandit.config import RobinConfig

    from ..config import settings

    caminho = Path(settings.SENTURY_ROBINBANDIT_CONFIG)
    if not caminho.is_absolute():
        caminho = Path(__file__).resolve().parents[2] / caminho
    return RobinConfig.from_yaml(caminho)


def provedores_conhecidos() -> set:
    try:
        return set(_config().providers)
    except Exception:
        return set()


def provedor_do_turno(cerebro: Dict[str, str], config: Any, settings: Any = None,
                      na_mesa: bool = False) -> Optional[Any]:
    """O provedor que entra no `use_ultra_provider` do turno, ou None (Router). Na vez da Mesa,
    a queda do provedor cai no Router mesmo com "se cair: parar": a fala é curta e uma vez
    parada trava a conversa de todos. A tarefa dele segue a escolha do cérebro."""
    if not cerebro:
        return None
    from robinbandit.providers import ReinforcedProvider, UnavailableProvider, build_provider

    try:
        montado = build_provider(config, cerebro["provedor"], settings, models=[cerebro["modelo"]],
                                 name=cerebro["provedor"])
    except Exception as exc:
        montado = UnavailableProvider(cerebro["provedor"], str(exc))
    if montado is None:
        montado = UnavailableProvider(cerebro["provedor"], "sem credencial para este provedor")
    # O nome do grupo é o que o Robin lê para decidir: ultra_max não volta ao Router.
    parar = cerebro["se_cair"] == "parar" and not na_mesa
    return ReinforcedProvider([montado], name="ultra_max" if parar else "ultra")


def ouvir_respostas() -> None:
    """Liga o registro das respostas do modelo neste turno, para saber depois quem respondeu."""
    try:
        from robinbandit.chain import iniciar_gravacao

        iniciar_gravacao()
    except Exception:
        pass


def respondeu_so_o_ultimo_recurso(config: Any) -> bool:
    """O turno terminou no provedor de último recurso do roteador: nenhum modelo de verdade
    respondeu, e o texto é um aviso de falha, não a resposta do residente."""
    ultimo = str(getattr(config, "last_resort", "") or "").strip().lower()
    if not ultimo:
        return False
    try:
        from robinbandit.chain import respostas_do_turno
    except Exception:
        return False
    respostas = respostas_do_turno() or []
    return bool(respostas) and str(respostas[-1].get("provedor") or "").strip().lower() == ultimo
