"""O histórico de cada mutação: o que foi tentado, o que sobreviveu, o que morreu.

Sem este registro não há linhagem, não há como saber que uma ideia já foi
testada e reprovada, e não há a que voltar. É por isso que ele vem antes do
resto do Mutation, e não depois.

Três decisões que valem explicar:

**O registro é versionado com o código.** Ele fica no repositório, não em
`~/.sentury`. O aprendizado do roteador é da máquina: foi medido com aquelas
chaves, naquele plano. Isto é outra coisa: é memória do *projeto*, precisa ser
revisável junto do diff, e serve para a próxima pessoa não repetir a mesma
tentativa.

**Rejeitada não é apagada.** Uma mutação reprovada vira evidência, com o
motivo e as condições em que valeria revisitar. Apagar o que não deu certo é
como perder o resultado negativo de um experimento: a informação existia e foi
jogada fora.

**O estado só anda para frente, pelo caminho declarado.** Não dá para promover
o que não foi avaliado, nem reprovar o que já foi promovido: para isso existe
reverter, que é outra coisa e fica registrada como tal.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# O ciclo de vida. Cada seta é uma decisão que alguém tomou e que fica gravada.
ESTADOS: Dict[str, tuple] = {
    "proposta": ("candidata", "descartada"),
    # Construída e isolada num worktree, ainda sem evidência.
    "candidata": ("em_avaliacao", "descartada"),
    # No Crucible: rodando evals contra a baseline.
    "em_avaliacao": ("aprovada", "rejeitada"),
    # Passou nos gates, esperando decisão humana.
    "aprovada": ("promovida", "rejeitada"),
    # Vale no runtime.
    "promovida": ("revertida",),
    # Terminais, mas nada é apagado: rejeitada e revertida são evidência.
    "rejeitada": (),
    "revertida": (),
    "descartada": (),
}

_ID = re.compile(r"^AM-\d{4}$")


@dataclass
class Mutacao:
    """Uma tentativa de alterar o core, com tudo que se sabe sobre ela."""

    id: str
    alvo: str                       # o que ela muda: "harness.reviewer", "context.poda"
    hipotese: str                   # o que se espera melhorar, e por quê
    estado: str = "proposta"
    observacao: str = ""            # o que motivou: o sintoma observado
    baseline_commit: str = ""       # de onde partiu; sem isso a evidência não vale
    branch: str = ""
    commits: List[str] = field(default_factory=list)
    parent: str = ""                # linhagem: mutação de que esta derivou
    eval_dataset: str = ""          # contra qual bateria foi medida
    fitness: Dict[str, Any] = field(default_factory=dict)
    motivo: str = ""                # por que foi rejeitada/revertida
    revisit_if: List[str] = field(default_factory=list)
    custo: Dict[str, Any] = field(default_factory=dict)   # tokens, tempo, tentativas
    eventos: List[Dict[str, Any]] = field(default_factory=list)
    criada_em: float = 0.0
    atualizada_em: float = 0.0

    def para_dict(self) -> Dict[str, Any]:
        return asdict(self)


def pasta() -> Path:
    """Onde os registros moram. `SENTURY_MUTATION_DIR` aponta para outro lugar
