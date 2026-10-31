"""O manifesto do agente: quem ele é, o que persegue e o que pode usar.

Nasce de uma proposta do Sentury e só vale depois que a pessoa aprova. A
validação aqui é a única porta: o registro nunca grava manifesto que não passou
por `validar`.
"""
from __future__ import annotations

import difflib
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

NOME_VALIDO = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
CANAIS = ("telegram",)

# Estados do agente. `dormindo` é o normal: existe, sem tarefa rodando.
DORMINDO = "dormindo"
TRABALHANDO = "trabalhando"
PAUSADO = "pausado"
APOSENTADO = "aposentado"
ESTADOS = (DORMINDO, TRABALHANDO, PAUSADO, APOSENTADO)

ORCAMENTO_PADRAO = {"usd_por_dia": 1.0, "turnos_por_dia": 60}
# O que o residente faz sem ninguém mandar, e quanto: assuntos que ele abre por
# dia e falas dele em cada assunto da Mesa.
AUTONOMIA_PADRAO = {"iniciativas_por_dia": 3, "falas_por_assunto": 3}
TETO_DA_AUTONOMIA = 20


class ManifestoInvalido(ValueError):
    pass


@dataclass
class Manifesto:
    nome: str
    papel: str
    objetivo: str
    ferramentas: List[str] = field(default_factory=list)
    # Skills instaladas que entram carregadas em toda tarefa dele.
    skills: List[str] = field(default_factory=list)
    personalidade: str = ""
    instrucoes: str = ""
    # Provedor e modelo fixos, e o que fazer se cair (vazio: o Router inteiro).
    cerebro: Dict[str, str] = field(default_factory=dict)
    # Família e plumagem são do Sentury; os acessórios, da pessoa.
    aparencia: Dict[str, Any] = field(default_factory=dict)
    canais: List[str] = field(default_factory=list)
    orcamento: Dict[str, float] = field(default_factory=lambda: dict(ORCAMENTO_PADRAO))
    autonomia: Dict[str, int] = field(default_factory=lambda: dict(AUTONOMIA_PADRAO))
    rede: str = "nenhuma"
    estado: str = DORMINDO
    criado_por: str = ""
    criado_em: float = 0.0
    atualizado_em: float = 0.0

    def para_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def de_dict(cls, dados: Dict[str, Any]) -> "Manifesto":
        conhecidos = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (dados or {}).items() if k in conhecidos})


def _ferramentas_conhecidas() -> set:
    from ..tools.registry import TOOL_REGISTRY

    return set(TOOL_REGISTRY)


def _proibidas() -> set:
    """O que um residente nunca recebe: mexer na tela da pessoa e criar outros
    agentes. A HQ não tem tela, e agente criando agente fica para depois."""
    return {"computador", "criar_agente"}


def _texto(dados: Dict[str, Any], chave: str, teto: int, *, obrigatorio: bool = False) -> str:
    valor = str(dados.get(chave) or "").strip()
    if obrigatorio and not valor:
        raise ManifestoInvalido(f"'{chave}' é obrigatório")
    if len(valor) > teto:
        raise ManifestoInvalido(f"'{chave}' passa de {teto} caracteres")
    return valor


