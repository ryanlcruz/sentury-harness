"""Carrega os textos base do motor e deixa a sobreposição do operador separada.

Um prompt base ausente ou vazio causa erro na inicialização; seguir sem regras
seria uma falha silenciosa de segurança e comportamento.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "base"


class PromptAusente(RuntimeError):
    """O texto do motor não está onde deveria."""


@lru_cache(maxsize=None)
def _texto_base(nome: str) -> str:
    """O conteúdo de `context/base/<nome>.md`.

    Em cache: são dezenas de KB lidos a cada import de módulo que os usa, e o
    conteúdo não muda dentro de um processo. Quem edita em execução usa a
    sobreposição do operador, que é o caminho feito para isso.
    """
    arquivo = PASTA / f"{nome}.md"
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptAusente(
            f"o texto '{nome}' nao foi encontrado em {arquivo}. "
            "Sem ele o agente responde sem as regras que este arquivo carrega."
        ) from exc
    if not texto.strip():
        raise PromptAusente(f"o texto '{nome}' esta vazio em {arquivo}.")
    return texto


def nomes_disponiveis() -> list:
    """O que existe hoje: usado por teste e por quem for editar."""
    return sorted(p.stem for p in PASTA.glob("*.md"))
