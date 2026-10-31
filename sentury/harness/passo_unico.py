"""Uma chamada por volta: o modelo usa uma ferramenta ou responde.

As chamadas nativas de ferramenta evitam um planejamento textual separado e
seu reparo de JSON. Texto sem chamada já encerra o turno. O prompt de decisão
permanece curto para não competir com os esquemas das ferramentas; provedores
sem suporte a chamadas nativas continuam pelo caminho de texto.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

logger = logging.getLogger(__name__)

# A lista de ferramentas chega pelo canal estruturado; repetir os esquemas no
# prompt gastaria contexto e poderia introduzir instruções contraditórias.
INSTRUCAO_DO_PASSO = """
Como agir neste turno

Você tem ferramentas de verdade. Para agir, chame a ferramenta: anunciar a ação
sem uma chamada não executa nada e deixa o pedido sem resultado.

Diga, na mesma mensagem da chamada, uma frase curta em primeira pessoa com o que
vai fazer e por quê ("Vou listar a pasta para ver o que tem nela"). Essa frase é
a única coisa que a pessoa lê enquanto espera — sem ela o sistema executa em
silêncio e ela só descobre no fim. Não prometa resultado nem número: o passo
ainda não rodou. Frase e chamada juntas; frase sozinha, não.

Quando já tiver o que precisa, responda em texto. A resposta em texto encerra o
turno, então só escreva quando de fato tiver a informação — e diga com franqueza
o que não conseguiu obter, em vez de afirmar ter feito o que não fez.

Você pode alternar: chamar, ver o resultado, chamar de novo, e só então
responder. Cada volta te devolve o resultado da anterior.
""".strip()


# Delimita o contrato de planejamento que o passo único substitui.
_INICIO_DO_CONTRATO = "Seu objetivo é gerar um plano"
_FIM_DO_CONTRATO = "### Ferramentas Disponíveis e seus Argumentos:"


def base_do_passo(prompt_do_planner: str) -> str:
    """As regras do planner sem o contrato de JSON, com a instrucao do passo.

    No passo unico a ferramenta vai pela chamada do provedor: o contrato de
    responder em JSON levaria o modelo a escrever a chamada no texto.
    """
    texto = str(prompt_do_planner or "")
    inicio, fim = texto.find(_INICIO_DO_CONTRATO), texto.find(_FIM_DO_CONTRATO)
    if inicio < 0 or fim < inicio:
        return f"{INSTRUCAO_DO_PASSO}\n\n{texto}"
    marcador_memoria = "### Preferências e memória"
    regras_da_memoria = texto[texto.find(marcador_memoria):inicio].strip() if marcador_memoria in texto[:inicio] else ""
    from ..residentes.escopo import quem_e

    partes = [quem_e(), INSTRUCAO_DO_PASSO, regras_da_memoria, texto[fim:].strip()]
    return "\n\n".join(p for p in partes if p)


def _suporta_ferramentas(provider: Any) -> bool:
    """O provedor aceita `tools=` na chamada?

    Pergunta à assinatura em vez de manter uma lista de nomes de provedor: que
    envelheceria a cada adapter novo, silenciosamente.
    """
    # A declaracao vem antes da assinatura: uma cadeia sempre aceita `tools=`,
    # mas so ela sabe se a conta que vai responder usa o parametro.
    declarado = getattr(provider, "supports_tools", None)
    if declarado is not None:
        return bool(declarado)
    try:
        parametros = inspect.signature(provider.complete).parameters
    except (AttributeError, TypeError, ValueError):
        return False
    return "tools" in parametros


def ativo(provider: Any) -> bool:
    """O passo único vale neste turno?"""
    from ..config import settings

    if not getattr(settings, "SENTURY_NATIVE_TOOLS", False):
        return False
    return _suporta_ferramentas(provider)


