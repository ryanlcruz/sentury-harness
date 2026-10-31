"""O que voltou da ferramenta, em tamanho de tela.

A execução já aparecia na conversa, mas só até a metade: dava para ver o
comando e nunca o resultado. Quem assiste fica sabendo que algo rodou, não o
que rodar produziu: e aí o único jeito de conferir é esperar a resposta final
e confiar nela.

Aqui sai um preview curto: a saída de verdade quando existe, o motivo quando
falhou, e uma linha de achados quando o retorno é estruturado. Passa pelo mesmo
tratamento da saída de processo (corta pelas pontas, limpa cor de terminal,
redige credencial), porque preview que vaza chave é pior que preview nenhum.
"""
from __future__ import annotations

from typing import Any

# Cabe em três linhas de tela. Mais que isso vira scroll dentro do passo, e o
# passo é um aviso, não o documento.
TETO = 420


def _do_dicionario(resultado: dict) -> str:
    for campo in ("saida", "stdout", "erro", "motivo", "mensagem", "texto"):
        valor = resultado.get(campo)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()

    # Retorno estruturado: mostra o que o turno vai usar, não o dicionário cru.
    achados = []
    for chave, valor in resultado.items():
        if chave in ("codigo", "comando", "script", "conteudo"):
            continue
        if isinstance(valor, (int, float, bool)):
            achados.append(f"{chave}={valor}")
        elif isinstance(valor, (list, tuple)):
            achados.append(f"{chave}: {len(valor)} itens")
        if len(achados) >= 4:
            break
    return " · ".join(achados)


def previsualizar(resultado: Any) -> str:
    """Resumo pronto para a tela. String vazia quando não há o que mostrar."""
    if resultado is None:
        return ""
    if isinstance(resultado, dict):
        bruto = _do_dicionario(resultado)
    elif isinstance(resultado, (list, tuple)):
        bruto = f"{len(resultado)} itens"
    else:
        bruto = str(resultado)

    if not bruto.strip():
        return ""

    from ..exec.saida import preparar

    texto, _ = preparar(bruto, TETO)
    return texto.strip()
