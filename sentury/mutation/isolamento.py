"""A mutação trabalha numa cópia, nunca no código vivo.

`git worktree` dá o que se precisa aqui: baseline e candidata existindo ao
mesmo tempo, em pastas separadas, compartilhando o mesmo histórico. O Crucible
compara as duas sem que nenhuma precise sair do lugar.

Reverter é a mesma mecânica pelo avesso: se nada foi promovido, jogar a cópia
fora basta. O código vivo nunca foi tocado, então não há o que desfazer nele.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PREFIXO_BRANCH = "mutation"
_TIMEOUT = 120.0


def raiz_do_repo(caminho: Optional[str] = None) -> Optional[Path]:
    saida = _git(["rev-parse", "--show-toplevel"], cwd=caminho or os.getcwd())
    return Path(saida["saida"].strip()) if saida["ok"] and saida["saida"].strip() else None


def pasta_das_copias() -> Path:
    """Onde as cópias vivem. Fora do repositório de propósito: uma worktree
    dentro dele apareceria no próprio `git status` e no deploy."""
    escolhido = os.environ.get("SENTURY_MUTATION_WORKTREES")
    if escolhido:
        return Path(escolhido).expanduser()
    home = os.environ.get("SENTURY_HOME") or str(Path.home() / ".sentury")
    return Path(home) / "mutations"


def _git(args: List[str], cwd: Optional[str] = None) -> Dict[str, Any]:
    """Chama o git sem shell. Nunca levanta: devolve o erro."""
    binario = shutil.which("git")
    if not binario:
        return {"ok": False, "saida": "", "erro": "git nao encontrado no sistema"}
    try:
        processo = subprocess.run(
            [binario, *args], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_TIMEOUT, check=False,
            shell=False, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "saida": "", "erro": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": processo.returncode == 0,
        "saida": processo.stdout or "",
        "erro": (processo.stderr or "").strip(),
    }


def commit_atual(cwd: Optional[str] = None) -> str:
    """A baseline. Sem ela a evidência da mutação não vale: não se sabe do que
    ela partiu nem contra o que foi comparada."""
    saida = _git(["rev-parse", "HEAD"], cwd=cwd)
    return saida["saida"].strip() if saida["ok"] else ""


def arvore_limpa(cwd: Optional[str] = None) -> bool:
    """O registro de mutações mora na árvore e `propor` o grava antes de abrir a
    cópia. Ele não é trabalho em andamento: contá-lo recusaria toda proposta."""
    from . import registro

    filtro: List[str] = []
    raiz = raiz_do_repo(cwd)
    pasta = registro.pasta().resolve()
    if raiz is not None and pasta.is_relative_to(raiz.resolve()):
        filtro = ["--", ".", f":(exclude){pasta.relative_to(raiz.resolve()).as_posix()}"]
    saida = _git(["status", "--porcelain", *filtro], cwd=str(raiz) if filtro else cwd)
    return saida["ok"] and not saida["saida"].strip()


def nome_do_branch(mutacao_id: str, alvo: str = "") -> str:
    apelido = "".join(c if c.isalnum() else "-" for c in (alvo or "").lower()).strip("-")
    apelido = "-".join(p for p in apelido.split("-") if p)[:40]
    return f"{PREFIXO_BRANCH}/{mutacao_id}" + (f"-{apelido}" if apelido else "")


def criar(mutacao_id: str, *, alvo: str = "", repo: Optional[str] = None) -> Dict[str, Any]:
    """Abre a cópia isolada da mutação.

    Exige árvore limpa: uma worktree criada por cima de trabalho não commitado
    nasceria de uma baseline que não existe em commit nenhum, e a comparação
    depois não significaria nada.
    """
    origem = str(repo or os.getcwd())
    raiz = raiz_do_repo(origem)
    if raiz is None:
        return {"ok": False, "erro": "fora de um repositorio git"}
    if not arvore_limpa(str(raiz)):
        return {"ok": False, "erro": "arvore suja: comite ou guarde o que esta em andamento antes"}

    baseline = commit_atual(str(raiz))
    if not baseline:
        return {"ok": False, "erro": "nao consegui ler o commit atual"}

    destino = pasta_das_copias() / mutacao_id
    if destino.exists():
        return {"ok": False, "erro": f"ja existe uma copia em {destino}"}
    destino.parent.mkdir(parents=True, exist_ok=True)

    branch = nome_do_branch(mutacao_id, alvo)
    feito = _git(["worktree", "add", "-b", branch, str(destino), baseline], cwd=str(raiz))
    if not feito["ok"]:
        return {"ok": False, "erro": feito["erro"] or "falha ao criar a copia"}

    logger.info("Mutacao %s isolada em %s (branch %s)", mutacao_id, destino, branch)
    return {"ok": True, "caminho": str(destino), "branch": branch, "baseline": baseline}


def descartar(mutacao_id: str, *, repo: Optional[str] = None, apagar_branch: bool = False) -> Dict[str, Any]:
    """Joga a cópia fora. É o rollback de tudo que não foi promovido.

    O branch **fica** por padrão: uma mutação rejeitada é evidência, e apagar o
    que ela tentou junto com a pasta destrói o que se aprendeu com ela.
    """
    raiz = raiz_do_repo(str(repo or os.getcwd()))
    if raiz is None:
        return {"ok": False, "erro": "fora de um repositorio git"}

    destino = pasta_das_copias() / mutacao_id
    if not destino.exists():
        return {"ok": True, "ja_removida": True, "caminho": str(destino)}

    feito = _git(["worktree", "remove", "--force", str(destino)], cwd=str(raiz))
    if not feito["ok"]:
        return {"ok": False, "erro": feito["erro"] or "falha ao remover a copia"}

    resultado = {"ok": True, "caminho": str(destino), "branch_mantido": not apagar_branch}
    if apagar_branch:
        _git(["branch", "-D", nome_do_branch(mutacao_id)], cwd=str(raiz))
    return resultado


# O patch vai para a tela de aprovação; acima disto, a tela mostra o resumo.
TETO_DO_PATCH = 200_000


def diferenca(mutacao_id: str, *, repo: Optional[str] = None, base: str = "HEAD",
              com_patch: bool = False) -> Dict[str, Any]:
    """O que a mutação mudou em relação à baseline. É o que vai para aprovação.

    `base` é o commit de onde a cópia partiu: comparar com o HEAD da cópia
    esconderia tudo o que já foi commitado lá dentro."""
    destino = pasta_das_copias() / mutacao_id
    if not destino.exists():
        return {"ok": False, "erro": f"nao existe copia para {mutacao_id}"}

    nomes = _git(["diff", "--name-only", base], cwd=str(destino))
    estatistica = _git(["diff", "--stat", base], cwd=str(destino))
    naorastreados = _git(["ls-files", "--others", "--exclude-standard"], cwd=str(destino))
    if not nomes["ok"]:
        return {"ok": False, "erro": nomes["erro"] or "falha ao ler o diff"}

    alterados = [l for l in nomes["saida"].splitlines() if l.strip()]
    novos = [l for l in naorastreados["saida"].splitlines() if l.strip()]
    resultado = {
        "ok": True,
        "caminho": str(destino),
        "alterados": alterados,
        "novos": novos,
        "resumo": estatistica["saida"].strip(),
        "mudou": bool(alterados or novos),
    }
    if com_patch:
        patch = _git(["diff", base], cwd=str(destino))["saida"]
        resultado["patch"] = patch[:TETO_DO_PATCH]
        resultado["patch_cortado"] = len(patch) > TETO_DO_PATCH
    return resultado


def listar() -> List[Dict[str, str]]:
    base = pasta_das_copias()
    if not base.is_dir():
        return []
    return [
        {"mutacao": p.name, "caminho": str(p)}
        for p in sorted(base.iterdir()) if p.is_dir()
    ]


__all__ = [
    "arvore_limpa", "commit_atual", "criar", "descartar", "diferenca",
    "listar", "nome_do_branch", "pasta_das_copias", "raiz_do_repo",
]
