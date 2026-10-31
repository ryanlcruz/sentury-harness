"""A aba do Mutation: o ciclo de cada mutação, pela autenticação do Sentury.

Propor abre a cópia isolada; quem constrói edita lá dentro; medir roda os
portões; promover e reverter são decisões humanas, com o nome de quem decidiu.
O merge continua fora daqui: quem move código para o runtime é quem decidiu,
com o diff na frente.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException

from . import ciclo, isolamento, medir, registro

router = APIRouter(prefix="/sentury/mutacoes", tags=["mutacao"])


def _repo() -> str:
    """A raiz do repositório do Sentury, qualquer que seja a pasta do processo."""
    return str(Path(__file__).resolve().parents[2])


def _ou_conflito(resultado: Dict[str, Any]) -> Dict[str, Any]:
    if not resultado.get("ok", True):
        raise HTTPException(409, str(resultado.get("erro") or "operacao recusada"))
    return resultado


def _texto(dados: Dict[str, Any], campo: str) -> str:
    valor = " ".join(str(dados.get(campo) or "").split())
    if not valor:
        raise HTTPException(400, f"falta `{campo}`")
    return valor


@router.get("")
def listar() -> Dict[str, Any]:
    repo = _repo()
    return {**ciclo.estado_geral(), "medindo": medir.medindo(),
            "arvore_limpa": isolamento.arvore_limpa(repo),
            "baseline": isolamento.commit_atual(repo),
            "portoes": [nome for nome, _, _ in medir.PORTOES],
            "estados": {nome: list(destinos) for nome, destinos in registro.ESTADOS.items()}}


@router.get("/sinais")
def ver_sinais() -> Dict[str, Any]:
    """O que o uso real mostrou e pode virar mutação."""
    from . import sinais

    return {"sinais": sinais.listar()}


def _modelo_auxiliar() -> Any:
    try:
        from .. import main

        return main.auxiliar_llm
    except Exception:
        return None


@router.post("/rascunho")
async def rascunhar(dados: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Uma frase, ou um sinal, vira alvo e hipótese para a pessoa conferir."""
    from robinbandit.sentury import no_ultra

    from . import rascunho, sinais

    texto = str(dados.get("texto") or "")
    sinal = sinais.por_id(str(dados.get("sinal") or "")) if dados.get("sinal") else {}
    if not texto.strip() and not sinal:
        raise HTTPException(400, "diga o que melhorar ou escolha um sinal")
    # O modo da tela (Reforçado ou Dedicado) vale aqui como vale no chat: fora
    # dele o pedido cairia no roteamento automático, que pode nem estar configurado.
    from robinbandit.sentury import clear_ultra_provider, use_ultra_provider

    from .. import main

    nivel = main._tier_provider_for(str(dados.get("modo") or ""))
    if nivel is None:
        with no_ultra():
            redigido = await rascunho.redigir(texto, sinal, _modelo_auxiliar())
    else:
        marca = use_ultra_provider(nivel)
        try:
            redigido = await rascunho.redigir(texto, sinal, _modelo_auxiliar())
        finally:
            clear_ultra_provider(marca)
    return {**redigido, "sinal": sinal or None}


@router.get("/{mutacao_id}")
def ver(mutacao_id: str) -> Dict[str, Any]:
    mutacao = registro.carregar(mutacao_id)
    if mutacao is None:
        raise HTTPException(404, f"mutacao desconhecida: {mutacao_id}")
    diff = isolamento.diferenca(mutacao_id, base=mutacao.baseline_commit or "HEAD", com_patch=True)
    return {**asdict(mutacao), "diff": diff if diff.get("ok") else None,
            "medindo": medir.medindo() == mutacao_id}


@router.post("")
def propor(dados: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return _ou_conflito(ciclo.propor(
        alvo=_texto(dados, "alvo"), hipotese=_texto(dados, "hipotese"),
        observacao=" ".join(str(dados.get("observacao") or "").split()),
        parent=str(dados.get("parent") or ""), repo=_repo()))


def _decisao(funcao, *args, **kwargs) -> Dict[str, Any]:
    try:
        return _ou_conflito(funcao(*args, **kwargs))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{mutacao_id}/construida")
def construida(mutacao_id: str) -> Dict[str, Any]:
    return _decisao(ciclo.construida, mutacao_id)


@router.post("/{mutacao_id}/medir")
def medir_agora(mutacao_id: str) -> Dict[str, Any]:
    return _ou_conflito(medir.iniciar(mutacao_id))


@router.post("/{mutacao_id}/promover")
def promover(mutacao_id: str, dados: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return _decisao(ciclo.promover, mutacao_id, decidido_por=_texto(dados, "decidido_por"))


@router.post("/{mutacao_id}/rejeitar")
def rejeitar(mutacao_id: str, dados: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Recusa humana de uma aprovada: os portões passaram, mas quem decide não quis."""
    motivo = _texto(dados, "motivo")
    try:
        registro.transicionar(mutacao_id, "rejeitada", motivo=motivo)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "id": mutacao_id, "estado": "rejeitada"}


@router.post("/{mutacao_id}/descartar")
def descartar(mutacao_id: str, dados: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Desiste de uma proposta ou candidata antes de medir. O registro fica."""
    motivo = _texto(dados, "motivo")
    try:
        registro.transicionar(mutacao_id, "descartada", motivo=motivo)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _ou_conflito(ciclo.limpar_copia(mutacao_id, repo=_repo()))


@router.post("/{mutacao_id}/reverter")
def reverter(mutacao_id: str, dados: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return _decisao(ciclo.reverter, mutacao_id, motivo=_texto(dados, "motivo"), repo=_repo())


@router.post("/{mutacao_id}/limpar")
def limpar(mutacao_id: str) -> Dict[str, Any]:
    return _ou_conflito(ciclo.limpar_copia(mutacao_id, repo=_repo()))


__all__ = ["router"]
