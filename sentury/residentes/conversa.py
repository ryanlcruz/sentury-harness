"""A conversa pública usa o mesmo histórico persistente do worker."""
from datetime import datetime, timezone

from . import hq, mesa, tarefas


def _o_que_chegou(tarefa) -> str:
    """O pedido como a pessoa deve ler: a vez na Mesa e o pedido de colega têm
    texto interno de turno, que não é dela."""
    assunto_id = mesa.de_origem(tarefa.origem)
    if assunto_id:
        assunto = mesa.carregar(assunto_id)
        return f"Vez na Mesa: {assunto.titulo if assunto else 'um assunto'}"
    if tarefa.origem.startswith("agente:"):
        colega = tarefa.origem.split(":", 1)[1]
        return f"{colega[:1].upper()}{colega[1:]} pediu: {tarefa.pedido}"
    from .anexos import nomes_na_mensagem
    return tarefa.pedido + nomes_na_mensagem(tarefa)


async def ler(nome: str) -> dict:
    from ..main import _load_state, trava_da_sessao

    agente = hq.ver(nome)
    sessao = hq.sessao_do(nome)
    async with trava_da_sessao.da(sessao):
        _, state = await _load_state(sessao, "hq")
        historico = list(state.history)
    todas = tarefas.listar(nome)
    por_id = {t.id: t for t in todas}
    vistas = set()
    mensagens = []
    # Cada vez na Mesa é um turno nesta sessão, mas a conversa dela mora na
    # Mesa: aqui cada assunto vira uma linha só, e as vezes dele ficam de fora.
    assuntos_citados = set()
    na_mesa = False
    for i, mensagem in enumerate(historico):
        papel = mensagem.get("role")
        if papel not in ("user", "assistant"):
            continue
        origem = str(mensagem.get("origem") or "")
        tarefa_id = origem.removeprefix("tarefa:") if origem.startswith("tarefa:") else ""
        tarefa = por_id.get(tarefa_id)
        if tarefa:
            vistas.add(tarefa.id)
        if papel == "user":
            assunto_id = mesa.de_origem(tarefa.origem) if tarefa else None
            na_mesa = bool(assunto_id)
            if assunto_id and assunto_id not in assuntos_citados:
                assuntos_citados.add(assunto_id)
                assunto = mesa.carregar(assunto_id)
                mensagens.append({
                    "id": f"{sessao}:{i}", "sessionId": sessao, "role": "assistant", "timestamp": "",
                    "content": f"Participei da Mesa: {assunto.titulo if assunto else 'um assunto'}. "
                               "A conversa e o resumo estão na Mesa.",
                    "residente": nome, "mesa": assunto_id,
                })
        if na_mesa:
            continue
        mensagens.append({
            "id": f"{sessao}:{i}", "sessionId": sessao, "role": papel,
            "content": _o_que_chegou(tarefa) if tarefa else str(mensagem.get("content") or ""),
            "timestamp": "",
            **({"pedido_original": tarefa.pedido} if tarefa and papel == "user" else {}),
            **({"residente": nome} if papel == "assistant" else {}),
        })
    for tarefa in todas:
        if tarefa.id in vistas or tarefa.estado not in tarefas.ABERTAS or mesa.de_origem(tarefa.origem):
            continue
        mensagens.append({
            "id": f"tarefa:{tarefa.id}", "sessionId": sessao, "role": "user",
            "content": _o_que_chegou(tarefa),
            "pedido_original": tarefa.pedido,
            "timestamp": datetime.fromtimestamp(tarefa.criada_em, timezone.utc).isoformat(),
        })
    return {"session_id": sessao, "agente": agente, "mensagens": mensagens,
            # Tarefa na fila ou rodando: a tela mostra que ele está trabalhando.
            "trabalhando": any(t.estado in (tarefas.NA_FILA, tarefas.RODANDO) for t in todas),
            "esperando": [t.publico() for t in todas if t.estado == "esperando" and not t.aguardando]}
