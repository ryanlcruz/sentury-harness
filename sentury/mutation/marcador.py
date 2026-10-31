"""Marcador que liga um trecho de código à mutação que o criou.

`git blame` diz quem mudou e quando, mas não sobrevive a um refactor e não diz
por quê. O marcador diz: e é procurável.

Uma linha por trecho, e só onde a intenção não é óbvia. A explicação inteira
mora no registro; aqui fica o ponteiro.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

PREFIXO = "mutinfo"
_MARCA = re.compile(rf"{PREFIXO}\s+(AM-\d{{4}})\s*[-—:]\s*(.*)", re.IGNORECASE)

# Comentário de linha por extensão. Fora daqui, não marca: um marcador com a
# sintaxe errada vira erro de compilação no arquivo que ele deveria explicar.
_COMENTARIO = {
    ".py": "#", ".sh": "#", ".yaml": "#", ".yml": "#", ".toml": "#",
    ".ts": "//", ".tsx": "//", ".js": "//", ".jsx": "//", ".go": "//",
    ".rs": "//", ".java": "//", ".c": "//", ".cpp": "//",
}


def montar(mutacao_id: str, resumo: str, extensao: str = ".py") -> str:
    """A linha a inserir. `resumo` é uma frase curta, no imperativo do que faz."""
    if not re.fullmatch(r"AM-\d{4}", str(mutacao_id or "")):
        raise ValueError(f"id de mutacao invalido: {mutacao_id}")
    texto = " ".join(str(resumo or "").split())[:90]
    if not texto:
        raise ValueError("marcador sem resumo nao explica nada")
    simbolo = _COMENTARIO.get(str(extensao).lower())
    if not simbolo:
        raise ValueError(f"nao sei comentar arquivos '{extensao}'")
    return f"{simbolo} {PREFIXO} {mutacao_id} - {texto}"


def encontrar(raiz: str = ".", mutacao_id: str = "") -> List[Dict[str, Any]]:
    """Onde cada marcador está. É o que responde 'o que veio da AM-0014?'."""
    base = Path(raiz).resolve()
    achados: List[Dict[str, Any]] = []
    for extensao in _COMENTARIO:
        for arquivo in base.rglob(f"*{extensao}"):
            if any(p in arquivo.parts for p in ("__pycache__", "node_modules", ".git", ".venv")):
                continue
            try:
                linhas = arquivo.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for numero, linha in enumerate(linhas, start=1):
                casou = _MARCA.search(linha)
                if not casou:
                    continue
                if mutacao_id and casou.group(1).upper() != mutacao_id.upper():
                    continue
                achados.append({
                    "mutacao": casou.group(1).upper(),
                    "arquivo": str(arquivo.relative_to(base)),
                    "linha": numero,
                    "resumo": casou.group(2).strip(),
                })
    return sorted(achados, key=lambda a: (a["mutacao"], a["arquivo"], a["linha"]))


def orfaos(raiz: str = ".") -> List[Dict[str, Any]]:
    """Marcadores que apontam para mutação que não existe no registro.

    Acontece quando alguém copia o código de outro lugar ou apaga o registro:
    o ponteiro fica, e passa a mentir sobre a origem do trecho.
    """
    from .registro import carregar

    return [m for m in encontrar(raiz) if carregar(m["mutacao"]) is None]


def documentar(mutacao_id: str, raiz: str = ".") -> str:
    """A seção que entra na documentação da mutação, com o que ela deixou onde."""
    from .registro import carregar

    mutacao = carregar(mutacao_id)
    if not mutacao:
        return f"Mutação {mutacao_id} não está no registro."

    linhas = [
        f"## {mutacao.id} — {mutacao.alvo}",
        "",
        f"**Estado:** {mutacao.estado}",
        f"**Hipótese:** {mutacao.hipotese}",
    ]
    if mutacao.observacao:
        linhas.append(f"**Motivou:** {mutacao.observacao}")
    if mutacao.baseline_commit:
        linhas.append(f"**Partiu de:** `{mutacao.baseline_commit[:12]}`")
    if mutacao.motivo:
        linhas.append(f"**Motivo do desfecho:** {mutacao.motivo}")
    if mutacao.revisit_if:
        linhas.append("**Revisitar se:** " + "; ".join(mutacao.revisit_if))

    marcas = encontrar(raiz, mutacao_id)
    linhas += ["", "### Onde ela mexeu", ""]
    if marcas:
        linhas += [f"- `{m['arquivo']}:{m['linha']}` — {m['resumo']}" for m in marcas]
    else:
        linhas.append("_Nenhum marcador no código._")
    return "\n".join(linhas)


__all__ = ["PREFIXO", "documentar", "encontrar", "montar", "orfaos"]
