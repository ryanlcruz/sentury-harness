"""De quem é a vez no computador: do agente ou da pessoa.

O Sentury usa o mouse e o teclado da própria pessoa. Alguns passos são dela:
login, senha, código de dois fatores, CAPTCHA, pagamento. Nesses, a vez passa
para ela de dois jeitos: o agente pede (`computador` com `pedir_a_pessoa`) ou
ela toma (o botão Assumir do cartão, que também para o turno).

Com a vez da pessoa, o `computador` recusa tudo, inclusive o print e a lista de
janelas: ela pode estar digitando uma senha. A recusa vale para qualquer
conversa, porque o computador é um só. Só a pessoa devolve, pelo botão
Devolver do cartão.

A época sobe a cada troca. Um gesto que começou na vez do agente e terminou na
da pessoa não vale: o print tirado depois dele é descartado.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Dict

AGENTE = "agente"
PESSOA = "pessoa"


@dataclass(frozen=True)
class Vez:
    com: str = AGENTE
    sessao: str = ""
    motivo: str = ""
    desde: float = 0.0
    epoca: int = 0

    @property
    def da_pessoa(self) -> bool:
        return self.com == PESSOA


_trava = threading.Lock()
_vez = Vez()


def atual() -> Vez:
    with _trava:
        return _vez


def passar_para_pessoa(sessao: str, motivo: str) -> Vez:
    """A vez vai para a pessoa. Se já era dela, só o motivo muda."""
    global _vez
    motivo = " ".join(str(motivo or "").split())[:160]
    with _trava:
        epoca = _vez.epoca if _vez.da_pessoa else _vez.epoca + 1
        _vez = Vez(PESSOA, sessao, motivo, time.time(), epoca)
        return _vez


def devolver() -> Vez:
    """A vez volta para o agente. Devolver o que já era dele não muda nada."""
    global _vez
    with _trava:
        if _vez.da_pessoa:
            _vez = Vez(AGENTE, "", "", time.time(), _vez.epoca + 1)
        return _vez


def publica(vez: Vez) -> Dict[str, object]:
    return asdict(vez)


def _limpar_para_testes() -> None:
    global _vez
    with _trava:
        _vez = Vez()


__all__ = ["AGENTE", "PESSOA", "Vez", "atual", "devolver", "passar_para_pessoa", "publica"]
