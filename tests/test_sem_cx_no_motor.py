"""O motor nao fala de CX: vocabulario de CX so dentro de `setores/cx/`.

Esta trava conta toda ocorrencia de vocabulario estrito de CX fora
do pacote (strings de Python, `.md` e `.yaml` do motor) e falha se o numero
subir. O teto so desce: cada limpeza baixa o numero aqui.

Comentario e docstring nao contam (explicam por que o CX saiu). Palavras que
qualquer setor usa (regiao, ticket, sla) ficam de fora.
"""
import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "sentury"
# O LEIA-ME dos setores explica a separacao e cita o CX de proposito.
FORA = ("domains/setores/cx", "domains/setores/LEIA-ME.md", "plugins", "client", "__pycache__", "tests")
TERMOS = re.compile(
    r"\b(nps|csat|detrator\w*|promotor\w*|pct_sla\w*|pct_backlog|pct_em_risco|unidade_negocio"
    r"|filia(?:l|is)|analyze_[a-z_]+|root_cause|de cx|analytics cx|experiencia do cliente"
    r"|experiência do cliente)\b",
    re.IGNORECASE,
)
# Ocorrencias que ainda restam no motor. So pode descer.
TETO = 79


def _fora_do_cx(caminho: Path) -> bool:
    rel = caminho.relative_to(RAIZ).as_posix()
    return not any(rel.startswith(f) or f"/{f}/" in f"/{rel}" for f in FORA)


def _strings_vivas(caminho: Path):
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    docs = set()
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and no.body:
            primeiro = no.body[0]
            if isinstance(primeiro, ast.Expr) and isinstance(primeiro.value, ast.Constant):
                docs.add(id(primeiro.value))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Constant) and isinstance(no.value, str) and id(no) not in docs:
            yield no.lineno, no.value


def ocorrencias():
    achadas = []
    for caminho in sorted(RAIZ.rglob("*")):
        if not caminho.is_file() or not _fora_do_cx(caminho):
            continue
        if caminho.suffix == ".py":
            for linha, texto in _strings_vivas(caminho):
                achadas += [(caminho, linha, m.group(0)) for m in TERMOS.finditer(texto)]
        elif caminho.suffix in (".md", ".yaml", ".yml"):
            for n, texto in enumerate(caminho.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                achadas += [(caminho, n, m.group(0)) for m in TERMOS.finditer(texto)]
    return achadas


def test_cx_no_motor_so_diminui():
    achadas = ocorrencias()
    if TETO is None:
        return
    assert len(achadas) <= TETO, (
        f"{len(achadas)} ocorrencias de CX fora de setores/cx (teto {TETO}). "
        "Vocabulario de CX mora no pacote do setor."
    )
