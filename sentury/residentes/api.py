"""A API da HQ: o Sentury do notebook cria agentes e manda tarefas por aqui.

No MVP ela não fica na internet: escuta em 127.0.0.1 (túnel SSH) ou no IP do
Tailscale, e cobra um token fixo. Sem `SENTURY_HQ_TOKEN` a API inteira
responde 503: HQ sem token é HQ desligada, nunca HQ aberta.
"""
from __future__ import annotations

import hmac
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from . import hq as _hq
from .manifesto import ManifestoInvalido
from .tarefas import TarefaInvalida
from .rotinas import NovaRotina, EstadoDaRotina
from .anexos import PedidoNaConversa


def token_da_hq() -> str:
    return os.environ.get("SENTURY_HQ_TOKEN", "").strip()


def _exigir_token(authorization: str = Header(default="")) -> None:
    esperado = token_da_hq()
    if not esperado:
        raise HTTPException(503, "HQ desligada: defina SENTURY_HQ_TOKEN para ligar a API")
    if not hmac.compare_digest(authorization.encode(), f"Bearer {esperado}".encode()):
        raise HTTPException(401, "token da HQ ausente ou errado")


router = APIRouter(prefix="/hq", tags=["hq"], dependencies=[Depends(_exigir_token)])


class CriarAgente(BaseModel):
    manifesto: Dict[str, Any]
    criado_por: str = Field(default="", max_length=120)


class NovaTarefa(BaseModel):
    pedido: str = Field(min_length=1, max_length=8000)
    origem: str = Field(default="api", max_length=120)
    # A tarefa do residente que pediu, quando é um colega pedindo.
    pai: str = Field(default="", max_length=64)