é o que permite testar sem sujar o repositório."""
    escolhido = os.environ.get("SENTURY_MUTATION_DIR")
    if escolhido:
        return Path(escolhido).expanduser()
    return Path(__file__).resolve().parent / "registro"


def _caminho(mutacao_id: str) -> Path:
    return pasta() / f"{mutacao_id}.json"


def _agora() -> float:
    return time.time()


def proximo_id() -> str:
    """Sequencial, legível e ordenável. `AM-0014` é citável numa conversa; um
    UUID não é."""
    maior = 0
    if pasta().is_dir():
        for arquivo in pasta().glob("AM-*.json"):
            try:
                maior = max(maior, int(arquivo.stem.split("-")[1]))
            except (IndexError, ValueError):
                continue
    return f"AM-{maior + 1:04d}"


def _gravar(mutacao: Mutacao) -> Mutacao:
    mutacao.atualizada_em = _agora()
    destino = _caminho(mutacao.id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(mutacao.para_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(destino)
    return mutacao


def abrir(
    *,
    alvo: str,
    hipotese: str,
    observacao: str = "",
    baseline_commit: str = "",
    parent: str = "",
    mutacao_id: str = "",
) -> Mutacao:
    """Abre uma mutação. Ela nasce `proposta`: nada foi construído ainda.

    `alvo` e `hipotese` são obrigatórios de propósito: uma mutação sem alvo não
    tem o que comparar, e sem hipótese não há como dizer se deu certo. Foi
    exatamente por falta de critério explícito que a aferição vira "parece bom".
    """
    alvo = (alvo or "").strip()
    hipotese = (hipotese or "").strip()
    if not alvo:
        raise ValueError("mutacao precisa de um alvo (o que ela muda)")
    if not hipotese:
        raise ValueError("mutacao precisa de uma hipotese (o que deve melhorar, e por que)")

    escolhido = (mutacao_id or "").strip() or proximo_id()
    if not _ID.match(escolhido):
        raise ValueError(f"id de mutacao invalido: {escolhido} (esperado AM-0001)")
    if _caminho(escolhido).exists():
        raise ValueError(f"mutacao {escolhido} ja existe")

    if parent and not carregar(parent):
        raise ValueError(f"mutacao pai desconhecida: {parent}")

    mutacao = Mutacao(
        id=escolhido, alvo=alvo, hipotese=hipotese, observacao=observacao.strip(),
        baseline_commit=baseline_commit.strip(), parent=parent.strip(),
        criada_em=_agora(),
    )
    mutacao.eventos.append({"em": _agora(), "tipo": "aberta", "detalhe": alvo})
    logger.info("Mutacao %s aberta sobre %s", escolhido, alvo)
    return _gravar(mutacao)


def carregar(mutacao_id: str) -> Optional[Mutacao]:
    caminho = _caminho(str(mutacao_id or "").strip())
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Registro de mutacao ilegivel (%s): %s", caminho, exc)
        return None
    conhecidos = {campo for campo in Mutacao.__dataclass_fields__}
    return Mutacao(**{k: v for k, v in dados.items() if k in conhecidos})


def listar(estado: str = "") -> List[Mutacao]:
    """Todas as mutações, da mais nova para a mais velha."""
    if not pasta().is_dir():
        return []
    achadas = [m for m in (carregar(a.stem) for a in pasta().glob("AM-*.json")) if m]
    if estado:
        achadas = [m for m in achadas if m.estado == estado]
    return sorted(achadas, key=lambda m: m.id, reverse=True)


def registrar_evento(mutacao_id: str, tipo: str, detalhe: str = "", **extra: Any) -> Mutacao:
    """Anota algo que aconteceu sem mudar o estado: um commit, um custo, uma
    rodada de avaliação. É o que transforma o registro em trilha."""
    mutacao = carregar(mutacao_id)
    if not mutacao:
        raise ValueError(f"mutacao desconhecida: {mutacao_id}")
    mutacao.eventos.append({"em": _agora(), "tipo": tipo, "detalhe": detalhe, **extra})
    return _gravar(mutacao)


def transicionar(
    mutacao_id: str,
    novo_estado: str,
    *,
    motivo: str = "",
    fitness: Optional[Dict[str, Any]] = None,
    revisit_if: Optional[List[str]] = None,
) -> Mutacao:
    """Move a mutação pelo ciclo, e só pelos caminhos declarados.

    Terminar em `rejeitada` ou `revertida` **exige** motivo: sem ele o registro
    guarda que algo não deu certo mas não o que aprender com isso, e a próxima
    tentativa repete o mesmo caminho às cegas.
    """
    mutacao = carregar(mutacao_id)
    if not mutacao:
        raise ValueError(f"mutacao desconhecida: {mutacao_id}")

    destino = str(novo_estado or "").strip()
    if destino not in ESTADOS:
        raise ValueError(f"estado desconhecido: {destino}")
    permitidos = ESTADOS.get(mutacao.estado, ())
    if destino not in permitidos:
        raise ValueError(
            f"{mutacao.id} nao pode ir de '{mutacao.estado}' para '{destino}'"
            f" (de la so da para: {', '.join(permitidos) or 'lugar nenhum'})"
        )
    if destino in ("rejeitada", "revertida") and not (motivo or "").strip():
        raise ValueError(f"para marcar como '{destino}' e preciso dizer o motivo")
    if destino == "aprovada" and not (fitness or mutacao.fitness):
        raise ValueError("nao da para aprovar sem evidencia: informe o fitness medido")

    anterior = mutacao.estado
    mutacao.estado = destino
    if motivo:
        mutacao.motivo = motivo.strip()
    if fitness:
        mutacao.fitness = dict(fitness)
    if revisit_if:
        mutacao.revisit_if = [str(item) for item in revisit_if]
    mutacao.eventos.append({
        "em": _agora(), "tipo": "estado", "detalhe": f"{anterior} -> {destino}",
        "motivo": motivo or "",
    })
    logger.info("Mutacao %s: %s -> %s", mutacao.id, anterior, destino)
    return _gravar(mutacao)


def historico(mutacao_id: str) -> List[Dict[str, Any]]:
    mutacao = carregar(mutacao_id)
    return list(mutacao.eventos) if mutacao else []


def linhagem(mutacao_id: str) -> List[str]:
    """A cadeia até a raiz. Uma mutação que derivou de outra herda o contexto
    de por que aquela existiu."""
    cadeia: List[str] = []
    atual = carregar(mutacao_id)
    visitados = set()
    while atual and atual.id not in visitados:
        visitados.add(atual.id)
        cadeia.append(atual.id)
        atual = carregar(atual.parent) if atual.parent else None
    return cadeia


def ja_tentado(alvo: str) -> List[Mutacao]:
    """O que já foi tentado neste alvo e não deu certo.

    É a razão de guardar o que morreu: antes de propor, dá para ver se a mesma
    ideia já foi reprovada e sob quais condições valeria tentar de novo.
    """
    alvo = (alvo or "").strip()
    return [
        m for m in listar()
        if m.alvo == alvo and m.estado in ("rejeitada", "revertida", "descartada")
    ]


__all__ = [
    "ESTADOS", "Mutacao", "abrir", "carregar", "historico", "ja_tentado",
    "linhagem", "listar", "pasta", "proximo_id", "registrar_evento", "transicionar",
]
