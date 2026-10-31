"""A pessoa colou algo sensivel na conversa: o agente avisa, e segue.

Nao redige nem bloqueia. O dado pode ser de teste, pode ser da propria pessoa
num uso pessoal, e trocar o valor quebraria o que ela pediu para fazer com ele.
O que cabe e dizer, uma vez, que aquilo e sensivel: como um colega diria.

Telefone e e-mail ficam de fora de proposito: o Sentury e generalista e de uso
pessoal, e avisar a cada e-mail seria o aviso que ninguem mais le. Pelo mesmo
motivo CPF e cartao so contam com digito verificador valido: um numero
qualquer de 11 digitos nao e CPF.
"""
from __future__ import annotations

import re
from typing import List

_CPF = re.compile(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)")
_CARTAO = re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")

ROTULOS = {
    "credencial": "uma chave ou senha",
    "cpf": "um CPF",
    "cartao": "um número de cartão",
}


def _cpf_valido(digitos: str) -> bool:
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(digitos[:tamanho]))
        if (soma * 10 % 11) % 10 != int(digitos[tamanho]):
            return False
    return True


def _luhn(digitos: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digitos)):
        n = int(d)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def detectar(texto: str) -> List[str]:
    """Os tipos de dado sensivel no texto, na ordem de `ROTULOS`."""
    from ..exec.saida import tem_segredo

    bruto = str(texto or "")
    achados = []
    if tem_segredo(bruto):
        achados.append("credencial")
    if any(_cpf_valido("".join(m.groups())) for m in _CPF.finditer(bruto)):
        achados.append("cpf")
    if any(_luhn(re.sub(r"\D", "", m.group(0))) for m in _CARTAO.finditer(bruto)):
        achados.append("cartao")
    return achados


def nota_para_o_modelo(tipos: List[str]) -> str:
    """A linha que entra no turno. Vazia quando nao ha nada."""
    if not tipos:
        return ""
    lista = ", ".join(ROTULOS[t] for t in tipos)
    return (
        f"[AVISO DE DADO SENSIVEL] A mensagem do usuario parece conter {lista}. "
        "Diga isso em UMA frase, no inicio, sem repetir o valor (ex.: \"vi que voce colou "
        "o que parece ser uma chave; ela fica no historico desta conversa\"). Nao recuse, "
        "nao peca confirmacao e nao troque o valor: siga com o pedido normalmente."
    )


__all__ = ["ROTULOS", "detectar", "nota_para_o_modelo"]
