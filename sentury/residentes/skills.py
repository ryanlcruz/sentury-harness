"""As skills do residente: o Sentury escolhe ao criar, e elas entram carregadas em
toda tarefa dele. O residente não carrega skill por conta própria (`executar_skill`
é do Sentury); quem põe o procedimento no turno é o harness, junto da identidade.
A skill que a pessoa cita com `/nome` no pedido entra também, só naquele turno."""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, List, Optional

from .manifesto import ManifestoInvalido

logger = logging.getLogger(__name__)

MARCA = "skill_do_residente"
TETO_DE_SKILLS = 6
# Várias skills longas tomariam o contexto da tarefa inteira.
TETO_DO_CONTEXTO = 16_000
_CITADA = re.compile(r"(?:^|\s)/([a-z0-9][a-z0-9_-]{1,80})(?=\s|$|[.,;:!?])", re.IGNORECASE)


def _carregador():
    from ..skills.escrita import pasta_do_usuario, pasta_embutida
    from ..skills.skill_loader import SkillLoader

    return SkillLoader(pasta_embutida(), pasta_do_usuario(), com_setor=True)


def instaladas() -> set:
    return {entrada.name for entrada in _carregador().scan_skills()}


def validar(nomes: Any) -> List[str]:
    """A lista do manifesto: só skills instaladas, sem repetição."""
    if isinstance(nomes, str):
        nomes = nomes.split(",")
    limpos = sorted({str(n).strip().lower().lstrip("/") for n in (nomes or []) if str(n).strip()})
    if len(limpos) > TETO_DE_SKILLS:
        raise ManifestoInvalido(f"um residente leva até {TETO_DE_SKILLS} skills")
    if limpos:
        desconhecidas = [n for n in limpos if n not in instaladas()]
        if desconhecidas:
            raise ManifestoInvalido(f"skills que não estão instaladas: {', '.join(desconhecidas)}")
    return limpos


def citadas(texto: str, conhecidas: Iterable[str]) -> List[str]:
    validas = set(conhecidas)
    vistas: List[str] = []
    for nome in _CITADA.findall(texto or ""):
        nome = nome.lower()
        if nome in validas and nome not in vistas:
            vistas.append(nome)
    return vistas


def blocos(agente: Any, mensagem: str = "", session_id: Optional[str] = None) -> List[str]:
    """Os blocos de contexto das skills deste turno, dentro do teto de tamanho."""
    proprias = list(getattr(agente, "skills", None) or [])
    extras = citadas(mensagem, instaladas()) if "/" in (mensagem or "") else []
    nomes = proprias + [n for n in extras if n not in proprias]
    if not nomes:
        return []
    carregador = _carregador()
    entraram: List[str] = []
    fora: List[str] = []
    total = 0
    for nome in nomes:
        conteudo = carregador.load_skill(nome, session_id=session_id)
        if conteudo is None:
            logger.info("A skill %s de %s não está mais instalada.", nome, agente.nome)
            continue
        bloco = conteudo.to_context_block()
        if total + len(bloco) > TETO_DO_CONTEXTO:
            fora.append(nome)
            continue
        entraram.append(bloco)
        total += len(bloco)
    if fora:
        entraram.append(f"Ficaram fora deste turno por tamanho: {', '.join(fora)}. Se a tarefa "
                        "depende de uma delas, diga isso na resposta.")
    return entraram
