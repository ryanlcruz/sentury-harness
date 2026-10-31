"""Navegar código: onde algo é definido e quem usa.

Antes de alterar uma função é preciso saber quem depende dela. Sem isso, a
alteração é feita no escuro e o dano aparece longe do lugar mexido.

Usa a AST do Python para definições (que sabe distinguir uma função de uma
menção em comentário) e busca textual para as referências, que atravessa
qualquer linguagem.
"""
from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

IGNORADAS = (
    "__pycache__", "node_modules", ".git", ".venv", "venv", "dist", "build",
    "site-packages", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    # Código de terceiro clonado para estudo não é o projeto. Aqui eram 7.375
    # dos 7.771 arquivos Python: navegar sobre eles é gastar o tempo do turno
    # respondendo sobre o repositório de outra pessoa.
    "referencia", "referencias", "refenciais", "vendor", "third_party",
)
MAX_ACHADOS = 200

# Teto do grafo. Projeto maior que isto pede índice de verdade, não uma
# varredura por pergunta: e devolver meio grafo não é navegar.
MAX_ARQUIVOS_NO_GRAFO = 1200


def _base(raiz: str) -> Path:
    """A pasta de trabalho do Sentury, nao a pasta de onde o processo subiu."""
    if raiz:
        return Path(raiz).resolve()
    from .arquivos import raiz_de_trabalho

    return raiz_de_trabalho().resolve()


def _vale_olhar(caminho: Path) -> bool:
    return not any(p in caminho.parts for p in IGNORADAS)


def _arquivos(raiz: Path, extensoes: tuple) -> List[Path]:
    """Os arquivos que valem olhar, PODANDO na descida.

    `rglob` + filtro depois atravessa o `.venv` e o `node_modules` inteiros
    antes de descartá-los: milhares de arquivos lidos para nada. Aqui a pasta
    ignorada nem é aberta, e a diferença é de minutos para segundos num
    projeto com dependências instaladas.
    """
    achados: List[Path] = []
    pilha = [raiz]
    while pilha:
        pasta = pilha.pop()
        try:
            for item in pasta.iterdir():
                if item.is_dir():
                    if item.name not in IGNORADAS and not item.name.startswith("."):
                        pilha.append(item)
                elif item.suffix in extensoes:
                    achados.append(item)
        except OSError:
            continue
    return sorted(achados)


