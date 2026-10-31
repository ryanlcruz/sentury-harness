"""Traduz níveis de esforço do Sentury para os valores aceitos pelo provedor.

A barra da UI fala em `low|medium|high|xhigh`. O que vai no
payload é outra coisa: cada modelo aceita um subconjunto (o deepseek-v4-pro no
OpenRouter nem sempre honra `low`; alguns modelos do Groq só ligam/desligam).
A EFFORT_POLICY faz essa tradução, chaveada por (modo, nível), sem trocar o modo
que o usuário escolheu: só ajusta o quanto se pensa dentro
dele.

O nível do request vive num contextvar (mesmo padrão do Ultra), então nenhuma
assinatura do harness muda: quem monta o payload lê daqui.
"""
import contextvars
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

LEVELS = ("low", "medium", "high", "xhigh")

# (modo, nível lógico) → effort mandado ao provedor. `None` = não mandar nada
# (deixa o default do modelo). Override por deploy/tenant; vazia = usa o default
# abaixo, que a sondagem validou.
EFFORT_POLICY: Dict[Tuple[Optional[str], str], Optional[str]] = {}

# `low` desliga o raciocínio quando o provedor aceita `none`; os demais níveis
# preservam o pedido para modelos que distinguem esforço intermediário.
_DEFAULT_PROVIDER_EFFORT: Dict[str, Optional[str]] = {
    "low": "none", "medium": "medium", "high": "high", "xhigh": "xhigh",
}


@dataclass
class EffortState:
    """`base` é o que a pessoa pediu; `active` é o que vale no turno."""
    base: str
    active: str

    @classmethod
    def new(cls, base: str) -> "EffortState":
        b = normalize(base) or "medium"
        return cls(base=b, active=b)


_effort_ctx: contextvars.ContextVar = contextvars.ContextVar("sentury_effort", default=None)


def normalize(level: Optional[str]) -> Optional[str]:
    lv = (level or "").strip().lower()
    return lv if lv in LEVELS else None


def use_effort(level: str):
    """Fixa o nível base do request. Devolve token: passe pro clear_effort()
    no finally (reset restaura o contexto anterior; em stream, dentro do
    generator, não em volta dele)."""
    return _effort_ctx.set(EffortState.new(level))


def clear_effort(token) -> None:
    try:
        _effort_ctx.reset(token)
    except (ValueError, LookupError):
        # token de outro contexto (task filha): ignorar é seguro.
        pass


def effort_state() -> Optional[EffortState]:
    return _effort_ctx.get()


def active_effort() -> Optional[str]:
    st = _effort_ctx.get()
    return st.active if st else None


def provider_effort_for(level: Optional[str], mode: Optional[str] = None) -> Optional[str]:
    """Nível lógico → effort do provedor, conforme a EFFORT_POLICY."""
    lv = normalize(level)
    if lv is None:
        return None
    if (mode, lv) in EFFORT_POLICY:
        return EFFORT_POLICY[(mode, lv)]
    if (None, lv) in EFFORT_POLICY:
        return EFFORT_POLICY[(None, lv)]
    return _DEFAULT_PROVIDER_EFFORT.get(lv)


# Compatibilidade pública: a política lógica de eficiência continua no Sentury,
# mas a tradução/compatibilidade do payload pertence ao gateway RobinBandit.
from robinbandit.reasoning import (  # noqa: E402,F401
    build_reasoning_payload,
    is_reasoning_rejection,
    mark_reasoning_control_rejected,
    reasoning_control_allowed,
)
