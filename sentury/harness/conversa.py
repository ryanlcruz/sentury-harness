"""A conversa como o modelo deve recebê-la no passo único.

A ordem é a de uma conversa: o sistema estável, o que já foi dito, a pergunta
deste turno no lugar dela, o que aconteceu no turno (resultados, avisos) e,
por último, o contexto do turno, que é a parte que muda. O prefixo estável
deixa o cache do provedor valer entre as chamadas.

Mensagem de sistema do histórico vira aviso do Sentury em papel de usuário:
nem todo provedor aceita sistema no meio da conversa. Papéis iguais seguidos
são juntados, nunca descartados.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

AVISO = "[System Notice:\n{conteudo}\n]"
CONTEXTO = "[Contexto do turno, montado pelo Sentury (não é mensagem da pessoa):\n{conteudo}\n]"


def _inicio_do_turno(historico: List[Dict[str, Any]]) -> int:
    """O turno atual começa depois da última resposta do assistente.

    A pergunta só entra no histórico no fim do turno; os resultados das
    ferramentas deste turno entram antes dela. Índice guardado se perderia
    quando a compactação reescreve o histórico no meio do turno.
    """
    for i in range(len(historico) - 1, -1, -1):
        if historico[i].get("role") == "assistant":
            return i + 1
    return 0


def _converter(msg: Dict[str, Any]) -> Optional[Dict[str, str]]:
    papel = msg.get("role")
    conteudo = str(msg.get("content") or "")
    if not conteudo.strip():
        return None
    # Orientação no meio do turno (harness/caixa_do_turno.py) é fala da pessoa:
    # vai com o texto dela, em papel de usuário. Resultado de ferramenta tem
    # papel próprio e não consegue se passar por isto.
    if papel == "system" and str(msg.get("orientacao") or "").strip():
        return {"role": "user", "content": str(msg["orientacao"]).strip()}
    if papel == "system":
        return {"role": "user", "content": AVISO.format(conteudo=conteudo)}
    if papel in ("user", "assistant"):
        # Plano em JSON cru de uma volta antiga nao e fala de ninguem.
        if papel == "assistant" and conteudo.lstrip().startswith("{"):
            return None
        return {"role": papel, "content": conteudo}
    return None


def marcar_chamada(msg: Dict[str, Any], passo: Any, ferramenta: str, argumentos: Any) -> Dict[str, Any]:
    """Liga o resultado à chamada que o produziu, sem criar mensagem nova.

    Uma mensagem `assistant` com `tool_calls` no histórico apareceria na tela
    como bolha vazia ao recarregar a conversa; a chamada viaja junto do
    resultado e só vira par chamada/resposta na hora de montar para o modelo.
    """
    id_ = str((passo or {}).get("id") or "") if isinstance(passo, dict) else ""
    msg["chamada"] = {"id": id_, "nome": str(ferramenta or ""), "argumentos": argumentos or {}}
    return msg


def _par_nativo(msg: Dict[str, Any], n: int) -> List[Dict[str, Any]]:
    """Resultado de ferramenta no formato nativo: a chamada do assistente e a
    resposta `tool` ligada a ela pelo id."""
    import json

    chamada = msg["chamada"]
    id_ = chamada.get("id") or f"sentury_{n}"
    return [
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": id_, "type": "function",
            "function": {"name": chamada.get("nome") or "ferramenta",
                         "arguments": json.dumps(chamada.get("argumentos") or {}, ensure_ascii=False)},
        }]},
        {"role": "tool", "tool_call_id": id_, "content": str(msg.get("content") or "")},
    ]


def montar(
    sistema: str,
    historico: List[Dict[str, Any]],
    pergunta: str,
    contexto_do_turno: str = "",
    *,
    nativo: bool = False,
) -> List[Dict[str, Any]]:
    """Mensagens para uma chamada do passo único.

    Com `nativo`, o resultado de ferramenta deste turno vai como par chamada e
    resposta `tool`; os adapters que não falam isso rebaixam para texto.
    """
    historico = [m for m in historico if isinstance(m, dict)]
    corte = _inicio_do_turno(historico)
    sequencia: List[Dict[str, Any]] = []
    for msg in historico[:corte]:
        convertida = _converter(msg)
        if convertida:
            sequencia.append(convertida)
    if str(pergunta or "").strip():
        atual: Dict[str, Any] = {"role": "user", "content": str(pergunta)}
        # A imagem anexada mora na mensagem do turno no histórico; sem trazê-la
        # para cá, ela não chegava ao modelo e o Router nem pedia quem enxerga.
        imagens = [img for m in historico[corte:] if m.get("role") == "user"
                   and str(m.get("content") or "") == str(pergunta) for img in (m.get("imagens") or [])]
        if imagens:
            atual["imagens"] = imagens
        sequencia.append(atual)
    for n, msg in enumerate(historico[corte:]):
        # A pergunta pode ja estar la (retomada, regeneracao): nao duplica.
        if msg.get("role") == "user" and str(msg.get("content") or "") == str(pergunta or ""):
            continue
        if nativo and msg.get("role") == "system" and isinstance(msg.get("chamada"), dict):
            sequencia.extend(_par_nativo(msg, n))
            continue
        convertida = _converter(msg)
        if convertida:
            sequencia.append(convertida)
    if str(contexto_do_turno or "").strip():
        sequencia.append({"role": "user", "content": CONTEXTO.format(conteudo=contexto_do_turno.strip())})

    juntas: List[Dict[str, Any]] = []
    for msg in sequencia:
        estrutural = msg["role"] == "tool" or msg.get("tool_calls")
        anterior_estrutural = juntas and (juntas[-1]["role"] == "tool" or juntas[-1].get("tool_calls"))
        if juntas and juntas[-1]["role"] == msg["role"] and not estrutural and not anterior_estrutural:
            imagens = list(juntas[-1].get("imagens") or []) + list(msg.get("imagens") or [])
            juntas[-1] = {"role": msg["role"], "content": juntas[-1]["content"] + "\n\n" + msg["content"],
                          **({"imagens": imagens} if imagens else {})}
        else:
            juntas.append(dict(msg))
    # Depois do sistema, a primeira fala tem que ser da pessoa.
    if juntas and juntas[0]["role"] == "assistant":
        juntas.insert(0, {"role": "user", "content": "(início da conversa)"})
    return [{"role": "system", "content": sistema}] + juntas



def historico_para_o_modelo(historico: List[Dict[str, Any]], pergunta: str) -> List[Dict[str, Any]]:
    """Toda mensagem de sistema entra, menos a da skill (vai no prompt).

    O filtro antigo era de junho, quando so o responder via o dado: deixava
    passar so sistema com '[INSTRUÇÃO DO SISTEMA:', e no passo unico a chamada
    que escreve a resposta nao via o resultado da ferramenta, o anexo nem o
    lembrete de repeticao.
    """
    saida = []
    for msg in historico:
        papel, conteudo = msg.get("role"), msg.get("content")
        if conteudo == pergunta:
            continue
        if papel in ("user", "assistant") or (
                papel == "system" and "[INSTRUÇÃO PROCEDURAL DE SKILL CARREGADA]" not in str(conteudo)):
            saida.append(msg)
    return saida


# O montador do caminho sem ferramenta nativa, como era no orquestrador.
def preparar_legado(system_prompt: str, history: List[Dict[str, str]], user_msg: Optional[str] = None) -> List[Dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]

    raw_steps = []
    for m in history:
        role = m.get("role")
        content = m.get("content", "")
        if not content:
            continue
        # Ignora JSON bruto de ações do Planner no histórico do chat
        if content.strip().startswith("{"):
            continue
        if role == "system":
            # Converte system intermediário para user
            raw_steps.append({"role": "user", "content": f"[System Notice:\n{content}\n]"})
        elif role in ("user", "assistant"):
            raw_steps.append({"role": role, "content": content})

    if user_msg:
        raw_steps.append({"role": "user", "content": user_msg})

    # Mensagens seguidas do mesmo papel viram uma, na ordem, como no caminho
    # nativo (`montar`). Descartar a primeira de duas falas da pessoa perdia o
    # que ela disse sem resposta, e o modelo deste caminho via outra conversa.
    clean_steps = []
    for step in raw_steps:
        if clean_steps and clean_steps[-1]["role"] == step["role"]:
            clean_steps[-1]["content"] += "\n\n" + step["content"]
        else:
            clean_steps.append(step.copy())


    # Garante que a primeira após system seja user
    if clean_steps and clean_steps[0]["role"] == "assistant":
        clean_steps[0]["role"] = "user"
        clean_steps[0]["content"] = f"[Assistant historical output:\n{clean_steps[0]['content']}\n]"

    messages.extend(clean_steps)
    return messages


__all__ = ["historico_para_o_modelo", "marcar_chamada", "montar", "preparar_legado"]
