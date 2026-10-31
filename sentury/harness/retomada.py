"""A tarefa que parou para pedir autorização, quando a autorização chega.

Terceira fase a ganhar nome e porta própria, pelo mesmo motivo das outras duas
(`pareceres.py`, `pos_resposta.py`): o laço estava virando flag sobre flag num
método de mil linhas, e cada conserto piorava isso.

## Duas tentativas até funcionar

O benchmark parou aqui três vezes seguidas, e as duas primeiras correções foram
insuficientes de um jeito instrutivo.

**Primeira**: nada era guardado. `state` não tinha campo de pendência e a
resposta do turno bloqueado não entrava no histórico, então o turno seguinte
recebia *"pode seguir"* solto e perguntava **"qual ação você deseja?"**: com o
pedido original duas mensagens acima.

**Segunda**: guardei a pendência e injetei *"continue de onde parou"*. O modelo
respondeu **"não tenho acesso à pasta nem ao resultado do passo anterior"**. Não
havia passo anterior: havia um passo que nunca rodou.

**Terceira**: a linha passou a nomear a chamada e a dizer que o acesso foi
concedido. O modelo então reconheceu tudo (*"já estou com acesso e vou mapear
esse banco para você agora mesmo"*) e encerrou o turno com `tool_calls: 0`.
Anunciou a ação em vez de tomá-la.

A conclusão é o desenho deste módulo: a ferramenta e os argumentos bloqueados
são **conhecidos**, então o harness executa. A linha de texto continua indo,
porque explica ao modelo o que aconteceu, mas ela não é mais a garantia: é
contexto. Depender de o modelo obedecer a uma instrução era transformar uma
garantia em pedido.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def guardar(pedido: str, permissao: Dict[str, Any], alvo: str) -> Dict[str, Any]:
    """O que o próximo turno precisa para retomar sozinho."""
    return {
        "pedido": pedido,
        "ferramenta": str(permissao.get("ferramenta") or ""),
        "argumentos": permissao.get("argumentos") or {},
        "alvo": alvo,
        "so_desta_vez": bool(permissao.get("so_desta_vez")),
        **({"equipe": permissao["equipe"]} if permissao.get("equipe") else {}),
    }


def linha_de_contexto(pendente: Dict[str, Any]) -> str:
    """A linha de sistema que conta ao modelo o que aconteceu entre os turnos.

    Nomeia a chamada a refazer. Um "continue de onde parou" fez o modelo procurar
    um resultado anterior que nunca existiu.
    """
    ferramenta = str(pendente.get("ferramenta") or "")
    if ferramenta:
        args = json.dumps(pendente.get("argumentos") or {}, ensure_ascii=False)
        refazer = f"Execute AGORA `{ferramenta}` com {args}"
    else:
        refazer = f"Refaca a etapa que estava bloqueada em `{pendente.get('alvo') or ''}`"
    return (
        "[TAREFA RETOMADA] A autorizacao que faltava FOI CONCEDIDA. "
        f"{refazer} e siga com o pedido original: {pendente['pedido']}\n"
        "O passo bloqueado nunca rodou, entao nao existe resultado anterior a "
        "recuperar — e o acesso nao falta mais. Nao pergunte o que fazer e nao "
        "diga que falta permissao."
    )


def aprovada(pendente: Dict[str, Any], sessao: str) -> bool:
    """A pessoa liberou o comando que parou o turno?

    Pergunta à política, que é quem guarda a resposta do cartão, venha ela da
    tela ou do Telegram. Sem isso, qualquer mensagem depois do cartão contava
    como aprovação: quem fechava o cartão e pedia outra coisa recebia o mesmo
    cartão de volta, com os argumentos antigos.
    """
    from ..exec.politica import avaliar

    alvo = str(pendente.get("alvo") or "").strip()
    if not alvo:
        return False
    try:
        decisao = avaliar(alvo, sessao, checar_alvo=False,
                          na_hora=bool(pendente.get("so_desta_vez")), consumir=False)
    except Exception:
        logger.debug("Retomada: a política não respondeu por %s", alvo, exc_info=True)
        return False
    return bool(decisao.get("permitido"))


def linha_sem_aprovacao(pendente: Dict[str, Any]) -> str:
    """O fato para o modelo quando o cartão ficou sem aprovação."""
    alvo = str(pendente.get("alvo") or pendente.get("ferramenta") or "")
    return (
        f"A ação `{alvo}` ficou esperando autorização e não foi aprovada, então não rodou. "
        "A mensagem mais recente da pessoa é o que ela quer agora e pode mudar o pedido. Se a ação "
        "ainda fizer sentido, proponha de novo com o que a pessoa acabou de dizer."
    )


def injetar_passo(
    plan: Optional[List[Dict[str, Any]]],
    retomar: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Devolve o plano com o passo autorizado na frente.

    Não substitui o plano: o planner pode ter proposto bem o resto da tarefa. Só
    garante que a etapa bloqueada acontece: e não duplica, se o planner já a
    propôs.
    """
    from ..tools.registry import TOOL_REGISTRY

    passos = list(plan or [])
    if not retomar:
        return passos
    if retomar.get("equipe"):
        # Um passo por residente aprovado; o que o planner já propôs com o mesmo nome não repete.
        ja = {str((p.get("arguments") or {}).get("nome") or "").lower()
              for p in passos if isinstance(p, dict) and p.get("tool") == "criar_agente"}
        novos = [{"tool": "criar_agente", "arguments": dict(m)} for m in retomar["equipe"]
                 if str(m.get("nome") or "").lower() not in ja]
        return novos + passos
    ferramenta = str(retomar.get("ferramenta") or "")
    # Ferramenta que não existe mais (pacote trocado entre os dois turnos) não
    # pode virar passo: o plano falharia por um nome fantasma.
    if not ferramenta or ferramenta not in TOOL_REGISTRY:
        return passos
    # "Ja proposto" e a mesma ferramenta com a mesma `acao`. So o nome nao
    # basta nas ferramentas de varias acoes: um plano com `computador digitar`
    # escondia o `computador clicar` aprovado, que nunca rodava, e o digitar
    # gastava a aprovacao. Comparar os argumentos inteiros seria o contrario:
    # o planner refaz o clique com a coordenada um pixel ao lado e ele roda duas.
    acao = str((retomar.get("argumentos") or {}).get("acao") or "")
    for passo in passos:
        if not isinstance(passo, dict) or str(passo.get("tool")) != ferramenta:
            continue
        if retomar.get("so_desta_vez"):
            # A aprovação pontual não cobre uma chamada com argumentos trocados.
            if (passo.get("arguments") or {}) == (retomar.get("argumentos") or {}):
                return passos
        elif str((passo.get("arguments") or {}).get("acao") or "") == acao:
            return passos
    logger.info(
        "Retomada: injetando %s no plano (estava bloqueado por permissao).",
        ferramenta,
    )
    return [{"tool": ferramenta, "arguments": retomar.get("argumentos") or {}}] + passos
