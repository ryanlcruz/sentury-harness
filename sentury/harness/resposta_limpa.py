"""Remove cercas vazias e sintaxe de arquivo que não pertencem à resposta.

Duplicação de plano não pode ser removida depois sem arriscar texto legítimo;
ela deve ser evitada no prompt.
"""
from __future__ import annotations

import re
from typing import Any

# ```json\n``` ou ```\n```: cerca aberta e fechada sem nada dentro.
_CERCA_VAZIA = re.compile(r"```[a-zA-Z0-9_+-]*\s*```", re.MULTILINE)
# A marca do checklist com o sinal de portão/opcional, no começo da linha.
_MARCA_DE_ARQUIVO = re.compile(r"^(\s*)-?\s*\[\s*[xX ]?\s*\]([*!])\s*", re.MULTILINE)
# `_Agenda: ..._` e `_Requisito: ..._` são linhas do arquivo, não da conversa.
_LINHA_DE_ARQUIVO = re.compile(r"^\s*_(Agenda|Requisitos?):.*_\s*$", re.MULTILINE | re.IGNORECASE)


def limpar(texto: str) -> str:
    """Tira da resposta o que é formato de arquivo ou cerca sem conteúdo.

    Conservador de propósito: só mexe no que é inequivocamente interno. Apagar
    texto legítimo é pior que deixar passar uma marca.
    """
    if not texto:
        return texto
    limpo = _CERCA_VAZIA.sub("", texto)
    # A tarefa continua; o que sai é só o sinal que o arquivo usa.
    limpo = _MARCA_DE_ARQUIVO.sub(r"\1- ", limpo)
    limpo = _LINHA_DE_ARQUIVO.sub("", limpo)
    # A remoção deixa buracos de três ou mais quebras.
    return re.sub(r"\n{3,}", "\n\n", limpo).strip()


# O card já mostra o plano inteiro. Sem esta linha, o responder reescrevia fase
# por fase na prosa e a tela ficava com o mesmo conteúdo duas vezes.
AVISO_DO_CARD = (
    "O plano que você acabou de montar JÁ APARECE na tela, como card, com todas "
    "as tarefas, os portões e o que é opcional. NÃO repita o checklist na "
    "resposta: diga em duas ou três frases o que o plano cobre, o que ele espera "
    "de decisão, e qual é o primeiro passo. Nunca escreva a sintaxe do arquivo "
    "(`- [ ]`, `[ ]!`, `[ ]*`, `_Agenda:_`, `_Requisito:_`) na conversa — ela é "
    "do arquivo, e quem lê a tela não sabe o que significa."
)


def avisar_do_card(state: Any, ferramenta: Any) -> bool:
    """Diz ao responder que o plano já está na tela, quando ele acabou de mexer
    num. Uma vez por turno: repetir o aviso gasta contexto sem mudar nada."""
    from .bloco import FERRAMENTAS_DE_PLANO

    if str(ferramenta or "") not in FERRAMENTAS_DE_PLANO:
        return False
    if any(AVISO_DO_CARD == str(m.get("content") or "") for m in state.history):
        return False
    state.history.append({"role": "system", "content": AVISO_DO_CARD})
    return True
