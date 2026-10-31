"""Quem acorda o agente quando chega tarefa, e o põe para dormir quando a fila esvazia.

Uma tarefa asyncio por agente acordado, nunca duas. Ela pega a tarefa mais
antiga, roda um turno vestido de agente e fecha a tarefa pelo resultado. Fila
vazia, orçamento acabado ou tarefa esperando a pessoa: o laço termina e o
agente volta a `dormindo`. O turno em si é do `main` (`configurar(rodar)`),
que sabe carregar a conversa do agente e gravar.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from . import manifesto as _m
from . import orcamento as _orcamento
from . import registro as _registro
from . import tarefas as _tarefas

logger = logging.getLogger(__name__)

Rodar = Callable[[_m.Manifesto, _tarefas.Tarefa], Awaitable[Dict[str, Any]]]
Observador = Callable[[_tarefas.Tarefa], Any]

_LACOS: Dict[str, asyncio.Task] = {}
_RODAR: Optional[Rodar] = None
_OBSERVADORES: List[Observador] = []
# Chamados em todo fim de tarefa, avise a pessoa ou não (a Mesa usa).
_AO_TERMINAR: List[Observador] = []


def configurar(rodar: Optional[Rodar]) -> None:
    global _RODAR
    _RODAR = rodar


def observar(funcao: Observador) -> None:
    """Chamado quando uma tarefa termina ou para esperando: é por aqui que a
    resposta volta ao canal de origem."""
    if funcao not in _OBSERVADORES:
        _OBSERVADORES.append(funcao)


def ao_terminar(funcao: Observador) -> None:
    if funcao not in _AO_TERMINAR:
        _AO_TERMINAR.append(funcao)


# Cada agente tem duas faixas: o trabalho e a Mesa. A conversa não espera uma tarefa longa.
FAIXAS = (False, True)


def _chave(nome: str, mesa: bool) -> str:
    return f"{nome}#mesa" if mesa else nome


def _vivo(chave: str) -> bool:
    laco = _LACOS.get(chave)
    # Laço preso a um event loop já fechado nunca mais roda: não conta como acordado.
    return bool(laco and not laco.done() and not laco.get_loop().is_closed())


def acordado(nome: str) -> bool:
    return any(_vivo(_chave(nome, mesa)) for mesa in FAIXAS)


def acordar(nome: str) -> bool:
    """Liga as faixas do agente que têm fila. Idempotente: faixa acordada fica como está."""
    if _RODAR is None:
        return False
    ligou = False
    for mesa in FAIXAS:
        chave = _chave(nome, mesa)
        if not _vivo(chave) and _tarefas.proxima(nome, mesa) is not None:
            _LACOS[chave] = asyncio.get_running_loop().create_task(_laco(nome, mesa))
            ligou = True
    return ligou


def rearmar() -> int:
    """No startup: devolve à fila o que caiu no meio e acorda quem tem fila."""
    _tarefas.recuperar()
    nomes = {t.agente for t in _tarefas.listar(estados=(_tarefas.NA_FILA,))}
    return sum(acordar(nome) for nome in sorted(nomes))


async def parar_todos() -> None:
    lacos = [laco for laco in _LACOS.values() if not laco.done()]
    for laco in lacos:
        laco.cancel()
    await asyncio.gather(*lacos, return_exceptions=True)
    _LACOS.clear()


def _custo(resultado: Dict[str, Any]) -> Optional[float]:
    """O custo do turno, ou None quando ninguém sabe quanto custou."""
    try:
        valor = (resultado.get("telemetry") or {}).get("custo_usd")
        return None if valor is None else float(valor)
    except (TypeError, ValueError):
        return None


def _fechar(tarefa: _tarefas.Tarefa, resultado: Any) -> _tarefas.Tarefa:
    if isinstance(resultado, dict) and resultado.get("controle_interrompido"):
        return _tarefas.carregar(tarefa.id)
    if not isinstance(resultado, dict):
        return _tarefas.falhar(tarefa.id, "o turno não devolveu resultado")
    custo = _custo(resultado)
    resposta = str(resultado.get("message") or "")
    if resultado.get("falhou"):
        # A vez na Mesa não volta para a fila: a conversa inteira esperaria cada nova tentativa.
        # Ela passa com o motivo, e quem tem a vez seguinte fala.
        return _tarefas.falhar(tarefa.id, str(resultado.get("erro") or "o turno falhou")[:300], custo,
                               de_novo=not _tarefas.da_mesa(tarefa))
    permissao = resultado.get("permissao")
    if permissao:
        alvo = (permissao.get("comando") or permissao.get("ferramenta") or "") \
            if isinstance(permissao, dict) else ""
        if alvo.startswith(_tarefas.PEDIDO_DE_FERRAMENTA):
            motivo = f"pediu a ferramenta {alvo[len(_tarefas.PEDIDO_DE_FERRAMENTA):].strip()}"
            porque = str((permissao.get("argumentos") or {}).get("motivo") or "").strip()
            motivo = f"{motivo}: {porque}" if porque else motivo
        else:
            motivo = f"precisa da sua autorização: {alvo}".strip().rstrip(":")
        return _tarefas.esperar(tarefa.id, motivo, resposta, custo, pendente=alvo)
    if resultado.get("clarification"):
        return _tarefas.esperar(tarefa.id, "o agente fez uma pergunta", resposta, custo)
    # A vez na Mesa não espera os colegas: o que ela pediu são próximos passos, que andam na fila
    # de cada dono enquanto a conversa segue (ou fecha).
    colegas = [] if _tarefas.da_mesa(tarefa) else _tarefas.filhos(tarefa.id, so_nao_entregues=True)
    if colegas:
        nomes = ", ".join(sorted({c.agente[:1].upper() + c.agente[1:] for c in colegas}))
        esperando = _tarefas.esperar(tarefa.id, f"aguardando {nomes}", resposta, custo,
                                     aguardando=[c.id for c in colegas])
        # O colega pode ter terminado antes deste turno acabar.
        return _tarefas.liberar_se_os_colegas_terminaram(tarefa.id) or esperando
    return _tarefas.concluir(tarefa.id, resposta, custo)


def _vale_avisar(tarefa: _tarefas.Tarefa) -> bool:
    """A pessoa é avisada do que pede ela. Esperar colega não pede, e o fim do
    pedido de um colega volta para quem pediu, não para ela."""
    if tarefa.estado == _tarefas.ESPERANDO:
        return not tarefa.aguardando
    interna = tarefa.origem.startswith(("agente:", "mesa:"))
    return tarefa.estado != _tarefas.NA_FILA and not interna


def terminou(tarefa: _tarefas.Tarefa) -> None:
    """Fim de tarefa: quem pediu volta a andar se era o último colega, e a
    Mesa passa a vez."""
    if tarefa.estado not in _tarefas.TERMINADAS:
        return
    for funcao in list(_AO_TERMINAR):
        try:
            funcao(tarefa)
        except Exception:
            logger.warning("Gancho de fim da tarefa %s falhou.", tarefa.id, exc_info=True)
    if not tarefa.pai:
        return
    liberada = _tarefas.liberar_se_os_colegas_terminaram(tarefa.pai)
    if liberada is not None:
        try:
            acordar(liberada.agente)
        except RuntimeError:
            pass  # sem loop rodando: o rearmar do startup acorda


def _avisar(tarefa: _tarefas.Tarefa) -> None:
    for funcao in list(_OBSERVADORES):
        try:
            retorno = funcao(tarefa)
            if asyncio.iscoroutine(retorno):
                asyncio.get_running_loop().create_task(retorno)
        except Exception:
            logger.warning("Observador da tarefa %s falhou.", tarefa.id, exc_info=True)


async def _laco(nome: str, mesa: bool = False) -> None:
    try:
        while True:
            agente = _registro.carregar(nome)
            if agente is None or agente.estado in (_m.PAUSADO, _m.APOSENTADO):
                return
            tarefa = _tarefas.proxima(nome, mesa)
            if tarefa is None:
                return
            motivo = _orcamento.corte(agente)
            if motivo and tarefa.origem.startswith(("agente:", "mesa:")):
                # O colega que pediu não espera até amanhã: recebe o motivo e segue. Na Mesa,
                # a vez passa com o motivo e a conversa continua com os outros.
                terminou(_tarefas.cancelar(tarefa.id, motivo))
                continue
            if motivo:
                # O pedido da pessoa fica na fila: amanhã, ou com orçamento novo, ele anda.
                _tarefas.anotar(tarefa.id, motivo)
                return
            tarefa = _tarefas.comecar(tarefa.id)
            _registro.mudar_estado(nome, _m.TRABALHANDO)
            try:
                from .controle_da_tela import rodar
                resultado = await rodar(agente, tarefa, _RODAR)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Agente %s: a tarefa %s falhou: %s", nome, tarefa.id, exc)
                resultado = {"falhou": True, "erro": str(exc)[:300]}
            fechada = _fechar(tarefa, resultado)
            if _vale_avisar(fechada):
                _avisar(fechada)
            terminou(fechada)
    finally:
        agente = _registro.carregar(nome)
        # Dorme só quando a outra faixa também parou.
        outra_rodando = bool(_tarefas.listar(nome, (_tarefas.RODANDO,)))
        if agente is not None and agente.estado == _m.TRABALHANDO and not outra_rodando:
            _registro.mudar_estado(nome, _m.DORMINDO)
        if _LACOS.get(_chave(nome, mesa)) is asyncio.current_task():
            _LACOS.pop(_chave(nome, mesa), None)


__all__ = ["acordado", "acordar", "ao_terminar", "configurar", "observar", "parar_todos", "rearmar",
           "terminou"]
