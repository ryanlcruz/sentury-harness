"""O ciclo de vida completo: abrir, isolar, avaliar, decidir, reverter.

O registro sabe o que aconteceu; o isolamento sabe onde. Aqui os dois andam
juntos, para não existir mutação registrada sem cópia nem cópia órfã sem
registro: cada uma sozinha é um jeito de perder o rastro.

Nada aqui promove nada sozinho. Promover é decisão humana, e a função existe
para registrar a decisão, não para tomá-la.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import isolamento, registro

logger = logging.getLogger(__name__)


def propor(
    *,
    alvo: str,
    hipotese: str,
    observacao: str = "",
    parent: str = "",
    repo: Optional[str] = None,
) -> Dict[str, Any]:
    """Abre a mutação e a cópia isolada na mesma operação.

    Se o isolamento falhar, a mutação é descartada em vez de ficar registrada
    como `proposta` sem lugar para trabalhar: um registro que aponta para uma
    cópia inexistente é pior que nenhum registro.
    """
    baseline = isolamento.commit_atual(repo)
    mutacao = registro.abrir(
        alvo=alvo, hipotese=hipotese, observacao=observacao,
        baseline_commit=baseline, parent=parent,
    )

    copia = isolamento.criar(mutacao.id, alvo=alvo, repo=repo)
    if not copia["ok"]:
        registro.transicionar(
            mutacao.id, "descartada",
            motivo=f"nao consegui isolar: {copia.get('erro')}",
        )
        return {"ok": False, "id": mutacao.id, "erro": copia.get("erro")}

    mutacao.branch = copia["branch"]
    mutacao.baseline_commit = copia["baseline"]
    registro.registrar_evento(
        mutacao.id, "isolada", copia["caminho"], branch=copia["branch"],
    )
    atualizada = registro.carregar(mutacao.id)
    if atualizada:
        atualizada.branch = copia["branch"]
        atualizada.baseline_commit = copia["baseline"]
        registro._gravar(atualizada)  # noqa: SLF001 (mesma família, sem API pública ainda)

    return {
        "ok": True, "id": mutacao.id, "caminho": copia["caminho"],
        "branch": copia["branch"], "baseline": copia["baseline"],
    }


def construida(mutacao_id: str) -> Dict[str, Any]:
    """Marca que há algo para avaliar. Exige diff: uma mutação que não mudou
    nada não é candidata: é uma pasta vazia esperando alguém perceber."""
    mutacao = registro.carregar(mutacao_id)
    diff = isolamento.diferenca(mutacao_id, base=(mutacao.baseline_commit if mutacao else "") or "HEAD")
    if not diff.get("ok"):
        return {"ok": False, "erro": diff.get("erro")}
    if not diff.get("mudou"):
        return {"ok": False, "erro": "a copia nao mudou nada; nao ha o que avaliar"}

    registro.registrar_evento(
        mutacao_id, "diff", diff["resumo"][:400],
        alterados=diff["alterados"], novos=diff["novos"],
    )
    registro.transicionar(mutacao_id, "candidata")
    return {"ok": True, "id": mutacao_id, "alterados": diff["alterados"], "novos": diff["novos"]}


def avaliar(mutacao_id: str) -> Dict[str, Any]:
    registro.transicionar(mutacao_id, "em_avaliacao")
    return {"ok": True, "id": mutacao_id}


def concluir_avaliacao(
    mutacao_id: str,
    *,
    passou: bool,
    fitness: Dict[str, Any],
    motivo: str = "",
    revisit_if: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Fecha a avaliação com a evidência medida.

    Reprovar **não** descarta a cópia: o branch e o diff continuam sendo o que
    se aprendeu, e jogar fora na hora da má notícia é perder exatamente o
    resultado que custou mais caro para obter.
    """
    if passou:
        registro.transicionar(mutacao_id, "aprovada", fitness=fitness)
        return {"ok": True, "id": mutacao_id, "estado": "aprovada"}

    registro.transicionar(
        mutacao_id, "rejeitada",
        motivo=motivo or "nao passou nos gates",
        fitness=fitness, revisit_if=revisit_if,
    )
    return {"ok": True, "id": mutacao_id, "estado": "rejeitada"}


def promover(mutacao_id: str, *, decidido_por: str) -> Dict[str, Any]:
    """Registra que um humano aprovou a entrada no runtime.

    `decidido_por` é obrigatório: promoção sem responsável registrado é
    exatamente o que a mediação humana existe para impedir. Esta função **não**
    faz o merge: quem move código é quem decidiu, com o diff na frente.
    """
    quem = (decidido_por or "").strip()
    if not quem:
        raise ValueError("promocao precisa do responsavel pela decisao")
    registro.registrar_evento(mutacao_id, "aprovacao_humana", quem)
    registro.transicionar(mutacao_id, "promovida")
    return {"ok": True, "id": mutacao_id, "estado": "promovida", "por": quem}


def reverter(mutacao_id: str, *, motivo: str, repo: Optional[str] = None) -> Dict[str, Any]:
    """Tira do ar uma mutação promovida e joga a cópia fora.

    O branch fica: reverter é dizer que não serviu AGORA, e o que ela tentou
    continua sendo evidência para quando as condições mudarem.
    """
    if not (motivo or "").strip():
        raise ValueError("reverter precisa do motivo")
    registro.transicionar(mutacao_id, "revertida", motivo=motivo)
    descarte = isolamento.descartar(mutacao_id, repo=repo)
    registro.registrar_evento(mutacao_id, "copia_removida", str(descarte.get("caminho", "")))
    return {"ok": True, "id": mutacao_id, "estado": "revertida", "copia_removida": descarte.get("ok")}


def limpar_copia(mutacao_id: str, *, repo: Optional[str] = None) -> Dict[str, Any]:
    """Remove a cópia de uma mutação que já terminou, mantendo o registro.

    Só faz sentido em estado terminal: apagar a cópia de algo em avaliação
    interromperia o que está sendo medido.
    """
    mutacao = registro.carregar(mutacao_id)
    if not mutacao:
        return {"ok": False, "erro": f"mutacao desconhecida: {mutacao_id}"}
    if mutacao.estado not in ("rejeitada", "revertida", "descartada", "promovida"):
        return {"ok": False, "erro": f"'{mutacao.estado}' ainda esta em andamento"}
    descarte = isolamento.descartar(mutacao_id, repo=repo)
    if descarte.get("ok"):
        registro.registrar_evento(mutacao_id, "copia_removida", str(descarte.get("caminho", "")))
    return descarte


def estado_geral() -> Dict[str, Any]:
    """O que alimenta o painel: cada mutação e se a cópia dela ainda existe."""
    copias = {c["mutacao"]: c["caminho"] for c in isolamento.listar()}
    mutacoes = []
    for m in registro.listar():
        mutacoes.append({
            "id": m.id, "alvo": m.alvo, "estado": m.estado, "hipotese": m.hipotese,
            "branch": m.branch, "baseline": m.baseline_commit,
            "fitness": m.fitness, "motivo": m.motivo,
            "copia": copias.get(m.id, ""),
            "eventos": len(m.eventos),
        })
    orfas = sorted(set(copias) - {m["id"] for m in mutacoes})
    return {"mutacoes": mutacoes, "copias_orfas": orfas}


__all__ = [
    "avaliar", "concluir_avaliacao", "construida", "estado_geral",
    "limpar_copia", "promover", "propor", "reverter",
]