class NovoAssunto(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    texto: str = Field(default="", max_length=2000)
    aberto_por: str = Field(default="pessoa", max_length=64)
    canal: str = Field(default="", max_length=120)


class Resumo(BaseModel):
    resumo: str = Field(default="", max_length=2000)


class FalaDaPessoa(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


class Resposta(BaseModel):
    resposta: str = Field(default="", max_length=16)
    retorno: str = Field(default="", max_length=8000)


def _chamar(funcao, *args: Any) -> Any:
    try:
        return funcao(*args)
    except _hq.NaoEncontrado as exc:
        raise HTTPException(404, str(exc)) from None
    except (ManifestoInvalido, TarefaInvalida, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/mesa")
async def assuntos() -> Dict[str, Any]:
    return {"assuntos": _hq.assuntos()}


@router.get("/decisoes")
async def decisoes() -> Dict[str, Any]:
    return {"decisoes": _hq.decisoes()}


@router.post("/mesa", status_code=201)
async def abrir_assunto(corpo: NovoAssunto) -> Dict[str, Any]:
    return _chamar(_hq.abrir_assunto, corpo.titulo, corpo.aberto_por, corpo.texto, corpo.canal)


@router.get("/mesa/{assunto_id}")
async def assunto(assunto_id: str) -> Dict[str, Any]:
    return _chamar(_hq.assunto, assunto_id)


@router.post("/mesa/{assunto_id}/falar")
async def falar_no_assunto(assunto_id: str, corpo: FalaDaPessoa) -> Dict[str, Any]:
    return _chamar(_hq.falar_na_mesa, assunto_id, corpo.texto)


@router.post("/mesa/{assunto_id}/fechar")
async def fechar_assunto(assunto_id: str, corpo: Resumo) -> Dict[str, Any]:
    return _chamar(_hq.fechar_assunto, assunto_id, corpo.resumo)


@router.delete("/mesa/{assunto_id}")
async def apagar_assunto(assunto_id: str) -> Dict[str, Any]:
    return _chamar(_hq.apagar_assunto, assunto_id)


@router.get("/saude")
async def saude() -> Dict[str, Any]:
    return {"ok": True, "agentes": len(_hq.listar())}


@router.post("/agents", status_code=201)
async def criar(corpo: CriarAgente) -> Dict[str, Any]:
    return _chamar(_hq.criar, corpo.manifesto, corpo.criado_por)


@router.get("/agents")
async def listar() -> Dict[str, Any]:
    return {"agentes": _hq.listar()}


@router.get("/agents/{nome}")
async def ver(nome: str) -> Dict[str, Any]:
    return _chamar(_hq.ver, nome)


class Acessorios(BaseModel):
    acessorios: Dict[str, str] = Field(default_factory=dict)


@router.get("/agents/{nome}/conversa")
async def conversa(nome: str) -> Dict[str, Any]:
    from .conversa import ler
    try:
        return await ler(nome)
    except _hq.NaoEncontrado as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/agents/{nome}/conversa", status_code=201)
async def pedir_na_conversa(nome: str, corpo: PedidoNaConversa):
    from .anexos import enviar
    try:
        return await enviar(nome, corpo)
    except _hq.NaoEncontrado as exc:
        raise HTTPException(404, str(exc)) from None
    except (ValueError, ManifestoInvalido) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/aparencia")
async def aparencia() -> Dict[str, Any]:
    return _hq.catalogo_de_aparencia()


@router.patch("/agents/{nome}")
async def editar(nome: str, campos: Dict[str, Any]) -> Dict[str, Any]:
    return _chamar(_hq.editar, nome, campos)


@router.put("/agents/{nome}/acessorios")
async def acessorios(nome: str, corpo: Acessorios) -> Dict[str, Any]:
    return _chamar(_hq.trocar_acessorios, nome, corpo.acessorios)


@router.post("/agents/{nome}/tasks", status_code=201)
async def pedir(nome: str, corpo: NovaTarefa) -> Dict[str, Any]:
    return _chamar(_hq.pedir, nome, corpo.pedido, corpo.origem, corpo.pai)


async def _rotina(coro):
    try:
        return await coro
    except _hq.NaoEncontrado as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/agents/{nome}/rotinas")
async def rotinas(nome: str):
    from .rotinas import listar
    return {"rotinas": _chamar(listar, nome)}


@router.post("/agents/{nome}/rotinas", status_code=201)
async def criar_rotina(nome: str, corpo: NovaRotina):
    from .rotinas import criar
    return await _rotina(criar(nome, **corpo.model_dump()))


@router.patch("/agents/{nome}/rotinas/{rotina_id}")
async def mudar_rotina(nome: str, rotina_id: str, corpo: EstadoDaRotina):
    from .rotinas import mudar
    return await _rotina(mudar(nome, rotina_id, corpo.ativa, corpo.model_dump(exclude_unset=True, exclude={"ativa"})))


@router.delete("/agents/{nome}/rotinas/{rotina_id}")
async def apagar_rotina(nome: str, rotina_id: str):
    from .rotinas import apagar
    return await _rotina(apagar(nome, rotina_id))


# Depois de `/tasks`: declarada antes, esta rota engoliria a de cima.
@router.post("/agents/{nome}/{acao}")
async def mudar(nome: str, acao: str) -> Dict[str, Any]:
    return _chamar(_hq.mudar, nome, acao)


@router.get("/tasks")
async def esperando() -> Dict[str, Any]:
    return {"tarefas": _hq.esperando()}


@router.get("/events")
async def eventos(desde: float = 0.0, limite: int = 60) -> Dict[str, Any]:
    return {"eventos": _hq.eventos(desde, limite)}


@router.get("/tasks/{tarefa_id}")
async def tarefa(tarefa_id: str) -> Dict[str, Any]:
    return _chamar(_hq.tarefa, tarefa_id)


@router.post("/tasks/{tarefa_id}/responder")
async def responder(tarefa_id: str, corpo: Resposta) -> Dict[str, Any]:
    return _chamar(_hq.responder, tarefa_id, corpo.resposta, corpo.retorno)


@router.post("/tasks/{tarefa_id}/cancelar")
async def cancelar(tarefa_id: str) -> Dict[str, Any]:
    return _chamar(_hq.cancelar, tarefa_id)


def montar(app: Any, prefixo: Optional[str] = None) -> None:
    app.include_router(router, prefix=prefixo or "")