def definicoes(nome: str, raiz: str = "") -> Dict[str, Any]:
    """Onde `nome` é definido: função, classe ou método.

    A AST distingue a definição do uso: `def analisar` é definição, `analisar()`
    numa linha qualquer não é. Busca textual confundiria as duas.
    """
    alvo = str(nome or "").strip()
    if not alvo:
        return {"ok": False, "erro": "falta o nome a procurar"}

    base = _base(raiz)
    achados: List[Dict[str, Any]] = []
    for arquivo in _arquivos(base, (".py",)):
        try:
            arvore = ast.parse(arquivo.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for no in ast.walk(arvore):
            if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if no.name != alvo:
                continue
            achados.append({
                "arquivo": str(arquivo.relative_to(base)),
                "linha": no.lineno,
                "tipo": "classe" if isinstance(no, ast.ClassDef) else "funcao",
                "assinatura": _assinatura(no),
                "doc": (ast.get_docstring(no) or "").split("\n")[0][:120],
            })
    return {"ok": True, "nome": alvo, "definicoes": achados, "total": len(achados)}


def _assinatura(no: ast.AST) -> str:
    if isinstance(no, ast.ClassDef):
        return f"class {no.name}"
    args = [a.arg for a in no.args.args if a.arg != "self"]
    if no.args.vararg:
        args.append("*" + no.args.vararg.arg)
    if no.args.kwarg:
        args.append("**" + no.args.kwarg.arg)
    prefixo = "async def" if isinstance(no, ast.AsyncFunctionDef) else "def"
    return f"{prefixo} {no.name}({', '.join(args)})"


def referencias(
    nome: str, raiz: str = "", *, extensoes: tuple = (".py", ".ts", ".tsx", ".js", ".yaml", ".yml")
) -> Dict[str, Any]:
    """Quem usa `nome`. Atravessa linguagens porque a dependência também
    atravessa: uma função Python pode ser chamada por um YAML de configuração."""
    alvo = str(nome or "").strip()
    if not alvo:
        return {"ok": False, "erro": "falta o nome a procurar"}

    # Fronteira de palavra: procurar `ler` não pode casar com `preencher`.
    padrao = re.compile(rf"\b{re.escape(alvo)}\b")
    base = _base(raiz)
    achados: List[Dict[str, Any]] = []
    for arquivo in _arquivos(base, extensoes):
        try:
            linhas = arquivo.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for numero, linha in enumerate(linhas, start=1):
            if padrao.search(linha):
                achados.append({
                    "arquivo": str(arquivo.relative_to(base)),
                    "linha": numero,
                    "texto": linha.strip()[:160],
                })
                if len(achados) >= MAX_ACHADOS:
                    return {
                        "ok": True, "nome": alvo, "referencias": achados,
                        "total": len(achados), "truncado": True,
                    }
    return {"ok": True, "nome": alvo, "referencias": achados, "total": len(achados),
            "truncado": False}


_CACHE_DO_GRAFO: Dict[str, Any] = {"chave": None, "grafo": None}


def _grafo(base: Path) -> Dict[str, Any]:
    """Quem define o que, e quem chama quem.

    Um passo pelo projeto, nao um por pergunta: percorrer em profundidade
    fazendo I/O por nivel ficaria lento justamente no caso que mais importa, o
    do simbolo muito usado.

    O resultado fica em cache por (raiz, quantidade, mtime mais recente). Sem
    isso, duas perguntas seguidas sobre o mesmo codigo pagam a varredura duas
    vezes: e aqui a varredura levava setenta segundos.
    """
    arquivos = _arquivos(base, (".py",))[:MAX_ARQUIVOS_NO_GRAFO]
    try:
        chave = (str(base), len(arquivos), max((a.stat().st_mtime_ns for a in arquivos), default=0))
    except OSError:
        chave = (str(base), len(arquivos), 0)
    if _CACHE_DO_GRAFO["chave"] == chave and _CACHE_DO_GRAFO["grafo"] is not None:
        return _CACHE_DO_GRAFO["grafo"]

    define: Dict[str, List[Dict[str, Any]]] = {}
    chama: Dict[str, set] = {}
    for arquivo in arquivos:
        try:
            arvore = ast.parse(arquivo.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for no in ast.walk(arvore):
            if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            define.setdefault(no.name, []).append({
                "arquivo": str(arquivo.relative_to(base)),
                "linha": no.lineno,
                "assinatura": _assinatura(no),
            })
            # O que o corpo desta funcao chama, por NOME. Resolver o alvo de
            # verdade exigiria inferencia de tipo; o nome erra em sobrecarga e
            # acerta no caso comum, que e o que serve para navegar.
            alvos = chama.setdefault(no.name, set())
            for dentro in ast.walk(no):
                if isinstance(dentro, ast.Call):
                    func = dentro.func
                    if isinstance(func, ast.Name):
                        alvos.add(func.id)
                    elif isinstance(func, ast.Attribute):
                        alvos.add(func.attr)
    grafo = {"define": define, "chama": chama, "arquivos": len(arquivos)}
    _CACHE_DO_GRAFO.update(chave=chave, grafo=grafo)
    return grafo


def percorrer(
    nome: str,
    raiz: str = "",
    *,
    sentido: str = "chama",
    profundidade: int = 2,
) -> Dict[str, Any]:
    """A cadeia a partir de `nome`.

    `sentido="chama"` desce: o que esta funcao chama, e o que essas chamam.
    `sentido="chamado_por"` sobe: quem a chama, e quem chama esses, e e o
    sentido que responde "e seguro mexer aqui?".

    A profundidade e curta de proposito. Tres niveis num projeto deste tamanho
    devolvem meio grafo, e meio grafo nao e navegacao: e outro monolito para o
    modelo ler.
    """
    alvo = str(nome or "").strip()
    if not alvo:
        return {"ok": False, "erro": "falta o nome a percorrer"}
    if sentido not in ("chama", "chamado_por"):
        return {"ok": False, "erro": "sentido deve ser 'chama' ou 'chamado_por'"}

    base = _base(raiz)
    grafo = _grafo(base)
    if alvo not in grafo["define"] and alvo not in grafo["chama"]:
        return {"ok": False, "erro": f"'{alvo}' nao e uma funcao definida no projeto"}

    if sentido == "chama":
        vizinhos = lambda n: sorted(x for x in grafo["chama"].get(n, ()) if x in grafo["define"])
    else:
        invertido: Dict[str, set] = {}
        for quem, alvos in grafo["chama"].items():
            for a in alvos:
                invertido.setdefault(a, set()).add(quem)
        vizinhos = lambda n: sorted(invertido.get(n, ()))

    # Teste que exercita a função não é quem depende dela: ele não quebra o
    # produto, e listado junto ele afoga o chamador que importa. "Quem chama
    # `marcar`?" devolvia onze linhas, dez delas `test_*`.
    def _do_produto(n: str) -> bool:
        return not n.startswith("test_")

    limite = max(1, min(int(profundidade or 2), 3))
    niveis, vistos = [], {alvo}
    fronteira = [alvo]
    for _ in range(limite):
        proximo = []
        for atual in fronteira:
            for vizinho in vizinhos(atual):
                if vizinho in vistos or not _do_produto(vizinho):
                    continue
                vistos.add(vizinho)
                proximo.append(vizinho)
        if not proximo:
            break
        niveis.append([
            {
                "nome": n,
                "onde": (grafo["define"].get(n) or [{}])[0].get("arquivo", ""),
                "linha": (grafo["define"].get(n) or [{}])[0].get("linha", 0),
                "assinatura": (grafo["define"].get(n) or [{}])[0].get("assinatura", ""),
            }
            for n in proximo[:40]
        ])
        fronteira = proximo[:40]

    return {
        "ok": True,
        "nome": alvo,
        "sentido": sentido,
        "definido_em": grafo["define"].get(alvo, []),
        "niveis": niveis,
        "alcance": sum(len(n) for n in niveis),
    }


def mapa(caminho: str, raiz: str = "") -> Dict[str, Any]:
    """O que existe num arquivo Python, sem precisar lê-lo inteiro.

    Um arquivo de cinco mil linhas não cabe na conversa; o mapa cabe, e diz
    onde ir buscar.
    """
    base = _base(raiz)
    if raiz:
        arquivo = (base / caminho).resolve() if not Path(caminho).is_absolute() else Path(caminho)
    else:
        # Mesma porta do `ler_arquivo`: pasta liberada e alvo sensivel.
        from .arquivos import PastaNaoLiberada, _pedir_a_pasta, _resolver

        try:
            arquivo = _resolver(caminho)
        except PastaNaoLiberada as fora:
            return _pedir_a_pasta(fora, "mapa_do_arquivo")
        except Exception as exc:
            return {"ok": False, "erro": str(exc)}
    if not arquivo.is_file():
        return {"ok": False, "erro": f"'{caminho}' nao existe"}
    try:
        fonte = arquivo.read_text(encoding="utf-8", errors="replace")
        arvore = ast.parse(fonte)
    except (OSError, SyntaxError) as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}

    total = len(fonte.splitlines())
    itens: List[Dict[str, Any]] = []
    for no in arvore.body:
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            fim = getattr(no, "end_lineno", no.lineno) or no.lineno
            item = {
                "nome": no.name, "linha": no.lineno, "linhas": fim - no.lineno + 1,
                "assinatura": _assinatura(no),
            }
            if isinstance(no, ast.ClassDef):
                item["metodos"] = [
                    {"nome": m.name, "linha": m.lineno,
                     "linhas": (getattr(m, "end_lineno", m.lineno) or m.lineno) - m.lineno + 1}
                    for m in no.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
            itens.append(item)

    nome = str(arquivo.relative_to(base)) if arquivo.is_relative_to(base) else str(arquivo)
    return {"ok": True, "arquivo": nome, "linhas": total,
            "itens": itens}


__all__ = ["definicoes", "mapa", "referencias"]
