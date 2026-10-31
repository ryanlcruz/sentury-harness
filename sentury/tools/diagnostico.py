"""Detecta erros de código antes de rodar testes completos.

Usa compilação e análise local, além de verificadores já instalados no projeto.
Não exige um servidor de linguagem nem instala dependências.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_ACHADOS = 60

# Nome que o Python resolve sozinho e que não é import nem atribuição local.
#
# `dir(__builtins__)` não serve: dentro de um módulo importado, `__builtins__` é
# o dicionário do módulo e `dir()` dele devolve os métodos do dict: então
# `ValueError`, `str` e `tuple` ficavam de fora e viravam falso positivo. O
# módulo `builtins` é a lista de verdade.
import builtins

_EMBUTIDOS = frozenset(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__builtins__", "__loader__", "self", "cls",
}


def _achado(caminho: Path, linha: int, gravidade: str, mensagem: str, origem: str) -> Dict[str, Any]:
    return {
        "arquivo": str(caminho),
        "linha": int(linha or 0),
        "gravidade": gravidade,   # erro | aviso
        "mensagem": str(mensagem)[:300],
        "origem": origem,
    }


def _sintaxe(caminho: Path, fonte: str) -> List[Dict[str, Any]]:
    """Erro de sintaxe. É o único que impede o arquivo de rodar, então vem
    primeiro e sozinho: com a árvore quebrada, nada mais dá para analisar."""
    try:
        compile(fonte, str(caminho), "exec")
        return []
    except SyntaxError as exc:
        return [_achado(caminho, exc.lineno or 0, "erro", f"{exc.msg}", "sintaxe")]
    except ValueError as exc:
        return [_achado(caminho, 0, "erro", str(exc), "sintaxe")]


def _nomes_indefinidos(caminho: Path, arvore: ast.AST) -> List[Dict[str, Any]]:
    """Nome usado e nunca ligado no módulo.

    Análise de escopo de verdade exige resolver import, closure e classe; isto
    é deliberadamente raso e só reporta o que é **claramente** solto: nome
    usado que não aparece em nenhum import, atribuição, def, class, parâmetro
    ou comprehension do arquivo. Falso positivo aqui custaria mais que o
    achado, então o critério é conservador.
    """
    ligados = set(_EMBUTIDOS)
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Import, ast.ImportFrom)):
            for alias in no.names:
                ligados.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ligados.add(no.name)
            for arg in getattr(getattr(no, "args", None), "args", []) or []:
                ligados.add(arg.arg)
            for campo in ("posonlyargs", "kwonlyargs"):
                for arg in getattr(getattr(no, "args", None), campo, []) or []:
                    ligados.add(arg.arg)
            for campo in ("vararg", "kwarg"):
                arg = getattr(getattr(no, "args", None), campo, None)
                if arg is not None:
                    ligados.add(arg.arg)
        elif isinstance(no, ast.Name) and isinstance(no.ctx, (ast.Store, ast.Del)):
            ligados.add(no.id)
        elif isinstance(no, ast.comprehension) and isinstance(no.target, ast.Name):
            ligados.add(no.target.id)
        elif isinstance(no, ast.ExceptHandler) and no.name:
            ligados.add(no.name)
        elif isinstance(no, ast.Global):
            ligados.update(no.names)
        elif isinstance(no, ast.arg):
            ligados.add(no.arg)

    vistos, saida = set(), []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Load):
            if no.id not in ligados and no.id not in vistos:
                vistos.add(no.id)
                saida.append(_achado(
                    caminho, no.lineno, "aviso",
                    f"'{no.id}' é usado e não aparece em nenhum import ou atribuição do arquivo",
                    "nome",
                ))
    return saida


def _imports_que_nao_existem(caminho: Path, arvore: ast.AST, raiz: Path) -> List[Dict[str, Any]]:
    """Import relativo apontando para módulo que não está no disco.

    Só relativo: o absoluto depende do ambiente instalado, e checá-lo daria
    falso positivo a cada pacote que existe no venv e não no repositório.
    """
    saida = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.ImportFrom) or not no.level:
            continue
        base = caminho.parent
        for _ in range(no.level - 1):
            base = base.parent
        alvo = base / Path(*(no.module or "").split(".")) if no.module else base
        if not (alvo.with_suffix(".py").is_file() or (alvo / "__init__.py").is_file()):
            saida.append(_achado(
                caminho, no.lineno, "erro",
                f"import relativo '{'.' * no.level}{no.module or ''}' não existe no disco",
                "import",
            ))
    return saida


def do_arquivo(caminho: str, raiz: str = ".") -> Dict[str, Any]:
    """Diagnóstico de um arquivo. Sintaxe primeiro; o resto só se ela passar."""
    base = Path(raiz).resolve()
    alvo = (base / caminho).resolve() if not Path(caminho).is_absolute() else Path(caminho)
    if not alvo.is_file():
        return {"ok": False, "erro": f"não é um arquivo: {alvo}"}
    if alvo.suffix != ".py":
        return {
            "ok": True, "arquivo": str(alvo), "achados": [],
            "nota": "diagnóstico local cobre Python; para outras linguagens use a ferramenta da linguagem pelo terminal",
        }

    try:
        fonte = alvo.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "erro": str(exc)}

    achados = _sintaxe(alvo, fonte)
    if achados:
        # Árvore quebrada: qualquer outra análise seria chute.
        return {"ok": True, "arquivo": str(alvo), "achados": achados, "erros": 1, "avisos": 0}

    arvore = ast.parse(fonte, str(alvo))
    achados += _imports_que_nao_existem(alvo, arvore, base)
    achados += _nomes_indefinidos(alvo, arvore)
    achados = achados[:MAX_ACHADOS]
    return {
        "ok": True,
        "arquivo": str(alvo),
        "achados": achados,
        "erros": sum(1 for a in achados if a["gravidade"] == "erro"),
        "avisos": sum(1 for a in achados if a["gravidade"] == "aviso"),
    }


def de_muitos(caminhos: List[str], raiz: str = ".") -> Dict[str, Any]:
    """Vários arquivos: o conjunto que uma alteração tocou."""
    todos, falhas = [], {}
    for caminho in caminhos[:40]:
        r = do_arquivo(caminho, raiz)
        if r.get("ok"):
            todos.extend(r.get("achados") or [])
        else:
            falhas[caminho] = r.get("erro", "")
    return {
        "ok": True,
        "arquivos": len(caminhos),
        "achados": todos[:MAX_ACHADOS],
        "erros": sum(1 for a in todos if a["gravidade"] == "erro"),
        "avisos": sum(1 for a in todos if a["gravidade"] == "aviso"),
        "nao_lidos": falhas,
    }


__all__ = ["de_muitos", "do_arquivo"]
