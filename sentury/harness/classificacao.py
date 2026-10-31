"""Se o resultado de uma ferramenta foi sucesso, falha ou pergunta pendente.

Tres estados, nao dois. "Nao veio erro" nunca foi prova de sucesso: a recusa do
shell devolve `{"ok": False, "recusado": True}` e passava como se tivesse
rodado: o turno seguia, o orcamento nao contava a falha e o modelo podia dizer
que executou.
"""
from __future__ import annotations

from typing import Any


def pendente(resultado: Any) -> bool:
    """Pergunta ao dono. Nao e falha do modelo e nao queima o teto de falhas."""
    return isinstance(resultado, dict) and bool(resultado.get("precisa_permissao"))


def recusado(resultado: Any) -> bool:
    """A politica ou o dono disse nao.

    Continua contando como falha para o laco (o passo nao aconteceu), mas na
    TELA e outra coisa: "o agente errou" e "a politica barrou" pedem reacoes
    diferentes de quem le, e o triangulo vermelho dizia a primeira nos dois
    casos.
    """
    return isinstance(resultado, dict) and bool(resultado.get("recusado"))


def falhou(resultado: Any) -> bool:
    if not isinstance(resultado, dict):
        return False
    if pendente(resultado):
        return False
    if resultado.get("recusado") or resultado.get("timeout") or resultado.get("ok") is False:
        return True
    # O codigo de saida e o veredito do processo, e vem antes de tudo.
    for campo in ("codigo", "codigo_saida"):
        valor = resultado.get(campo)
        if isinstance(valor, int):
            return valor != 0
    # Sucesso declarado ganha de `erro`: nesses retornos `erro` carrega o
    # stderr, e comando que termina bem escreve aviso ali o tempo todo (git e
    # pip fazem isso). Sem esta ordem, sucesso virava falha falsa.
    if resultado.get("ok") is True:
        return False
    return bool(resultado.get("erro"))


def motivo(resultado: Any) -> str:
    """A frase que explica a falha, venha ela de onde vier."""
    if not isinstance(resultado, dict):
        return ""
    return str(
        resultado.get("erro") or resultado.get("motivo") or resultado.get("stderr") or ""
    ).strip()
