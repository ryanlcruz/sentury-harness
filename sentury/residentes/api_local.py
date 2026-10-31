"""As rotas que a tela do Sentury usa para a HQ.

Passam pelo `cliente`, então valem igual com a HQ no próprio processo ou na
VPS. A autenticação é a mesma das outras rotas do Sentury: quem monta o router
passa a dependência (`main` passa `verify_api_token`).
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import cliente as _cliente
from .manifesto import ManifestoInvalido
from .rotinas import NovaRotina, EstadoDaRotina
from .anexos import PedidoNaConversa

# Os caminhos com "_" nunca colidem com nome de agente: o nome não aceita "_".
router = APIRouter(prefix="/sentury/residentes", tags=["residentes"])


class NovaTarefa(BaseModel):
    pedido: str = Field(min_length=1, max_length=8000)


class Acessorios(BaseModel):
    acessorios: Dict[str, str] = Field(default_factory=dict)


class NovoAssunto(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    texto: str = Field(default="", max_length=2000)


class Resumo(BaseModel):
    resumo: str = Field(default="", max_length=2000)


class FalaDaPessoa(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


class Resposta(BaseModel):
    resposta: str = Field(default="", max_length=16)
    retorno: str = Field(default="", max_length=8000)


async def _chamar(coro) -> Any:
    try:
        return await coro
    except _cliente.HQIndisponivel as exc:
        raise HTTPException(503, str(exc)) from None
    except (ManifestoInvalido, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("")
async def listar() -> Dict[str, Any]:
    return {"agentes": await _chamar(_cliente.listar()), "hq": _cliente.onde()}


@router.get("/_aparencia")
async def aparencia() -> Dict[str, Any]:
    return await _chamar(_cliente.aparencia())


@router.get("/_previa")
async def previa(nome: str, familia: str = "") -> Dict[str, Any]:
    """A coruja que vai nascer, para o cartão da fábrica mostrar a mesma."""
    from .aparencia import cores, montar

    aparencia = montar(nome.strip().lower(), familia)
    return {"aparencia": aparencia, "cores": cores(aparencia)}


@router.get("/_esperando")
async def esperando() -> Dict[str, Any]:
    return {"tarefas": await _chamar(_cliente.esperando())}


@router.get("/_eventos")
async def eventos(desde: float = 0.0, limite: int = 60) -> Dict[str, Any]:
    """O feed do Escritório. O próximo `desde` é o `em` mais novo que chegou:
    o relógio é o da HQ, que pode estar em outra máquina."""
    return {"eventos": await _chamar(_cliente.eventos(desde, limite))}


@router.get("/_mesa")
async def assuntos() -> Dict[str, Any]:
    return {"assuntos": await _chamar(_cliente.assuntos())}


@router.get("/_decisoes")
async def decisoes() -> Dict[str, Any]:
    return {"decisoes": await _chamar(_cliente.decisoes())}


@router.post("/_mesa", status_code=201)
async def abrir_assunto(corpo: NovoAssunto) -> Dict[str, Any]:
    return await _chamar(_cliente.abrir_assunto(corpo.titulo, corpo.texto))


@router.get("/_mesa/{assunto_id}")
async def assunto(assunto_id: str) -> Dict[str, Any]:
    return await _chamar(_cliente.assunto(assunto_id))


@router.post("/_mesa/{assunto_id}/falar")
async def falar_no_assunto(assunto_id: str, corpo: FalaDaPessoa) -> Dict[str, Any]:
    return await _chamar(_cliente.falar_no_assunto(assunto_id, corpo.texto))


@router.post("/_mesa/{assunto_id}/fechar")
async def fechar_assunto(assunto_id: str, corpo: Resumo) -> Dict[str, Any]:
    return await _chamar(_cliente.fechar_assunto(assunto_id, corpo.resumo))


@router.delete("/_mesa/{assunto_id}")
async def apagar_assunto(assunto_id: str) -> Dict[str, Any]:
    return await _chamar(_cliente.apagar_assunto(assunto_id))


@router.get("/_tarefas/{tarefa_id}")
async def tarefa(tarefa_id: str) -> Dict[str, Any]:
    return await _chamar(_cliente.tarefa(tarefa_id))


@router.post("/_tarefas/{tarefa_id}/responder")
async def responder(tarefa_id: str, corpo: Resposta) -> Dict[str, Any]:
    return await _chamar(_cliente.responder(tarefa_id, corpo.resposta, corpo.retorno))


@router.post("/_tarefas/{tarefa_id}/cancelar")
async def cancelar(tarefa_id: str) -> Dict[str, Any]:
    return await _chamar(_cliente.cancelar(tarefa_id))


@router.get("/{nome}")
async def ver(nome: str) -> Dict[str, Any]:
    return await _chamar(_cliente.ver(nome))


@router.get("/{nome}/contexto")
async def contexto(nome: str) -> Dict[str, Any]:
    """O contexto que o turno do residente monta. Lê onde o turno roda, que é esta máquina."""
    import asyncio

    from .identidade import contexto as _contexto

    blocos = await asyncio.to_thread(_contexto, nome)
    if blocos is None:
        raise HTTPException(status_code=404, detail=f"não existe residente '{nome}'")
    return {"blocos": blocos}


@router.get("/{nome}/conversa")
async def conversa(nome: str) -> Dict[str, Any]:
    return await _chamar(_cliente.conversa(nome))


@router.post("/{nome}/conversa", status_code=201)
async def pedir_na_conversa(nome: str, corpo: PedidoNaConversa) -> Dict[str, Any]:
    return await _chamar(_cliente.pedir_na_conversa(nome, corpo))


@router.get("/{nome}/rotinas")
async def rotinas(nome: str) -> Dict[str, Any]:
    return await _chamar(_cliente.rotinas(nome))


@router.post("/{nome}/rotinas", status_code=201)
async def criar_rotina(nome: str, corpo: NovaRotina) -> Dict[str, Any]:
    return await _chamar(_cliente.criar_rotina(nome, corpo.model_dump()))


@router.patch("/{nome}/rotinas/{rotina_id}")
async def mudar_rotina(nome: str, rotina_id: str, corpo: EstadoDaRotina) -> Dict[str, Any]:
    return await _chamar(_cliente.mudar_rotina(nome, rotina_id, corpo.ativa, corpo.model_dump(exclude_unset=True, exclude={"ativa"})))


@router.delete("/{nome}/rotinas/{rotina_id}")
async def apagar_rotina(nome: str, rotina_id: str) -> Dict[str, Any]:
    return await _chamar(_cliente.apagar_rotina(nome, rotina_id))


@router.patch("/{nome}")
async def editar(nome: str, campos: Dict[str, Any]) -> Dict[str, Any]:
    return await _chamar(_cliente.editar(nome, campos))


@router.put("/{nome}/acessorios")
async def acessorios(nome: str, corpo: Acessorios) -> Dict[str, Any]:
    return await _chamar(_cliente.trocar_acessorios(nome, corpo.acessorios))


@router.post("/{nome}/tarefas", status_code=201)
async def pedir(nome: str, corpo: NovaTarefa) -> Dict[str, Any]:
    return await _chamar(_cliente.pedir(nome, corpo.pedido, "tela"))


# Uma rota por ação: um `/{nome}/{acao}` genérico engoliria o `/mencao` do main.
@router.post("/{nome}/pausar")
async def pausar(nome: str) -> Dict[str, Any]:
    return await _chamar(_cliente.mudar(nome, "pausar"))


@router.post("/{nome}/retomar")
async def retomar(nome: str) -> Dict[str, Any]:
    return await _chamar(_cliente.mudar(nome, "retomar"))


@router.post("/{nome}/aposentar")
async def aposentar(nome: str) -> Dict[str, Any]:
    return await _chamar(_cliente.mudar(nome, "aposentar"))
