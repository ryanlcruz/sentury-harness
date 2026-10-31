"""Como o Sentury do notebook fala com a HQ.

Com `SENTURY_HQ_URL` definida, vai pela API com o token. Sem ela, a HQ é este
mesmo processo: é o modo de testar no PC antes de existir container ou VPS, e
roda exatamente as mesmas operações (`hq.py`).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from . import hq as _hq
from . import mesa as _mesa
from .manifesto import ManifestoInvalido
from .tarefas import TarefaInvalida


class HQIndisponivel(RuntimeError):
    pass


def url_da_hq() -> str:
    return os.environ.get("SENTURY_HQ_URL", "").strip().rstrip("/")


def onde() -> str:
    return url_da_hq() or "local"


async def _http(metodo: str, caminho: str, corpo: Optional[Dict[str, Any]] = None) -> Any:
    import httpx

    token = os.environ.get("SENTURY_HQ_TOKEN", "").strip()
    try:
        async with httpx.AsyncClient(timeout=20) as cliente:
            resposta = await cliente.request(
                metodo, f"{url_da_hq()}/hq{caminho}", json=corpo,
                headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise HQIndisponivel(f"a HQ em {url_da_hq()} não respondeu: {type(exc).__name__}") from None
    if resposta.status_code >= 400:
        try:
            detalhe = resposta.json().get("detail")
        except ValueError:
            detalhe = resposta.text[:200]
        if resposta.status_code in (401, 503):
            raise HQIndisponivel(f"a HQ recusou ({resposta.status_code}): {detalhe}")
        raise ManifestoInvalido(str(detalhe))
    return resposta.json()


async def _local(funcao, *args: Any) -> Any:
    try:
        return funcao(*args)
    except _hq.NaoEncontrado as exc:
        raise ManifestoInvalido(str(exc)) from None
    except TarefaInvalida as exc:
        raise ManifestoInvalido(str(exc)) from None
    except _mesa.AssuntoInvalido as exc:
        raise ManifestoInvalido(str(exc)) from None


async def criar(manifesto: Dict[str, Any], criado_por: str = "") -> Dict[str, Any]:
    if url_da_hq():
        return await _http("POST", "/agents", {"manifesto": manifesto, "criado_por": criado_por})
    return await _local(_hq.criar, manifesto, criado_por)


async def listar() -> Any:
    if url_da_hq():
        return (await _http("GET", "/agents")).get("agentes", [])
    return await _local(_hq.listar)


async def ver(nome: str) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("GET", f"/agents/{nome}")
    return await _local(_hq.ver, nome)


async def conversa(nome: str) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("GET", f"/agents/{nome}/conversa")
    from .conversa import ler
    try:
        return await ler(nome)
    except _hq.NaoEncontrado as exc:
        raise ManifestoInvalido(str(exc)) from None


async def pedir(nome: str, pedido: str, origem: str = "sentury", pai: str = "") -> Dict[str, Any]:
    if url_da_hq():
        return await _http("POST", f"/agents/{nome}/tasks", {"pedido": pedido, "origem": origem, "pai": pai})
    return await _local(_hq.pedir, nome, pedido, origem, pai)


async def pedir_na_conversa(nome, corpo):
    if url_da_hq():
        return await _http("POST", f"/agents/{nome}/conversa", corpo.model_dump())
    from .anexos import enviar
    try:
        return await enviar(nome, corpo)
    except _hq.NaoEncontrado as exc:
        raise ManifestoInvalido(str(exc)) from None


async def rotinas(nome: str):
    if url_da_hq():
        return await _http("GET", f"/agents/{nome}/rotinas")
    from .rotinas import listar
    return {"rotinas": await _local(listar, nome)}


async def criar_rotina(nome: str, campos: Dict[str, Any]):
    if url_da_hq():
        return await _http("POST", f"/agents/{nome}/rotinas", campos)
    from .rotinas import criar
    try:
        return await criar(nome, **campos)
    except _hq.NaoEncontrado as exc:
        raise ManifestoInvalido(str(exc)) from None


async def mudar_rotina(nome: str, rotina_id: str, ativa=None, campos=None):
    if url_da_hq():
        return await _http("PATCH", f"/agents/{nome}/rotinas/{rotina_id}", {**(campos or {}), **({"ativa": ativa} if ativa is not None else {})})
    from .rotinas import mudar
    return await mudar(nome, rotina_id, ativa, campos)


async def apagar_rotina(nome: str, rotina_id: str):
    if url_da_hq():
        return await _http("DELETE", f"/agents/{nome}/rotinas/{rotina_id}")
    from .rotinas import apagar
    return await apagar(nome, rotina_id)


async def tarefa(tarefa_id: str) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("GET", f"/tasks/{tarefa_id}")
    return await _local(_hq.tarefa, tarefa_id)


async def mudar(nome: str, acao: str) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("POST", f"/agents/{nome}/{acao}")
    return await _local(_hq.mudar, nome, acao)


async def editar(nome: str, campos: Dict[str, Any]) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("PATCH", f"/agents/{nome}", campos)
    return await _local(_hq.editar, nome, campos)


async def trocar_acessorios(nome: str, acessorios: Dict[str, str]) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("PUT", f"/agents/{nome}/acessorios", {"acessorios": acessorios})
    return await _local(_hq.trocar_acessorios, nome, acessorios)


async def aparencia() -> Dict[str, Any]:
    if url_da_hq():
        return await _http("GET", "/aparencia")
    return await _local(_hq.catalogo_de_aparencia)


async def esperando() -> Any:
    if url_da_hq():
        return (await _http("GET", "/tasks")).get("tarefas", [])
    return await _local(_hq.esperando)


async def eventos(desde: float = 0.0, limite: int = 60) -> Any:
    if url_da_hq():
        return (await _http("GET", f"/events?desde={float(desde)}&limite={int(limite)}")).get("eventos", [])
    return await _local(_hq.eventos, desde, limite)


async def responder(tarefa_id: str, resposta: str, retorno: str = "") -> Dict[str, Any]:
    if url_da_hq():
        return await _http("POST", f"/tasks/{tarefa_id}/responder", {"resposta": resposta, "retorno": retorno})
    return await _local(_hq.responder, tarefa_id, resposta, retorno)


async def assuntos() -> Any:
    if url_da_hq():
        return (await _http("GET", "/mesa")).get("assuntos", [])
    return await _local(_hq.assuntos)


async def decisoes() -> Any:
    if url_da_hq():
        return (await _http("GET", "/decisoes")).get("decisoes", [])
    return await _local(_hq.decisoes)


async def abrir_assunto(titulo: str, texto: str = "", aberto_por: str = "pessoa",
                        canal: str = "") -> Dict[str, Any]:
    if url_da_hq():
        return await _http("POST", "/mesa", {"titulo": titulo, "texto": texto, "aberto_por": aberto_por,
                                             "canal": canal})
    return await _local(_hq.abrir_assunto, titulo, aberto_por, texto, canal)


async def assunto(assunto_id: str) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("GET", f"/mesa/{assunto_id}")
    return await _local(_hq.assunto, assunto_id)


async def falar_no_assunto(assunto_id: str, texto: str) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("POST", f"/mesa/{assunto_id}/falar", {"texto": texto})
    return await _local(_hq.falar_na_mesa, assunto_id, texto)


async def fechar_assunto(assunto_id: str, resumo: str = "") -> Dict[str, Any]:
    if url_da_hq():
        return await _http("POST", f"/mesa/{assunto_id}/fechar", {"resumo": resumo})
    return await _local(_hq.fechar_assunto, assunto_id, resumo)


async def apagar_assunto(assunto_id: str) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("DELETE", f"/mesa/{assunto_id}")
    return await _local(_hq.apagar_assunto, assunto_id)


async def cancelar(tarefa_id: str) -> Dict[str, Any]:
    if url_da_hq():
        return await _http("POST", f"/tasks/{tarefa_id}/cancelar")
    return await _local(_hq.cancelar, tarefa_id)
