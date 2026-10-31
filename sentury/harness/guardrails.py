"""Verifica a resposta final sem acoplar novas checagens ao orquestrador.

Guardrails ativos pedem uma reescrita e depois saneiam o texto, se necessário.
Observadores apenas registram achados, sem bloquear a resposta.
"""
from dataclasses import dataclass
from typing import Callable, List, Optional

from .grounding import _CURRENCY_RE, classify_numbers, evidence_text, find_ungrounded, texto_para_conferir
from .state import AnalysisState


@dataclass
class GuardrailResult:
    name: str
    tripwire_triggered: bool
    reason: str = ""
    correction_instruction: Optional[str] = None
    sanitize: Optional[Callable[[str], str]] = None
    # Contagem por classe (grounded/derived/suspect): vira telemetria.
    detail: Optional[dict] = None
    # O aviso chega ao usuário; apenas registrar um número sem lastro não o protege.
    aviso: Optional[str] = None


def currency_guardrail(state: AnalysisState, text: str) -> GuardrailResult:
    """Avisa quando um valor monetário não tem lastro na evidência da sessão.

    A checagem considera o `numero` extraído, não o símbolo da moeda ou o setor.
    """
    achados = find_ungrounded(texto_para_conferir(text), evidence_text(state))
    if not achados["currency"]:
        return GuardrailResult(name="grounding_currency", tripwire_triggered=False)
    # O regex de dinheiro e guloso com `[\d.,]+` e leva o ponto final da frase
    # junto ("R$ 98.000." vira "R$ 98.000.:" no aviso).
    sem_lastro = ", ".join(str(v).rstrip(".,") for v in achados["currency"])
    return GuardrailResult(
        name="grounding_currency",
        tripwire_triggered=False,
        reason=f"valor monetário sem lastro: {achados['currency']}",
        aviso=(f"Não encontrei lastro para {sem_lastro}: esse valor não apareceu "
               f"em nenhum resultado desta sessão. Confira antes de usar."),
    )


def decimal_observer(state: AnalysisState, text: str) -> GuardrailResult:
    """Separa números com lastro, derivados e suspeitos sem bloquear a resposta.

    Diferenças calculadas a partir da evidência não devem ser tratadas como
    números inventados.
    """
    classes = classify_numbers(texto_para_conferir(text), evidence_text(state))
    suspeitos = classes["suspect"]
    return GuardrailResult(
        name="grounding_decimals",
        tripwire_triggered=False,
        reason=(f"numeros sem origem: {suspeitos}" if suspeitos else ""),
        detail={k: len(v) for k, v in classes.items()},
    )


# Não há bloqueio automático: a detecção por expressão regular pode atingir
# valores legítimos. Os observadores avisam sem alterar a resposta.
OUTPUT_GUARDRAILS: List[Callable[[AnalysisState, str], GuardrailResult]] = []
OBSERVERS: List[Callable[[AnalysisState, str], GuardrailResult]] = [
    currency_guardrail, decimal_observer,
]


def veredito(text: str, houve_aviso: bool) -> Optional[bool]:
    """Devolve ao RobinBandit um sinal de qualidade baseado em evidência.

    Sem valor monetário não há o que julgar; `None` evita marcar como fiel uma
    resposta que não foi testada por esta checagem.
    """
    if houve_aviso:
        return False
    return True if _CURRENCY_RE.search(text or "") else None