def validar(dados: Dict[str, Any]) -> Manifesto:
    """Manifesto pronto para gravar, ou `ManifestoInvalido` com o motivo."""
    if not isinstance(dados, dict):
        raise ManifestoInvalido("o manifesto precisa ser um objeto")
    nome = str(dados.get("nome") or "").strip().lower()
    if not NOME_VALIDO.match(nome):
        raise ManifestoInvalido(
            "nome: minúsculas, números e hífen, começando por letra, de 2 a 31 caracteres")

    ferramentas = dados.get("ferramentas") or []
    if isinstance(ferramentas, str):
        ferramentas = [f.strip() for f in ferramentas.split(",")]
    ferramentas = sorted({str(f).strip() for f in ferramentas if str(f).strip()})
    if not ferramentas:
        raise ManifestoInvalido("'ferramentas' não pode ser vazio: o agente precisa de pelo menos uma")
    desconhecidas = [f for f in ferramentas if f not in _ferramentas_conhecidas()]
    if desconhecidas:
        # O nome inventado costuma estar perto do real (`rb_agenda` e `agenda`):
        # dizer qual existe poupa a volta em que o modelo iria procurar.
        conhecidas = sorted(_ferramentas_conhecidas())
        perto = sorted({p for f in desconhecidas for p in difflib.get_close_matches(f, conhecidas, 3, 0.6)})
        dica = f"; as que existem e mais se parecem: {', '.join(perto)}" if perto else ""
        raise ManifestoInvalido(f"ferramentas que não existem: {', '.join(desconhecidas)}{dica}")
    vetadas = [f for f in ferramentas if f in _proibidas()]
    if vetadas:
        raise ManifestoInvalido(f"ferramentas que um residente não recebe: {', '.join(vetadas)}")

    canais = sorted({str(c).strip().lower() for c in (dados.get("canais") or []) if str(c).strip()})
    fora = [c for c in canais if c not in CANAIS]
    if fora:
        raise ManifestoInvalido(f"canais que não existem: {', '.join(fora)}")

    orcamento = dict(ORCAMENTO_PADRAO)
    for chave, valor in (dados.get("orcamento") or {}).items():
        if chave not in ORCAMENTO_PADRAO:
            raise ManifestoInvalido(f"orçamento só aceita {', '.join(ORCAMENTO_PADRAO)}")
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            raise ManifestoInvalido(f"orçamento '{chave}' precisa ser número") from None
        if numero <= 0:
            raise ManifestoInvalido(f"orçamento '{chave}' precisa ser maior que zero")
        orcamento[chave] = numero

    autonomia = dict(AUTONOMIA_PADRAO)
    for chave, valor in (dados.get("autonomia") or {}).items():
        if chave not in AUTONOMIA_PADRAO:
            raise ManifestoInvalido(f"autonomia só aceita {', '.join(AUTONOMIA_PADRAO)}")
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            raise ManifestoInvalido(f"autonomia '{chave}' precisa ser número inteiro") from None
        if not 0 <= numero <= TETO_DA_AUTONOMIA:
            raise ManifestoInvalido(f"autonomia '{chave}' vai de 0 a {TETO_DA_AUTONOMIA}")
        autonomia[chave] = numero

    rede = dados.get("rede", "nenhuma")
    if rede not in ("nenhuma", "internet"):
        raise ManifestoInvalido("rede: escolha nenhuma ou internet")

    estado = str(dados.get("estado") or DORMINDO)
    if estado not in ESTADOS:
        raise ManifestoInvalido(f"estado '{estado}' não existe")

    from . import aparencia as _aparencia
    from . import cerebro as _cerebro
    from . import skills as _skills

    try:
        cerebro = _cerebro.validar(dados.get("cerebro"))
        # Do disco vem `aparencia` pronta; da criação, `familia` e `acessorios`
        # soltos. Nos dois casos a plumagem é recalculada: ela nunca vem de fora.
        guardada = dados.get("aparencia") if isinstance(dados.get("aparencia"), dict) else {}
        aparencia = _aparencia.montar(
            nome,
            guardada.get("familia") or dados.get("familia") or "",
            guardada.get("acessorios") if guardada else dados.get("acessorios"),
        )
    except (_aparencia.AparenciaInvalida, _cerebro.CerebroInvalido) as exc:
        raise ManifestoInvalido(str(exc)) from None

    return Manifesto(
        nome=nome,
        papel=_texto(dados, "papel", 120, obrigatorio=True),
        objetivo=_texto(dados, "objetivo", 600, obrigatorio=True),
        ferramentas=ferramentas,
        skills=_skills.validar(dados.get("skills")),
        personalidade=_texto(dados, "personalidade", 400),
        instrucoes=_texto(dados, "instrucoes", 4000),
        cerebro=cerebro,
        aparencia=aparencia,
        canais=canais,
        orcamento=orcamento,
        autonomia=autonomia,
        rede=rede,
        estado=estado,
        criado_por=_texto(dados, "criado_por", 120),
        criado_em=float(dados.get("criado_em") or 0.0),
        atualizado_em=float(dados.get("atualizado_em") or 0.0),
    )


_CASAS_PRONTAS: set = set()


def casa() -> Path:
    raiz = Path(os.environ.get("SENTURY_HOME") or (Path.home() / ".sentury"))
    pasta = raiz / "residentes"
    # Chamada a cada leitura de tarefa: a pasta é criada só na primeira vez.
    if str(pasta) not in _CASAS_PRONTAS:
        pasta.mkdir(parents=True, exist_ok=True)
        _CASAS_PRONTAS.add(str(pasta))
    return pasta
