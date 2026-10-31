"""Quem está agendando, para as ferramentas alcançarem o agendador.

O `CronScheduler` nasce no `main.py`, junto do orquestrador e do store, e as
ferramentas rodam num módulo que não conhece o `main`. Em vez de passar a
instância por seis assinaturas até chegar lá, ela se registra aqui.

É um ponteiro só, escrito uma vez no arranque. Quando não há nada registrado
num teste, ou num modo sem agendamento: as ferramentas dizem isso em vez
de estourar.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_ATIVO: Optional[Any] = None


def registrar(agendador: Any) -> None:
    global _ATIVO
    _ATIVO = agendador


def atual() -> Optional[Any]:
    return _ATIVO


def limpar() -> None:
    """Só para teste: solta a instância registrada."""
    global _ATIVO
    _ATIVO = None


def _indisponivel() -> Dict[str, Any]:
    return {"ok": False, "erro": "agendamento indisponivel nesta instalacao"}


def agendar(
    *,
    session_id: str,
    user_id: str,
    tarefa: str,
    cron: str = "",
    intervalo_seg: Optional[int] = None,
    quando: str = "",
    executar_em: str = "",
) -> Dict[str, Any]:
    """Cria um agendamento.

    Aceita três formas, na ordem em que confia nelas:

    1. `cron`: expressão cron. É o que o modelo devolve quando entende o
       pedido ("toda segunda de manhã" → `0 9 * * 1`), e é a forma exata.
    2. `intervalo_seg`: para "a cada N minutos".
    3. `quando` em texto: último recurso, passa pelo mesmo interpretador dos
       comandos de barra. Só cobre dois moldes de frase, e foi justamente por
       depender dele que o agendamento parecia não existir: quem escrevesse
       fora do molde não agendava nada.
    """
    agendador = atual()
    if agendador is None:
        return _indisponivel()

    tarefa = (tarefa or "").strip()
    if not tarefa:
        return {"ok": False, "erro": "falta dizer O QUE deve rodar no horario"}

    cron = (cron or "").strip()
    once_delay: Optional[int] = None
    once_at = str(executar_em or "").strip()
    if not cron and intervalo_seg is None and not once_at and quando:
        from .cron_scheduler import parse_cron_command

        lido = parse_cron_command(quando)
        if lido:
            cron = lido.get("cron_expr") or ""
            intervalo_seg = lido.get("interval_sec")
            once_delay = lido.get("delay_sec")
            once_at = str(lido.get("run_at") or "")
    if not cron and intervalo_seg is None and once_delay is None and not once_at:
        return {
            "ok": False,
            "erro": (
                "falta quando rodar: mande `cron` (ex.: '0 9 * * 1' para toda "
                "segunda as 9h), `intervalo_seg` ou `executar_em` (ISO 8601)"
            ),
        }

    # Agendado por um residente, o job é dele: aparece com o dono na tela e dispara
    # pela fila dele, com orçamento e só as ferramentas do manifesto.
    dono = _residente_do_turno()
    deles = {"residente": dono.nome, "residente_criado_em": dono.criado_em} if dono else {}
    try:
        if once_delay is not None or once_at:
            job = agendador.add_once_job(
                session_id, user_id, tarefa,
                delay_sec=once_delay, run_at=once_at or None, **deles,
            )
        else:
            job = agendador.add_job(
                session_id, user_id, tarefa,
                interval_sec=intervalo_seg, cron_expr=cron or None, **deles,
            )
    except ValueError as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": True, **job}


# Cinco campos nao bastam: "quando chegar o relatorio mensal" tem cinco
# palavras e virava `0 8 * * 1` sem ninguem notar: um horario inventado a
# partir de uma frase que nao falava de horario. Cada campo tem que ser feito
# so dos caracteres que o cron usa.
_CAMPO_DE_CRON = re.compile(r"^[0-9*/,\-]+$")


def _parece_cron(texto: str) -> bool:
    campos = str(texto or "").split()
    return len(campos) == 5 and all(_CAMPO_DE_CRON.match(c) for c in campos)


def agendar_workflow(
    *,
    session_id: str,
    user_id: str,
    workflow: str,
    gatilho: str,
    ativo: bool = False,
) -> Dict[str, Any]:
    """Liga a receita persistida ao relógio.

    `criar_workflow` é a porta de alto nível: o modelo não precisa chamar uma
    segunda ferramenta de cron nem duplicar os passos num prompt solto.
    """
    agendador = atual()
    if agendador is None:
        return _indisponivel()

    nome = str(workflow or "").strip()
    quando = str(gatilho or "").strip()
    if not nome:
        return {"ok": False, "erro": "falta o nome do workflow"}

    cron = quando if _parece_cron(quando) else ""
    intervalo_seg: Optional[int] = None
    if not cron:
        from .cron_scheduler import parse_cron_command

        lido = parse_cron_command(quando)
        if lido:
            cron = str(lido.get("cron_expr") or "")
            intervalo_seg = lido.get("interval_sec")
    if not cron and intervalo_seg is None:
        # Nem todo gatilho e relogio. "quando chegar o relatorio", "se a fila
        # passar de 50" sao gatilhos legitimos, e o agendador nao tem o que
        # fazer com eles: quem dispara e um vigia, que ainda nao existe. O
        # campo separa isso de falha de verdade -- a receita esta correta.
        return {
            "ok": False,
            "por_evento": True,
            "erro": (
                "gatilho por evento: nao e relogio, entao nao ha o que agendar "
                "(cron '0 8 * * 1' ou intervalo 'a cada 30 minutos' agendam)"
            ),
        }

    # Recriar uma receita atualiza seu relógio em vez de produzir duas rotinas
    # iguais, ambas cobrando e respondendo na mesma conversa.
    for existente in list(agendador.list_jobs()):
        if existente.get("workflow") == nome:
            agendador.remove_job(existente["id"])

    try:
        job = agendador.add_job(
            session_id,
            user_id,
            f"Execute o workflow '{nome}'.",
            interval_sec=intervalo_seg,
            cron_expr=cron or None,
            workflow=nome,
            active=ativo,
        )
    except ValueError as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": True, **job}


def listar(session_id: Optional[str] = None) -> Dict[str, Any]:
    agendador = atual()
    if agendador is None:
        return _indisponivel()
    return {"ok": True, "agendamentos": agendador.list_jobs(session_id)}


def _residente_do_turno():
    from ..residentes.escopo import agente_do_turno

    return agente_do_turno()


def cancelar(job_id: str) -> Dict[str, Any]:
    agendador = atual()
    if agendador is None:
        return _indisponivel()
    alvo = str(job_id or "").strip()
    if not alvo:
        return {"ok": False, "erro": "falta o id do agendamento"}
    dono = _residente_do_turno()
    jobs = getattr(agendador, "jobs", None)
    job = jobs.get(alvo) if dono and isinstance(jobs, dict) else None
    if dono and job is not None and job.get("residente") != dono.nome:
        return {"ok": False, "erro": "esse agendamento não é seu; quem pode cancelar é a pessoa ou o dono dele"}
    if agendador.remove_job(alvo):
        return {"ok": True, "removido": alvo}
    return {"ok": False, "erro": f"nao encontrei o agendamento '{alvo}'"}


def ativar(job_id: str, ativo: bool = True) -> Dict[str, Any]:
    agendador = atual()
    if agendador is None:
        return _indisponivel()
    try:
        job = agendador.set_active(str(job_id or "").strip(), ativo)
    except ValueError as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": True, **job}


__all__ = [
    "agendar", "agendar_workflow", "ativar", "atual", "cancelar", "limpar", "listar", "registrar",
]
