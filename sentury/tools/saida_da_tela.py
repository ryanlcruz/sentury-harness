"""A saída de comando, script e código, do jeito que o card da conversa mostra.

O resumo da ferramenta (`harness/resumo_de_ferramenta.py`) corta em 420
caracteres e escolhe um campo só: a saída normal esconde o erro, e a falha de
um teste fica depois do corte. Aqui vai a saída inteira, em linhas, com a
origem de cada uma (`out` ou `err`) na ordem em que saíram, o código de saída
e, quando dá para ler, uma linha de resumo ("1 de 71 testes falhou").

Isto vai só para a tela. O modelo continua recebendo o resultado de sempre.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..exec.saida import limpar_ansi, redigir_segredos
from .registry import com_propriedade

# As ferramentas cuja saída aparece no card como terminal.
TERMINAIS = com_propriedade("saida_terminal")

# O que a tela recebe no máximo. O card recolhe bem antes disso; o teto é para
# um build de milhares de linhas não virar um evento de megabytes.
MAX_LINHAS = 400
MAX_CHARS_POR_LINHA = 2000

Linha = Tuple[str, str]


def _limpa(texto: str) -> str:
    texto = redigir_segredos(limpar_ansi(str(texto or "")))
    return texto if len(texto) <= MAX_CHARS_POR_LINHA else texto[:MAX_CHARS_POR_LINHA] + " …"


def _separar(texto: Any, origem: str) -> List[Linha]:
    if not isinstance(texto, str) or not texto:
        return []
    linhas = texto.split("\n")
    if linhas and linhas[-1] == "":
        linhas.pop()
    return [(origem, linha) for linha in linhas]


def linhas_do_resultado(tool: str, resultado: Dict[str, Any]) -> List[Linha]:
    """As linhas em ordem. Sem a ordem de chegada (o processo não foi
    acompanhado), a saída vem antes do erro."""
    ordenadas = resultado.get("linhas")
    if isinstance(ordenadas, list) and ordenadas:
        return [(str(o), str(t)) for o, t in ordenadas]
    if tool == "executar_python":
        return _separar(resultado.get("saida"), "out") + _separar(resultado.get("erro"), "err")
    saida = resultado.get("saida") if resultado.get("saida") is not None else resultado.get("stdout")
    erro = resultado.get("erro") if resultado.get("erro") is not None else resultado.get("stderr")
    if saida is None and erro is None:
        saida = resultado.get("saida_parcial")
    return _separar(saida, "out") + _separar(erro, "err")


def codigo_de_saida(tool: str, resultado: Dict[str, Any]) -> Optional[int]:
    """O código de saída, ou None enquanto roda. No Python, `codigo` é o
    fonte que rodou: ali o código é 1 quando houve erro."""
    if tool == "executar_python":
        return 1 if resultado.get("erro") else 0
    if resultado.get("rodando") or resultado.get("em_segundo_plano"):
        return None
    codigo = resultado.get("codigo")
    if isinstance(codigo, bool) or not isinstance(codigo, int):
        return None if resultado.get("ok") is None else (0 if resultado.get("ok") else 1)
    return codigo


_PYTEST = re.compile(r"(?:(\d+) failed)?[, ]*(?:(\d+) passed)?[^\n]* in [\d.]+s")
_PYTEST_PARTES = re.compile(r"(\d+) (failed|passed|errors?|skipped)")
_TSC = re.compile(r"Found (\d+) errors?")


def resumo(linhas: Iterable[Linha]) -> Optional[str]:
    """Uma linha do que aconteceu, lida da própria saída. Só para o que se
    reconhece com certeza (pytest, tsc); o resto fica sem resumo."""
    textos = [t for _, t in linhas]
    for texto in reversed(textos[-40:]):
        limpo = texto.strip().strip("=").strip()
        if " in " in limpo and _PYTEST.search(limpo) and _PYTEST_PARTES.search(limpo):
            contas = {}
            for numero, tipo in _PYTEST_PARTES.findall(limpo):
                contas[tipo.rstrip("s") if tipo.startswith("error") else tipo] = int(numero)
            falhas = contas.get("failed", 0) + contas.get("error", 0)
            total = falhas + contas.get("passed", 0)
            if not total:
                continue
            if falhas:
                return f"{falhas} de {total} testes {'falhou' if falhas == 1 else 'falharam'}"
            return f"{total} de {total} testes passaram"
        achou = _TSC.search(limpo)
        if achou:
            n = int(achou.group(1))
            return f"{n} erro{'s' if n != 1 else ''} de tipo"
    return None


def montar(tool: str, resultado: Any) -> Optional[Dict[str, Any]]:
    """O que o card mostra, ou None para quem não é terminal."""
    if tool not in TERMINAIS or not isinstance(resultado, dict):
        return None
    todas = linhas_do_resultado(tool, resultado)
    cortadas = int(resultado.get("linhas_cortadas") or 0)
    if len(todas) > MAX_LINHAS:
        cortadas += len(todas) - MAX_LINHAS
        todas = todas[-MAX_LINHAS:]
    linhas = [[origem if origem in ("out", "err") else "out", _limpa(texto)] for origem, texto in todas]
    return {
        "linhas": linhas,
        "cortadas": cortadas,
        "codigo": codigo_de_saida(tool, resultado),
        "resumo": resumo(todas),
    }


class AoVivo:
    """As linhas que saem do processo, levadas à tela em lotes.

    As linhas chegam da thread que lê o processo; a tela recebe no laço de
    eventos, no máximo a cada `INTERVALO` segundos, para um build barulhento
    não mandar um evento por linha. Sem ninguém ouvindo o turno, não faz nada.
    """

    INTERVALO = 0.2

    def __init__(self, tool: str) -> None:
        import asyncio
        import threading

        from ..harness.emissor import EMISSOR

        self.tool = tool
        self._emitir = EMISSOR.get()
        self._laco = asyncio.get_running_loop() if self._emitir else None
        self._lote: List[Linha] = []
        self._trava = threading.Lock()
        self._agendado = False
        self._acabou = False

    def __call__(self, origem: str, texto: str) -> None:
        if self._laco is None:
            return
        with self._trava:
            if self._acabou:
                return
            self._lote.append((origem, texto))
            if self._agendado:
                return
            self._agendado = True
        try:
            self._laco.call_soon_threadsafe(self._laco.call_later, self.INTERVALO, self.despejar)
        except RuntimeError:  # laço já fechado
            pass

    def despejar(self) -> None:
        with self._trava:
            lote, self._lote, self._agendado = self._lote, [], False
        if not lote or self._emitir is None:
            return
        try:
            self._emitir({
                "type": "saida_parcial", "ferramenta": self.tool,
                "linhas": [[origem, _limpa(texto)] for origem, texto in lote],
            })
        except Exception:
            pass

    def encerrar(self) -> None:
        """A saída inteira vai no evento final; o que sobrou do lote sai antes."""
        self.despejar()
        with self._trava:
            self._acabou = True


def emitir_final(tool: str, resultado: Any) -> None:
    """Manda ao card a saída completa e tira as linhas do que vai ao modelo."""
    tela = montar(tool, resultado)
    tirar_do_resultado(resultado)
    if tela is None:
        return
    from ..harness.emissor import emitir

    emitir({"type": "saida", "ferramenta": tool, **tela})


def tirar_do_resultado(resultado: Any) -> None:
    """As linhas em ordem são da tela: ao modelo continua indo `saida` e
    `erro`, que já têm o mesmo texto."""
    if isinstance(resultado, dict):
        resultado.pop("linhas", None)
        resultado.pop("linhas_cortadas", None)


__all__ = [
    "AoVivo", "TERMINAIS", "codigo_de_saida", "emitir_final", "linhas_do_resultado", "montar", "resumo",
    "tirar_do_resultado",
]
