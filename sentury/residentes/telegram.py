"""Os residentes no Telegram: `@nome` manda para a fila dele, e ele avisa de volta.

O gateway do Telegram chama estas funções; o que vale para tela e Telegram
(fila, resposta, aprovação) continua passando pelo `cliente`, então serve com a
HQ no próprio processo ou na VPS.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import cliente as _cliente
from .manifesto import ManifestoInvalido

_MENCAO = re.compile(r"^@([a-z][a-z0-9-]{1,30})\s+([\s\S]+)$")
_BOTOES = (("s", "uma_vez", "Autorizar desta vez"), ("n", "negar", "Negar"))


def ler_assunto(texto: str) -> Optional[Tuple[str, str]]:
    """`/mesa <título>` e, nas linhas de baixo, o contexto: (título, texto)."""
    linhas = str(texto or "").strip().split("\n", 1)
    partes = linhas[0].split(maxsplit=1)
    if not partes or partes[0].lower().split("@", 1)[0] != "/mesa":
        return None
    titulo = partes[1].strip() if len(partes) > 1 else ""
    return titulo, (linhas[1].strip() if len(linhas) > 1 else "")


async def abrir_na_mesa(chat_id: Any, titulo: str, texto: str) -> str:
    if not titulo:
        return ("Escreva o assunto depois do comando, e o contexto nas linhas de baixo. "
                "Chame quem precisa estar com @nome. Ex.: /mesa por que o backup falhou?")
    assunto = await _cliente.abrir_assunto(titulo, texto, "pessoa", f"telegram:{chat_id}")
    quem = ", ".join(_Nome(n) for n in assunto.get("participantes") or [])
    chamados = f" Já estão nele: {quem}." if quem else " Quem tiver a ver com o assunto entra."
    return f"Abri na Mesa: \"{assunto['titulo']}\".{chamados} Mando o resumo aqui quando fechar."


def aviso_de_fechamento(assunto: Any) -> Optional[Tuple[Any, str]]:
    """(chat, texto) do resumo, quando o assunto veio do Telegram."""
    canal = str(getattr(assunto, "canal", "") or "")
    if not canal.startswith("telegram:"):
        return None
    chat = canal.split(":", 1)[1]
    falaram = ", ".join(sorted({_Nome(f["de"]) for f in getattr(assunto, "falas", [])})) or "ninguém"
    resumo = getattr(assunto, "resumo", "") or "sem resumo"
    texto = f"**Mesa: {assunto.titulo}**\nFalaram: {falaram}.\n\n{resumo}"
    return (int(chat) if chat.lstrip("-").isdigit() else chat), texto


def _Nome(nome: str) -> str:
    return nome[:1].upper() + nome[1:]


def ler_mencao(texto: str) -> Optional[Tuple[str, str]]:
    achado = _MENCAO.match(str(texto or "").strip())
    return (achado.group(1), achado.group(2).strip()) if achado else None


async def encaminhar(chat_id: Any, nome: str, texto: str) -> Optional[str]:
    """A resposta curta para o chat, ou None quando não há residente com esse
    nome (aí a mensagem segue para o Sentury como qualquer outra)."""
    try:
        await _cliente.ver(nome)
    except ManifestoInvalido:
        return None
    # Ele estava esperando uma resposta sua: o texto responde, não vira tarefa nova.
    pergunta = next((t for t in await _cliente.esperando()
                     if t.get("agente") == nome and not t.get("pendente")), None)
    if pergunta:
        await _cliente.responder(pergunta["id"], "", texto)
        return f"Repassei sua resposta para {_Nome(nome)}."
    tarefa = await _cliente.pedir(nome, texto, f"telegram:{chat_id}")
    aviso = f" {tarefa['aviso']}." if tarefa.get("aviso") else ""
    return f"Mandei para {_Nome(nome)}.{aviso} Aviso aqui quando terminar."


def destinos(tarefa: Any, canais: Iterable[str], donos: List[Any]) -> List[Any]:
    """Para onde vai o aviso: o chat de onde veio o pedido; se o pedido veio de
    outro lugar e o residente tem o canal Telegram, os chats autorizados."""
    origem = str(getattr(tarefa, "origem", "") or "")
    if origem.startswith("telegram:"):
        chat = origem.split(":", 1)[1]
        return [int(chat) if chat.lstrip("-").isdigit() else chat]
    return list(donos) if "telegram" in set(canais or []) else []


def aviso(tarefa: Any) -> Tuple[str, Optional[Dict[str, Any]]]:
    """O texto (markdown) e, quando ele espera aprovação, os botões."""
    Nome = _Nome(tarefa.agente)
    if tarefa.estado == "feita":
        return f"**{Nome}** terminou \"{tarefa.pedido}\":\n\n{tarefa.resposta or 'sem resposta em texto.'}", None
    if tarefa.estado == "esperando" and tarefa.pendente.startswith("ferramenta_nova "):
        texto = f"**{Nome}** {tarefa.motivo or 'pediu uma ferramenta nova'}.\nTarefa: \"{tarefa.pedido}\""
        return texto, botoes(tarefa.id)
    if tarefa.estado == "esperando" and tarefa.pendente:
        texto = f"**{Nome}** quer rodar fora da caixa:\n`{tarefa.pendente}`\nTarefa: \"{tarefa.pedido}\""
        return texto, botoes(tarefa.id)
    if tarefa.estado == "esperando":
        pergunta = tarefa.resposta or tarefa.motivo
        return f"**{Nome}** perguntou:\n{pergunta}\n\nResponda com `@{tarefa.agente} sua resposta`.", None
    return f"**{Nome}** não conseguiu \"{tarefa.pedido}\": {tarefa.motivo or tarefa.estado}.", None


def botoes(tarefa_id: str) -> Dict[str, Any]:
    return {"inline_keyboard": [[{"text": rotulo, "callback_data": f"res:{tarefa_id}:{codigo}"}
                                 for codigo, _, rotulo in _BOTOES]]}


def ler_botao(dados: str) -> Optional[Tuple[str, str, str]]:
    """`res:<tarefa>:<código>` → (tarefa, resposta, rótulo), ou None se não é dele."""
    partes = str(dados or "").split(":")
    if len(partes) != 3 or partes[0] != "res":
        return None
    for codigo, resposta, rotulo in _BOTOES:
        if codigo == partes[2]:
            return partes[1], resposta, rotulo
    return None


async def responder_botao(tarefa_id: str, resposta: str) -> Dict[str, Any]:
    return await _cliente.responder(tarefa_id, resposta)
