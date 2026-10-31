"""O que ele diz antes de executar.

Quando o modelo devolve `tool_calls` nativos, ele costuma escrever junto o
motivo: "vou olhar a pasta primeiro, depois contar as tabelas". Esse texto
chegava no orquestrador e era descartado: o plano era montado só dos calls
(`orchestrator._generate_plan`, ramo `_native`). O usuário via a ferramenta
rodar sem nunca ler por quê.

Como `_generate_plan` roda uma vez por volta do laço, guardar esse texto dá
narração **a cada execução**, e não só no começo do turno.

Duas coisas que este módulo existe para impedir:

- **Narração não é resposta.** Se o texto for longo, é o modelo respondendo no
  lugar de agir; mostrar aquilo como "vou fazer" entrega no meio do turno algo
  que a resposta final ainda vai contradizer.
- **Repetição vira ruído.** Na segunda volta o modelo costuma repetir a mesma
  frase. Uma linha igual à anterior não acrescenta nada.
"""
from __future__ import annotations

import re
from typing import Optional

# Acima disto não é anúncio do próximo passo, é resposta antecipada.
TETO = 320

_BLOCO_DE_CODIGO = re.compile(r"```.*?```", re.DOTALL)
_ESPACO = re.compile(r"\s+")


def _nua(texto: str) -> str:
    return _ESPACO.sub(" ", str(texto or "")).strip().lower()


def limpar(bruto: Optional[str]) -> Optional[str]:
    """O texto pronto para a tela, ou None quando não há narração ali."""
    texto = _BLOCO_DE_CODIGO.sub(" ", str(bruto or ""))
    texto = _ESPACO.sub(" ", texto).strip()
    if not texto:
        return None
    # Sobrou só a pontuação que cercava o JSON.
    if not re.search(r"[a-zà-ÿ]{3}", texto, re.IGNORECASE):
        return None
    if len(texto) > TETO:
        return None
    return texto


class Narrador:
    """Guarda o que já foi dito, para não repetir."""

    def __init__(self) -> None:
        self._ditas: set = set()

    def proxima(self, bruto: Optional[str]) -> Optional[str]:
        texto = limpar(bruto)
        if texto is None:
            return None
        chave = _nua(texto)
        if chave in self._ditas:
            return None
        self._ditas.add(chave)
        return texto


def apos_planejar(orquestrador, decision_log, narrador, emitir_raciocinio) -> None:
    """O que todo planejamento deixa para trás: telemetria, raciocínio e fala.

    Os dois ramos de planejamento (primeiro plano e replanejamento) repetiam
    estas mesmas linhas. Juntar aqui é o que impede a fala de existir só num
    deles: e foi assim que o replanejamento ficou mudo antes.
    """
    decision_log["planner_model"] = getattr(orquestrador.planner, "last_model", None)
    resumo = getattr(orquestrador.planner, "last_reasoning_summary", None)
    decision_log["planner_reasoning_summary"] = resumo
    decision_log["planner_contract"] = orquestrador.turno.contrato
    emitir_raciocinio(resumo)
    # A fala NAO vira evento de turno. Emitida solta, ela ia para o topo e as
    # voltas seguintes empilhavam em cima: tres frases juntas e uma execucao
    # embaixo, sem dizer qual frase era de qual. Guardada aqui, ela sai no
    # `tool_start` do primeiro passo desta volta: colada no que anuncia.
    orquestrador.turno.fala_da_volta = narrador.proxima(
        orquestrador.turno.narracao)


def tirar_fala(orquestrador) -> Optional[str]:
    """A fala guardada pela volta atual, uma vez só.

    Consumir no primeiro passo é o que faz a frase anunciar a execução em vez
    de se repetir em cada um dos passos daquela volta.
    """
    fala = orquestrador.turno.fala_da_volta
    orquestrador.turno.fala_da_volta = None
    return fala
