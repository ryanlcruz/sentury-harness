"""Persiste objetivos que atravessam turnos até um critério de conclusão.

O agente propõe e a pessoa aprova antes da execução. Ao declarar conclusão,
o agente apresenta evidência e espera a confirmação da pessoa.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.RLock()

PROPOSTO = "proposto"
ATIVO = "ativo"
PAUSADO = "pausado"
AGUARDANDO = "aguardando_confirmacao"
CUMPRIDO = "cumprido"
ABANDONADO = "abandonado"
ESTADOS = (PROPOSTO, ATIVO, PAUSADO, AGUARDANDO, CUMPRIDO, ABANDONADO)
# Um goal por conversa de cada vez: dois perseguindo coisas diferentes no mesmo
# historico disputariam o contexto e o navegador.
_EM_ABERTO = (PROPOSTO, ATIVO, PAUSADO, AGUARDANDO)

LIMITE_TURNOS_PADRAO = 60
LIMITE_HORAS_PADRAO = 8.0


@dataclass
class Goal:
    id: str
    session_id: str
    user_id: str
    objetivo: str
    criterio: str
    marcos: List[Dict[str, Any]] = field(default_factory=list)
    limite_turnos: int = LIMITE_TURNOS_PADRAO
    limite_horas: float = LIMITE_HORAS_PADRAO
    modo: str = ""
    estado: str = PROPOSTO
    motivo: str = ""
    # Quem parou: "limite", "falha", "permissao", "pergunta", "parado", "pessoa".
    # A permissao respondida retoma sozinha; as outras esperam o "continuar".
    pausado_por: str = ""
    turnos: int = 0
    criado_em: float = 0.0
    iniciado_em: float = 0.0
    atualizado_em: float = 0.0
    evidencia_final: Any = None
    nota_do_dono: str = ""
    eventos: List[Dict[str, Any]] = field(default_factory=list)

    def publico(self) -> Dict[str, Any]:
        dados = asdict(self)
        dados.pop("eventos", None)
        dados["marcos_feitos"] = sum(1 for m in self.marcos if m.get("feito"))
        return dados


class GoalInvalido(ValueError):
    pass


def _pasta() -> Path:
    casa = Path(os.environ.get("SENTURY_HOME") or (Path.home() / ".sentury"))
    pasta = casa / "goals"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _gravar(goal: Goal) -> Goal:
    goal.atualizado_em = time.time()
    alvo = _pasta() / f"{goal.id}.json"
    tmp = alvo.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(goal), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(alvo)
    return goal


def _evento(goal: Goal, tipo: str, **dados: Any) -> None:
    goal.eventos.append({"em": time.time(), "tipo": tipo, **dados})
    del goal.eventos[:-200]


def carregar(goal_id: str) -> Optional[Goal]:
    limpo = "".join(c for c in str(goal_id or "") if c.isalnum() or c in "-_")
    if not limpo:
        return None
    try:
        dados = json.loads((_pasta() / f"{limpo}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    conhecidos = set(Goal.__dataclass_fields__)
    return Goal(**{k: v for k, v in dados.items() if k in conhecidos})


def listar(session_id: str = "", estados: tuple = ()) -> List[Goal]:
    achados = []
    for arquivo in _pasta().glob("*.json"):
        goal = carregar(arquivo.stem)
        if goal is None:
            continue
        if session_id and goal.session_id != session_id:
            continue
        if estados and goal.estado not in estados:
            continue
        achados.append(goal)
    return sorted(achados, key=lambda g: g.criado_em)


def em_aberto(session_id: str) -> Optional[Goal]:
    """O goal da conversa que ainda nao terminou, se houver."""
    abertos = listar(session_id, _EM_ABERTO)
    return abertos[-1] if abertos else None


def _exigir(goal_id: str, *estados: str) -> Goal:
    goal = carregar(goal_id)
    if goal is None:
        raise GoalInvalido(f"goal '{goal_id}' nao existe")
    if estados and goal.estado not in estados:
        raise GoalInvalido(f"goal esta '{goal.estado}'; esperado {' ou '.join(estados)}")
    return goal


def propor(
    session_id: str,
    user_id: str,
    objetivo: str,
    criterio: str,
    marcos: Optional[List[str]] = None,
    *,
    limite_turnos: Optional[int] = None,
    limite_horas: Optional[float] = None,
) -> Goal:
    objetivo, criterio = str(objetivo or "").strip(), str(criterio or "").strip()
    if not objetivo:
        raise GoalInvalido("goal precisa do objetivo")
    if not criterio:
        # Sem criterio de pronto, "cumpri" vira opiniao: e o executor nao
        # teria contra o que parar.
        raise GoalInvalido("goal precisa do criterio de pronto: como saber que terminou")
    with _LOCK:
        aberto = em_aberto(session_id)
        if aberto is not None and aberto.estado != PROPOSTO:
            raise GoalInvalido(f"esta conversa ja tem um goal {aberto.estado}: '{aberto.objetivo}'")
        if aberto is not None:
            # Proposta nova substitui a que nao foi aprovada.
            aberto.estado, aberto.motivo = ABANDONADO, "substituido por outra proposta"
            _gravar(aberto)
        agora = time.time()
        goal = Goal(
            id=f"G-{uuid.uuid4().hex[:10]}", session_id=str(session_id), user_id=str(user_id),
            objetivo=objetivo, criterio=criterio,
            marcos=[{"titulo": str(m).strip(), "feito": False, "evidencia": None, "em": None}
                    for m in (marcos or []) if str(m).strip()],
            limite_turnos=max(1, int(limite_turnos or LIMITE_TURNOS_PADRAO)),
            limite_horas=max(0.1, float(limite_horas or LIMITE_HORAS_PADRAO)),
            criado_em=agora,
        )
        _evento(goal, "proposto")
        return _gravar(goal)


def aprovar(goal_id: str, modo: str = "") -> Goal:
    with _LOCK:
        goal = _exigir(goal_id, PROPOSTO)
        goal.estado, goal.motivo, goal.modo = ATIVO, "", str(modo or "")
        goal.iniciado_em = time.time()
        _evento(goal, "aprovado", modo=goal.modo)
        return _gravar(goal)


def pausar(goal_id: str, motivo: str, *, por: str = "pessoa") -> Goal:
    with _LOCK:
        goal = _exigir(goal_id, ATIVO)
        goal.estado, goal.motivo, goal.pausado_por = PAUSADO, str(motivo or "pausado")[:300], str(por)
        _evento(goal, "pausado", motivo=goal.motivo, por=goal.pausado_por)
        return _gravar(goal)


def retomar(goal_id: str, *, mais_turnos: int = 0) -> Goal:
    """Volta a ativo. `mais_turnos` estende o limite quando foi ele que parou."""
    with _LOCK:
        goal = _exigir(goal_id, PAUSADO)
        goal.estado, goal.motivo, goal.pausado_por = ATIVO, "", ""
        if mais_turnos:
            goal.limite_turnos += int(mais_turnos)
        _evento(goal, "retomado", mais_turnos=int(mais_turnos or 0))
        return _gravar(goal)


def continuar(goal_id: str) -> Goal:
    """O "continuar" da pessoa. Se foi o limite de turnos que parou, sem mais
    turnos o goal pararia de novo no primeiro passo: estende sozinho."""
    goal = _exigir(goal_id, PAUSADO)
    mais = 0
    if goal.pausado_por == "limite" and goal.turnos >= goal.limite_turnos:
        mais = max(10, goal.limite_turnos // 2)
    return retomar(goal_id, mais_turnos=mais)


def marcar(goal_id: str, titulo: str, evidencia: Any) -> Goal:
    """Um marco cumprido. Marco que nao estava na lista entra no fim."""
    if not str(evidencia or "").strip():
        raise GoalInvalido("marco sem evidencia nao conta: diga o que prova (print, URL, trecho)")
    with _LOCK:
        goal = _exigir(goal_id, ATIVO, PAUSADO)
        alvo = str(titulo or "").strip()
        marco = next((m for m in goal.marcos if m["titulo"].lower() == alvo.lower()), None)
        if marco is None:
            marco = {"titulo": alvo, "feito": False, "evidencia": None, "em": None}
            goal.marcos.append(marco)
        marco.update(feito=True, evidencia=evidencia, em=time.time())
        _evento(goal, "marco", titulo=alvo)
        return _gravar(goal)


def declarar_cumprido(goal_id: str, evidencia: Any) -> Goal:
    if not str(evidencia or "").strip():
        raise GoalInvalido("declarar cumprido exige a evidencia que prova o criterio")
    with _LOCK:
        goal = _exigir(goal_id, ATIVO, PAUSADO)
        goal.estado, goal.evidencia_final, goal.motivo = AGUARDANDO, evidencia, ""
        _evento(goal, "declarado_cumprido")
        return _gravar(goal)


def confirmar(goal_id: str, cumprido: bool, nota: str = "") -> Goal:
    """A palavra final e da pessoa. "Nao" devolve o goal ao trabalho."""
    with _LOCK:
        goal = _exigir(goal_id, AGUARDANDO)
        goal.nota_do_dono = str(nota or "")[:1000]
        if cumprido:
            goal.estado = CUMPRIDO
            _evento(goal, "confirmado")
        else:
            goal.estado, goal.evidencia_final = ATIVO, None
            _evento(goal, "recusado", nota=goal.nota_do_dono)
        return _gravar(goal)


def abandonar(goal_id: str, motivo: str = "") -> Goal:
    with _LOCK:
        goal = _exigir(goal_id, *_EM_ABERTO)
        goal.estado, goal.motivo = ABANDONADO, str(motivo or "abandonado")[:300]
        _evento(goal, "abandonado", motivo=goal.motivo)
        return _gravar(goal)


def contar_turno(goal_id: str) -> Goal:
    with _LOCK:
        goal = _exigir(goal_id, ATIVO)
        goal.turnos += 1
        return _gravar(goal)


def limite_estourado(goal: Goal, agora: Optional[float] = None) -> Optional[str]:
    """Por que parar agora, ou None. O limite e o que impede um goal travado de
    queimar cota a noite inteira."""
    if goal.turnos >= goal.limite_turnos:
        return f"chegou ao limite de {goal.limite_turnos} turnos"
    decorrido = ((time.time() if agora is None else agora) - (goal.iniciado_em or time.time())) / 3600
    if decorrido >= goal.limite_horas:
        return f"chegou ao limite de {goal.limite_horas:g} h"
    return None


def mensagem_de_continuacao(goal: Goal) -> str:
    """O que o executor manda ao agente a cada turno. Aparece na conversa com a
    marca de automatico: quem le o historico sabe que nao foi a pessoa."""
    marcos = "\n".join(f"- [{'x' if m.get('feito') else ' '}] {m['titulo']}" for m in goal.marcos) \
        or "- (sem marcos declarados)"
    nota = f"\nA pessoa disse que ainda nao cumpriu: {goal.nota_do_dono}" if goal.nota_do_dono \
        and goal.estado == ATIVO else ""
    return (
        f"[continuacao automatica do goal, turno {goal.turnos} de {goal.limite_turnos}]\n"
        f"Objetivo: {goal.objetivo}\nPronto quando: {goal.criterio}\nMarcos:\n{marcos}{nota}\n"
        "Faca o proximo passo concreto. Cumpriu um marco: `goal` com acao `marco` e a evidencia. "
        "Cumpriu o criterio inteiro: `goal` com acao `cumprido` e a evidencia. Travado: diga por que."
    )


__all__ = [
    "ABANDONADO", "AGUARDANDO", "ATIVO", "CUMPRIDO", "ESTADOS", "Goal", "GoalInvalido",
    "PAUSADO", "PROPOSTO", "abandonar", "aprovar", "carregar", "confirmar", "continuar",
    "contar_turno",
    "declarar_cumprido", "em_aberto", "limite_estourado", "listar", "marcar",
    "mensagem_de_continuacao", "pausar", "propor", "retomar",
]
