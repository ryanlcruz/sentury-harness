"""Plano e workflow tem uma porta so, e nao e codigo.

Visto na tela: o modelo chamou `executar_python` para **escrever um plano**.
Montou o texto do Markdown numa string e gravou. Funciona por acidente e erra
em tudo o que importa:

- o arquivo nasce sem o estado que mora fora do repositorio (tentativas,
  portao, sessoes), entao o card na tela mostra um plano vazio;
- `status_da_tarefa` depois nao acha a tarefa, porque o id nao foi gerado por
  quem gera id;
- e o dono paga uma execucao de sandbox para produzir um `.md` que
  `criar_plano` escreve numa chamada, sem gate e sem risco.

Codigo existe para o que tem calculo, laco ou volume. Escrever quinze linhas de
texto nao e nenhuma das tres coisas.

O desvio e deterministico de proposito: a mesma coisa dita na `orientacao` e
uma instrucao que o modelo segue quase sempre, e "quase sempre" foi exatamente
o que produziu o defeito.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# As pastas que so o modulo de plano/workflow deve tocar. Comparadas depois de
# normalizar a barra, para valer no Windows sem duplicar a lista.
_PASTAS = (".sentury/planos", ".sentury/workflows")

# No codigo, a pista e o caminho escrito como literal: com qualquer barra.
_NO_CODIGO = re.compile(r"\.sentury[\\/]+(planos|workflows)", re.IGNORECASE)

_ESCRITA = ("escrever_arquivo", "editar_arquivo")
_CODIGO = ("executar_python", "executar_script")

_RECADO = (
    "Plano e workflow nao se escrevem por fora: use `criar_plano` "
    "(nome, tarefas) ou `criar_workflow` (nome, gatilho, passos), e "
    "`status_da_tarefa` para marcar andamento. O arquivo e so metade — a "
    "outra metade e o estado (ids, tentativas, portao) que essas ferramentas "
    "gravam e que o card na tela le. Escrito na mao, o plano aparece vazio e "
    "`status_da_tarefa` nao encontra a tarefa depois."
)


def _texto(arguments: Dict[str, Any], *chaves: str) -> str:
    for chave in chaves:
        valor = arguments.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor
    return ""


def desvio(tool: str, arguments: Any) -> Optional[Dict[str, Any]]:
    """Devolve a recusa quando a chamada esta indo pela porta errada."""
    if not isinstance(arguments, dict):
        return None
    if tool in _ESCRITA:
        alvo = _texto(arguments, "caminho", "path").replace("\\", "/").lower()
        if any(pasta in alvo for pasta in _PASTAS):
            return {"ok": False, "recusado": True, "erro": _RECADO,
                    "use": "criar_plano" if "planos" in alvo else "criar_workflow"}
        return None
    if tool in _CODIGO:
        corpo = _texto(arguments, "codigo", "code", "conteudo", "content")
        achado = _NO_CODIGO.search(corpo)
        if achado:
            return {"ok": False, "recusado": True, "erro": _RECADO,
                    "use": "criar_plano" if achado.group(1).lower() == "planos"
                    else "criar_workflow"}
    return None
