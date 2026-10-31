"""Sandbox Python, o escape-hatch de CÁLCULO: quando o gestor pede algo que
nenhuma ferramenta fixa cobre (uma métrica custom, um recorte estatístico, um
cruzamento específico), o agente escreve Python e roda AQUI, sobre uma CÓPIA
LOCAL dos dados (os mesmos DataFrames que o store já busca e cacheia: é a
"cópia no SQLite/pandas" sem precisar de arquivo).

Seguro por construção (contexto local/single-tenant da demo), em camadas:
  1. AST: rejeita `import`, acesso a dunder (`__...__`), e nomes perigosos
     (open/eval/exec/os/getattr...). Sem import, não dá pra escapar pro sistema.
  2. Builtins restritos: só um whitelist seguro (len, sum, sorted, round...).
  3. Timeout: roda numa thread com tempo-limite.
  4. Read-only: os DataFrames são uma cópia; nada é persistido. O agente só
     lê e calcula.

O agente atribui o resultado a `resultado`; devolvemos isso (+ o que imprimir).
"""
import ast
import os
import contextvars
import inspect
import io
import contextlib
import functools
import sys
import threading
import textwrap
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import logging
from typing import Any, Dict
from xml.sax.saxutils import escape as xml_escape

import numpy as np
import pandas as pd

from ..runtime_imports import optional_import

# Garantir backend nao interativo para evitar crashes de thread com Tkinter (Tcl_AsyncDelete)
matplotlib_mod = optional_import("matplotlib")
if matplotlib_mod is not None:
    try:
        matplotlib_mod.use("Agg")
    except Exception:
        pass
plt = optional_import("matplotlib.pyplot")



# 20s: cálculo puro termina bem antes; o teto maior é para os helpers de REDE
# (arxiv_search faz HTTP no arXiv, que costuma levar ~10-15s). `while` é permitido
# com teto de iterações (guard no AST) + este timeout como rede de segurança.
logger = logging.getLogger(__name__)

_TIMEOUT_S = 20.0
_MAX_LINHAS = 200

# Biblioteca padrão que o sandbox aceita importar: formatos, cálculo e texto.
# Nenhuma delas abre socket, roda processo ou lê variável de ambiente: e quem
# abre (`os`, `subprocess`, `socket`, `urllib`, `requests`, `shutil`, `pickle`)
# está fora justamente por isso.
#
# `sqlite3` permite ler bases locais sem expor módulos de rede ou processo.
_IMPORTS_PERMITIDOS = frozenset({
    "csv", "json", "sqlite3", "datetime", "math", "statistics", "decimal",
    "fractions", "re", "collections", "itertools", "functools", "operator",
    "string", "textwrap", "unicodedata", "difflib", "hashlib", "base64",
    "binascii", "struct", "zlib", "gzip", "bz2", "lzma", "uuid", "random",
    "heapq", "bisect", "array", "enum", "dataclasses", "typing", "copy",
    "pprint", "calendar", "zoneinfo", "html", "xml", "configparser",
    "pandas", "numpy",
    # `glob` só lista nomes. Sem ele o código abre um arquivo pelo `open`
    # guardado mas não descobre quais existem: e a tarefa morre aí.
    # `pathlib` continua fora: `Path.write_text`/`unlink` escreveriam sem
    # passar pelo `open` guardado, que é quem confina a escrita.
    "glob",
})

# Nomes proibidos no código (defesa além do AST sem import).
_PROIBIDOS = {
    "__import__", "eval", "exec", "compile", "globals", "locals",
    "getattr", "setattr", "delattr", "vars", "input", "exit", "quit",
    "breakpoint", "help", "memoryview", "classmethod", "staticmethod",
}

# --- Confinamento de arquivos ---------------------------------------------
# A LLM pode CRIAR artefatos (o caminho "coisas incríveis"), mas nunca escapar
# pra fora do sandbox nem sobrescrever código do projeto. Sem `import`, já não há
# os/subprocess/shell (sem sudo). Falta confinar o `open`/gravações: é o que isto
# faz: só artefatos, só dentro da pasta do sandbox, nunca em dirs de código.
def _raiz_do_sandbox() -> Path:
    """Onde cai o caminho relativo do script: a pasta de entregas
    (Documentos/Sentury), porque o que ele grava ali vira anexo para a pessoa."""
    try:
        from ..artifacts.destino import pasta_de_entregas

        return pasta_de_entregas()
    except Exception:
        # Sem o modulo de pastas (analise fora do harness, teste isolado),
        # o temp do sistema e melhor que a pasta de codigo.
        import tempfile

        alvo = Path(tempfile.gettempdir()).resolve() / "sentury-sandbox"
        alvo.mkdir(parents=True, exist_ok=True)
        return alvo


_SANDBOX_ROOT = _raiz_do_sandbox()
_ALLOWED_WRITE_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".html", ".htm", ".pptx",
    ".xlsx", ".csv", ".pdf", ".txt", ".json", ".excalidraw", ".md",
}

# Script so no rascunho. Gravar um `.py` ali e anotacao: quem decide e a hora
# de RODAR, e rodar exige aprovacao do conteudo (`shell.yaml`, secao `executa`).
# Na pasta do usuario seria outra coisa: sobrescrever o codigo dele, que nao
# tem nada a ver com execucao.
_SCRIPT_EXT = {".py", ".ps1", ".sh", ".js", ".ipynb"}
_PROTECTED_DIRS = {
    "sentury", "tests", "scripts", "referencia", ".git", ".venv", ".github",
}


# Arquivos criados PELA execução corrente. Isolado por task async, então duas
# requisições concorrentes não enxergam uma a outra.
#
# Isolar os arquivos por tarefa impede que pedidos concorrentes troquem entregas.
_arquivos_da_execucao: contextvars.ContextVar = contextvars.ContextVar(
    "sentury_sandbox_arquivos", default=None
)


def _plt_registrado():
    """O `plt` do sandbox. O confinamento das imagens mora no canvas
    (`_confinar_imagens_do_matplotlib`), por onde passa toda gravacao."""
    return plt


# O que o sandbox importa do matplotlib. Fora daqui ficam `animation` (o gravador
# de video roda processo) e os backends.
_MATPLOTLIB_LIBERADO = frozenset({
    "matplotlib", "matplotlib.pyplot", "matplotlib.ticker", "matplotlib.colors",
    "matplotlib.cm", "matplotlib.dates",
})


def _matplotlib_do_sandbox(nome: str, com_lista: bool) -> Any:
    """O `matplotlib` que o import do sandbox entrega: so os submodulos liberados."""
    import importlib
    import types

    fachada = types.ModuleType("matplotlib")
    fachada.pyplot = plt
    for sub in ("ticker", "colors", "cm", "dates"):
        setattr(fachada, sub, importlib.import_module(f"matplotlib.{sub}"))
    fachada.rcParams = matplotlib_mod.rcParams
    fachada.use = lambda *a, **k: None  # o backend ja e Agg
    fachada.__version__ = getattr(matplotlib_mod, "__version__", "")
    if com_lista and nome != "matplotlib":
        # `from matplotlib.ticker import X` recebe o proprio submodulo.
        return getattr(fachada, nome.split(".", 1)[1])
    return fachada


def _tabelas_do_setor() -> tuple:
    """O que o pacote ativo quer ver como DataFrame aqui dentro."""
    try:
        from ..domains.do_setor import tabelas_no_sandbox

        return tuple(tabelas_no_sandbox())
    except Exception:
        # Sem dominios (analise fora do harness, teste isolado) o sandbox
        # continua sendo execucao de script: que e o padrao certo.
        return ()


def _registrar_arquivo(caminho: Any) -> None:
    lista = _arquivos_da_execucao.get()
    if lista is not None:
        try:
            item = str(Path(caminho).resolve())
        except Exception:
            item = str(caminho)
        # Um `savefig` passa por mais de uma porta confinada; o arquivo e um so.
        if item not in lista:
            lista.append(item)


def _bases_permitidas() -> list:
    """Onde o sandbox pode tocar: a raiz dele e o que o dono liberou.

    Reusa a permissão que já existe: pasta de trabalho e pastas liberadas na
    tela do Harness. Inventar um segundo sistema de permissão aqui significaria
    duas listas para manter e uma delas desatualizada.
    """
    bases = [_SANDBOX_ROOT]
    try:
        from ..tools.arquivos import casa_do_sentury, pastas_extras, raiz_de_trabalho

        bases.append(raiz_de_trabalho().resolve())
        bases.extend(pasta.resolve() for pasta in pastas_extras())
        # O rascunho do agente. Escrever no proprio bloco de anotacoes nao
        # depende de o dono ter liberado nada: ele nao e do dono.
        bases.append((casa_do_sentury() / "rascunho").resolve())
    except Exception:
        # Sem o módulo de pastas (teste isolado, uso da análise fora do
        # harness), o sandbox volta a ser só a raiz dele. Restringir demais
        # falha de um jeito que dá para entender.
        pass
    return bases


def _tudo_liberado() -> bool:
    try:
        from ..tools.arquivos import tudo_liberado

        return bool(tudo_liberado())
    except Exception:
        return False


def _recusar_area_do_sentury(alvo: Path) -> None:
    """A instalacao do Sentury nao e area de escrita do sandbox.

    Compara por caminho real: junction e symlink do Windows chegam aqui com
    outro nome e passariam por comparacao de texto. O rascunho, que mora dentro
    da casa, continua liberado: e onde o sandbox trabalha.
    """
    from ..tools.arquivos import casa_do_sentury, instalacao_do_sentury

    try:
        real = Path(os.path.realpath(alvo))
    except OSError:
        real = Path(alvo)
    rascunho = Path(os.path.realpath(_SANDBOX_ROOT))
    if rascunho == real or rascunho in real.parents:
        return
    for proibida in (instalacao_do_sentury(), casa_do_sentury()):
        try:
            area = Path(os.path.realpath(proibida))
        except OSError:
            continue
        if area == real or area in real.parents:
            raise PermissionError(
                f"'{alvo}' fica dentro da instalação do Sentury; o sandbox não grava aí."
            )


def _confined_path(filename: Any, *, for_write: bool) -> Path:
    """Resolve `filename` e rejeita o que está fora do espaço permitido.

    Permitido é a raiz do sandbox MAIS as pastas que o dono liberou. Sem isso,
    "analise o arquivo que está nesta pasta" era impossível: o agente tinha
    pandas na mão e não conseguia abrir o arquivo: o Python virava uma
    ferramenta que só sabia mexer no dado que já vinha junto.

    Em escrita continua valendo o resto: só artefato, nunca em diretório de
    código ou infra.
    """
    p = Path(str(filename))
    target = (p if p.is_absolute() else _SANDBOX_ROOT / p).resolve()

    if _tudo_liberado():
        # "Liberar tudo" amplia ONDE se le e se escreve: nao desliga a protecao
        # do código. O caminho completo continua sujeito à lista de proteção.
        rel = Path(*target.parts[1:]) if len(target.parts) > 1 else Path(target.name)
    else:
        base = next(
            (b for b in _bases_permitidas() if b == target or b in target.parents),
            None,
        )
        if base is None:
            raise PermissionError(
                f"'{target}' está fora do espaço liberado. Libere a pasta na tela "
                "do Harness (ou peça acesso a ela) antes de ler ou escrever nela."
            )
        rel = target.relative_to(base)

    if for_write:
        # Ordem importa: primeiro QUEM esta ali (codigo do projeto, instalacao
        # do Sentury), depois O QUE se grava. Um `.py` dentro de `sentury/` e
        # recusado por ser codigo do projeto, nao por ser script.
        if any(parte in _PROTECTED_DIRS for parte in rel.parts[:-1] or rel.parts[:1]):
            raise PermissionError("gravar dentro de diretórios de código/infra do projeto não é permitido.")
        _recusar_area_do_sentury(target)

        sufixo = target.suffix.lower()
        if sufixo in _SCRIPT_EXT:
            # Script so no rascunho: la ele e anotacao, e rodar depende de
            # aprovacao do conteudo. Na pasta do usuario seria sobrescrever o
            # codigo dele, que nao tem nada a ver com execucao.
            rascunho = Path(os.path.realpath(_SANDBOX_ROOT))
            real = Path(os.path.realpath(target))
            if rascunho != real and rascunho not in real.parents:
                raise PermissionError(
                    f"gravar '{sufixo}' só é permitido no rascunho do sandbox "
                    f"({rascunho}); na pasta do usuário isso sobrescreveria código."
                )
        elif sufixo not in _ALLOWED_WRITE_EXT:
            raise PermissionError(
                f"gravar '{target.suffix or 'arquivo sem extensão'}' não é permitido — "
                "o sandbox só grava artefatos (png, jpg, gif, svg, html, pptx, xlsx, csv, pdf, txt, json)."
            )
        # Todo gravador do sandbox passa por aqui: é o ponto único pra saber o
        # que ESTA execução criou.
        _registrar_arquivo(target)
    return target


# Os escritores de DataFrame/Series abrem o arquivo por conta propria, entao nao
# passavam pelo `_guarded_open`: `df.to_csv('x.csv')` gravava na raiz do repo, e
# com caminho absoluto em qualquer lugar da maquina.
_ESCRITORES_DO_PANDAS = (
    "to_csv", "to_excel", "to_json", "to_html", "to_xml", "to_markdown",
    "to_parquet", "to_feather", "to_pickle", "to_stata", "to_latex",
)
# O primeiro argumento de cada um tem nome diferente; por palavra-chave, qualquer
# um destes pode ser o caminho.
_NOMES_DO_CAMINHO = ("path_or_buf", "excel_writer", "path", "buf", "fname")


def _confinar_escritores_do_pandas() -> None:
    """Embrulha os escritores para que, DENTRO do sandbox, o caminho seja confinado.

    Fora de uma execucao (contextvar vazio) o pandas e o de sempre: as ferramentas
    do motor tambem usam pandas, e nao sao codigo do modelo."""
    if pd is None:
        return
    for classe in (pd.DataFrame, pd.Series):
        for nome in _ESCRITORES_DO_PANDAS:
            original = getattr(classe, nome, None)
            if original is None or getattr(original, "_sentury_confinado", False):
                continue

            def envolvido(self, *args, _original=original, **kwargs):
                if _arquivos_da_execucao.get() is not None:
                    if args and isinstance(args[0], (str, os.PathLike)):
                        args = (str(_confined_path(args[0], for_write=True)),) + args[1:]
                    for chave in _NOMES_DO_CAMINHO:
                        if isinstance(kwargs.get(chave), (str, os.PathLike)):
                            kwargs[chave] = str(_confined_path(kwargs[chave], for_write=True))
                return _original(self, *args, **kwargs)

            envolvido._sentury_confinado = True
            envolvido.__name__ = nome
            envolvido.__doc__ = original.__doc__
            setattr(classe, nome, envolvido)


def _confinar_imagens_do_matplotlib() -> None:
    """Dentro do sandbox, toda imagem que o matplotlib grava passa pelo confinamento.

    `fig.savefig`, `plt.savefig` e `canvas.print_png` chegam ao canvas, e o
    `imsave` abre o arquivo sozinho. Fora de uma execucao o matplotlib e o de
    sempre, porque o motor tambem desenha grafico."""
    if matplotlib_mod is None:
        return
    alvos = []
    try:
        import matplotlib.image as imagem
        from matplotlib.backend_bases import FigureCanvasBase
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        alvos.append((FigureCanvasBase, "print_figure", 1))
        alvos += [(FigureCanvasAgg, nome, 1) for nome in (
            "print_png", "print_jpg", "print_jpeg", "print_tif", "print_tiff",
            "print_webp", "print_raw", "print_rgba")]
        alvos.append((imagem, "imsave", 0))
    except Exception as exc:
        logger.debug("matplotlib sem confinamento de imagem: %s", exc)
    for dono, nome, posicao in alvos:
        original = getattr(dono, nome, None)
        if original is None or getattr(original, "_sentury_confinado", False):
            continue

        def envolvido(*args, _original=original, _posicao=posicao, **kwargs):
            if _arquivos_da_execucao.get() is not None:
                if len(args) > _posicao and isinstance(args[_posicao], (str, os.PathLike)):
                    caminho = str(_confined_path(args[_posicao], for_write=True))
                    args = args[:_posicao] + (caminho,) + args[_posicao + 1:]
                for chave in ("fname", "filename", "filename_or_obj"):
                    if isinstance(kwargs.get(chave), (str, os.PathLike)):
                        kwargs[chave] = str(_confined_path(kwargs[chave], for_write=True))
            return _original(*args, **kwargs)

        # O matplotlib filtra os argumentos pela assinatura do `print_*`;
        # `__wrapped__` faz o `inspect.signature` ver a original.
        functools.update_wrapper(envolvido, original)
        envolvido._sentury_confinado = True
        setattr(dono, nome, envolvido)


_confinar_imagens_do_matplotlib()


_confinar_escritores_do_pandas()


def _guarded_open(file: Any, mode: str = "r", *args, **kwargs):
    for_write = any(m in mode for m in ("w", "a", "x", "+"))
    return open(_confined_path(file, for_write=for_write), mode, *args, **kwargs)


# Builtins liberados (seguros, sem acesso a sistema/rede). `open` é o confinado.
# Ampliado: operações de valor puras (chr/ord/hex/repr/bytes/slice/iter…) dão mais
# expressividade à LLM sem nenhuma superfície de sistema (não importam, não abrem
# arquivo, não tocam rede): todas read-only sobre dados em memória.
_SAFE_BUILTINS = {
    k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
    for k in (
        "len", "range", "sum", "min", "max", "sorted", "abs", "round", "list",
        "dict", "set", "tuple", "str", "int", "float", "bool", "enumerate",
        "zip", "map", "filter", "any", "all", "print", "reversed", "type",
        "isinstance", "divmod", "pow", "format",
        # --- ampliação segura (só valor, sem sistema) ---
        "chr", "ord", "bin", "hex", "oct", "repr", "ascii", "frozenset",
        "slice", "next", "iter", "complex", "bytes", "bytearray",
    )
}

# Sem as classes de excecao, `try/except Exception` morre com NameError: o
# modelo escreve codigo defensivo e o sandbox o pune por isso. Classe de
# excecao nao abre arquivo, nao importa e nao toca rede.
_SAFE_BUILTINS.update({
    nome: valor
    for nome, valor in (
        __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
    ).items()
    if isinstance(valor, type) and issubclass(valor, BaseException)
})
_SAFE_BUILTINS["open"] = _guarded_open


def _guarded_import(nome, globais=None, locais=None, deitem=(), nivel=0):
    """`import` que só entrega o que a lista branca permite.

    O AST já recusa o import proibido antes de rodar. Este guarda é a segunda
    tranca, e ela importa: sem ela o `import csv` passava na validação e
    estourava `__import__ not found` na execução: permissão concedida pela
    metade é pior que recusa, porque o agente tenta e falha no meio do turno.
    """
    if nivel:
        raise ImportError("import relativo não é permitido aqui.")
    if nome in _MATPLOTLIB_LIBERADO and matplotlib_mod is not None:
        return _matplotlib_do_sandbox(nome, bool(deitem))
    if _raiz_do_modulo(nome) not in _IMPORTS_PERMITIDOS:
        raise ImportError(
            f"importar '{nome}' não é permitido aqui. "
            f"Liberados: {', '.join(sorted(_IMPORTS_PERMITIDOS))}."
        )
    return _import_de_verdade(nome, globais, locais, deitem, nivel)


_import_de_verdade = (
    __builtins__["__import__"] if isinstance(__builtins__, dict)
    else getattr(__builtins__, "__import__")
)
_SAFE_BUILTINS["__import__"] = _guarded_import


# Teto de iterações por loop `while` (defesa além do timeout de 20s): um guard
# injetado no AST conta as iterações e aborta antes de um loop realmente infinito
# pegar CPU. Assim `while` é liberado (mais expressividade) sem o risco clássico.
_MAX_LOOP_ITER = 1_000_000


class _WhileGuardInjector(ast.NodeTransformer):
    """Injeta `__loopguard__(id)` no topo do corpo de cada `while`: conta as
    iterações e levanta se passar do teto. IDs distintos por loop."""

    def __init__(self) -> None:
        self._n = 0

    def visit_While(self, node: ast.While) -> ast.While:
        self.generic_visit(node)  # trata loops aninhados primeiro
        self._n += 1
        guard = ast.Expr(value=ast.Call(
            func=ast.Name(id="__loopguard__", ctx=ast.Load()),
            args=[ast.Constant(value=self._n)],
            keywords=[],
        ))
        node.body = [guard, *node.body]
        return node


def _make_loopguard():
    counts: Dict[int, int] = {}

    def _guard(loop_id: int) -> None:
        c = counts.get(loop_id, 0) + 1
        counts[loop_id] = c
        if c > _MAX_LOOP_ITER:
            raise RuntimeError(
                f"loop 'while' excedeu {_MAX_LOOP_ITER:,} iterações — provável loop infinito."
            )

    return _guard


def _raiz_do_modulo(nome: str) -> str:
    """`os.path` tem raiz `os`. É a raiz que decide: liberar `xml` não pode
    liberar `xmlrpc`, e liberar `json` não pode liberar `jsonpickle`."""
    return str(nome or "").split(".", 1)[0]


def _import_recusado(no: Any) -> str:
    """O primeiro módulo do import que não está na lista. Vazio = pode."""
    if isinstance(no, ast.ImportFrom):
        # `from . import x` não tem módulo: relativo não faz sentido aqui.
        if no.level:
            return "(import relativo)"
        if (no.module or "") in _MATPLOTLIB_LIBERADO:
            return ""
        raiz = _raiz_do_modulo(no.module or "")
        return "" if raiz in _IMPORTS_PERMITIDOS else (no.module or "(vazio)")
    for alias in getattr(no, "names", []):
        if alias.name in _MATPLOTLIB_LIBERADO:
            continue
        if _raiz_do_modulo(alias.name) not in _IMPORTS_PERMITIDOS:
            return alias.name
    return ""


def _validar(codigo: str) -> str:
    try:
        arvore = ast.parse(codigo)
    except SyntaxError as exc:
        return f"erro de sintaxe: {exc.msg} (linha {exc.lineno})"
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Import, ast.ImportFrom)):
            recusado = _import_recusado(no)
            if recusado:
                return (
                    f"importar '{recusado}' não é permitido aqui. Liberados: "
                    f"{', '.join(sorted(_IMPORTS_PERMITIDOS))}. "
                    "Para rodar algo fora dessa lista, use a ferramenta de shell "
                    "— ela pede autorização, este sandbox não."
                )
        if isinstance(no, ast.Attribute) and no.attr.startswith("__"):
            return "acesso a atributos internos (__...__) não é permitido."
        if isinstance(no, ast.Name) and no.id in _PROIBIDOS:
            return f"uso de '{no.id}' não é permitido."
    return ""



def _serializar(valor: Any) -> Any:
    if isinstance(valor, pd.DataFrame):
        return {"tipo": "tabela", "linhas": len(valor), "dados": valor.head(_MAX_LINHAS).to_dict("records")}
    if isinstance(valor, pd.Series):
        return {"tipo": "serie", "dados": valor.head(_MAX_LINHAS).to_dict()}
    if isinstance(valor, (np.integer, np.floating)):
        return valor.item()
    if isinstance(valor, np.ndarray):
        return valor[:_MAX_LINHAS].tolist()
    return valor


def _load_optional_module(module_name: str):
    return optional_import(module_name)


def _ascii_banner_fallback(text: str) -> str:
    label = (text or "Sentury").strip().upper() or "SENTURY"
    border = "#" * (len(label) + 6)
    middle = f"## {label} ##"
    return f"{border}\n{middle}\n{border}\n"


def _render_ascii_table_helper(headers: list, rows: list, max_cell_width: int = 24) -> str:
    headers = [str(header) for header in (headers or [])]
    if not headers:
        return ""

    normalized_rows = []
    for row in rows or []:
        if isinstance(row, dict):
            normalized_rows.append([row.get(header, "") for header in headers])
            continue
        values = list(row) if isinstance(row, (list, tuple)) else [row]
        if len(values) < len(headers):
            values.extend([""] * (len(headers) - len(values)))
        normalized_rows.append(values[: len(headers)])

    def _wrap_cell(value: Any, width: int) -> list[str]:
        text = "" if value is None else str(value)
        wrapped = textwrap.wrap(
            text,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        )
        return wrapped or [""]

    widths = []
    for index, header in enumerate(headers):
        samples = [header]
        for row in normalized_rows:
            if index < len(row):
                samples.extend(_wrap_cell(row[index], max_cell_width))
        widths.append(min(max(len(sample) for sample in samples), max_cell_width))

    def _border() -> str:
        return "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def _render_row(row_values: list[Any]) -> list[str]:
        wrapped_cells = [
            _wrap_cell(row_values[index] if index < len(row_values) else "", widths[index])
            for index in range(len(headers))
        ]
        row_height = max(len(cell_lines) for cell_lines in wrapped_cells)
        lines = []
        for line_index in range(row_height):
            rendered_cells = []
            for col_index, cell_lines in enumerate(wrapped_cells):
                text = cell_lines[line_index] if line_index < len(cell_lines) else ""
                rendered_cells.append(f" {text.ljust(widths[col_index])} ")
            lines.append("|" + "|".join(rendered_cells) + "|")
        return lines

    output_lines = [_border(), *_render_row(headers), _border()]
    for row in normalized_rows:
        output_lines.extend(_render_row(row))
    output_lines.append(_border())
    return "\n".join(output_lines)


def _find_local_pptx_template() -> Path | None:
    repo_root = Path(__file__).resolve().parents[2]
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = (
        repo_root / ".venv" / "Lib" / "site-packages" / "pptx" / "templates" / "default.pptx",
        repo_root / ".venv" / "lib" / py_ver / "site-packages" / "pptx" / "templates" / "default.pptx",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _write_minimal_pptx(filename: str, slides: list, titulo_deck: str) -> str:
    slides = slides or []
    slide_count = max(1, len(slides) + 1)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _slide_xml(title: str, bullets: list[str]) -> str:
        title_xml = xml_escape(title or "")
        body_xml = "".join(
            (
                "<a:p>"
                "<a:r><a:rPr lang=\"pt-BR\" sz=\"1800\"/>"
                f"<a:t>{xml_escape(str(bullet))}</a:t>"
                "</a:r></a:p>"
            )
            for bullet in bullets
        ) or "<a:p><a:endParaRPr lang=\"pt-BR\"/></a:p>"
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr/>
        <p:txBody>
          <a:bodyPr/><a:lstStyle/>
          <a:p><a:r><a:rPr lang="pt-BR" sz="2800" b="1"/><a:t>{title_xml}</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="3" name="Body"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr/>
        <p:txBody>
          <a:bodyPr/><a:lstStyle/>
          {body_xml}
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""

    content_types = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>",
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">",
        "  <Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>",
        "  <Default Extension=\"xml\" ContentType=\"application/xml\"/>",
        "  <Override PartName=\"/ppt/presentation.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml\"/>",
        "  <Override PartName=\"/docProps/core.xml\" ContentType=\"application/vnd.openxmlformats-package.core-properties+xml\"/>",
        "  <Override PartName=\"/docProps/app.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.extended-properties+xml\"/>",
    ]
    for slide_no in range(1, slide_count + 1):
        content_types.append(
            f"  <Override PartName=\"/ppt/slides/slide{slide_no}.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.slide+xml\"/>"
        )
    content_types.append("</Types>")

    slide_ids = []
    slide_rels = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>",
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">",
    ]
    for slide_no in range(1, slide_count + 1):
        rel_id = f"rId{slide_no}"
        slide_ids.append(f"    <p:sldId id=\"{255 + slide_no}\" r:id=\"{rel_id}\"/>")
        slide_rels.append(
            f"  <Relationship Id=\"{rel_id}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide\" Target=\"slides/slide{slide_no}.xml\"/>"
        )
    slide_rels.append("</Relationships>")

    presentation_xml = "\n".join(
        [
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>",
            "<p:presentation xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\">",
            "  <p:sldIdLst>",
            *slide_ids,
            "  </p:sldIdLst>",
            "  <p:sldSz cx=\"9144000\" cy=\"5143500\"/>",
            "  <p:notesSz cx=\"6858000\" cy=\"9144000\"/>",
            "</p:presentation>",
        ]
    )

    with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "\n".join(content_types),
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "docProps/core.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{xml_escape(titulo_deck or "Sentury")}</dc:title>
  <dc:creator>Sentury</dc:creator>
  <cp:lastModifiedBy>Sentury</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>""",
        )
        archive.writestr(
            "docProps/app.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Sentury</Application>
  <Slides>{slide_count}</Slides>
  <PresentationFormat>Widescreen</PresentationFormat>
</Properties>""",
        )
        archive.writestr("ppt/presentation.xml", presentation_xml)
        archive.writestr("ppt/_rels/presentation.xml.rels", "\n".join(slide_rels))
        archive.writestr("ppt/slides/slide1.xml", _slide_xml(titulo_deck or "Sentury", [""]))
        for index, slide in enumerate(slides, start=2):
            archive.writestr(
                f"ppt/slides/slide{index}.xml",
                _slide_xml(str(slide.get("title", "")), [str(item) for item in (slide.get("bullets") or [])]),
            )

    return f"Apresentacao gerada com sucesso em '{filename}' ({len(slides)} slides + capa)"


def _gif_search_helper(query: str) -> str:
    import urllib.request
    import urllib.parse
    import re
    try:
        q_norm = (query or "celebration").strip().lower()
        q_norm = re.sub(r'[^a-z0-9\s-]', '', q_norm)
        q_encoded = urllib.parse.quote_plus(q_norm)
        url_query = f"{q_encoded.replace('+', '-')}-gifs"
        req = urllib.request.Request(
            f"https://tenor.com/search/{url_query}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        html = urllib.request.urlopen(req, timeout=5).read().decode("utf-8")
        urls = re.findall(r'https://media\.tenor\.com/[a-zA-Z0-9_-]+?/[a-zA-Z0-9_-]+?\.gif', html)
        if urls:
            return urls[0]
    except Exception:
        pass
    # Fallback urls para garantir retorno em caso de timeout
    fallbacks = {
        "triste": "https://media.tenor.com/D5JyOlboNAkAAAAM/star-tamil-chat-sanjay-chat.gif",
        "tristeza": "https://media.tenor.com/D5JyOlboNAkAAAAM/star-tamil-chat-sanjay-chat.gif",
        "feliz": "https://media.tenor.com/1moJO32FTGAAAAAM/star-tamil-chat-startamilchat.gif",
        "celebracao": "https://media.tenor.com/1moJO32FTGAAAAAM/star-tamil-chat-startamilchat.gif"
    }
    return fallbacks.get(query, "https://media.tenor.com/ZkIYsVOL6kEAAAAM/tomascore-horse.gif")


def _arxiv_search_helper(query: str, max_results: int = 5) -> list:
    import urllib.request
    import urllib.parse
    import xml.etree.ElementTree as ET
    import json
    
    NS = {'a': 'http://www.w3.org/2005/Atom'}
    params = {
        'search_query': f'all:{urllib.parse.quote(query)}',
        'max_results': str(max_results),
        'sortBy': 'relevance',
        'sortOrder': 'descending'
    }
    url = "https://export.arxiv.org/api/query?" + "&".join(f"{k}={v}" for k, v in params.items())

    results = []
    try:
        # 15s: o arXiv costuma ser lento. Cabe no teto de 20s do sandbox.
        req = urllib.request.Request(url, headers={'User-Agent': 'Sentury/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()

        root = ET.fromstring(data)
        for entry in root.findall('a:entry', NS):
            title = entry.find('a:title', NS).text.strip().replace('\n', ' ')
            raw_id = entry.find('a:id', NS).text.strip()
            arxiv_id = raw_id.split('/abs/')[-1] if '/abs/' in raw_id else raw_id
            arxiv_id = arxiv_id.split('v')[0]  # base ID
            published = entry.find('a:published', NS).text[:10]
            authors = [a.find('a:name', NS).text for a in entry.findall('a:author', NS)]
            summary = entry.find('a:summary', NS).text.strip().replace('\n', ' ')

            # Citações via Semantic Scholar foram removidas: a chamada extra por
            # paper era lenta/instável (rate-limit) e estourava o tempo. O valor
            # está nos papers reais em si.
            results.append({
                "title": title,
                "arxiv_id": arxiv_id,
                "published": published,
                "authors": ", ".join(authors),
                "summary": summary[:400],
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            })
    except Exception as e:
        print(f"Erro ao buscar no arXiv: {e}")

    return results


def _save_excalidraw_helper(filename: str, nodes: list, connections: list = None) -> str:
    import json
    elements = []
    
    # Nós (ex: {"id": "n1", "text": "Backlog", "color": "red", "x": 100, "y": 100})
    for i, node in enumerate(nodes):
        nid = node.get("id", f"node_{i}")
        text = node.get("text", "")
        nx = node.get("x", 100 + i * 240)
        ny = node.get("y", 100)
        w = node.get("width", 180)
        h = node.get("height", 80)
        
        # Cores (vermelho, amarelo, verde, azul)
        color_map = {
            "red": ("#fee2e2", "#ef4444"),
            "yellow": ("#fef3c7", "#f59e0b"),
            "green": ("#dcfce7", "#10b981"),
            "blue": ("#e0f2fe", "#0284c7")
        }
        bg, border = color_map.get(node.get("color", "blue"), ("#e0f2fe", "#0284c7"))
        
        # Retângulo
        rect = {
            "type": "rectangle",
            "version": 1,
            "versionNonce": i * 1000 + 1,
            "isDeleted": False,
            "id": nid,
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "x": nx,
            "y": ny,
            "width": w,
            "height": h,
            "strokeColor": border,
            "backgroundColor": bg,
            "roundness": {"type": 3},
            "seed": i * 5000 + 3
        }
        elements.append(rect)
        
        # Texto
        text_elem = {
            "type": "text",
            "version": 1,
            "versionNonce": i * 1000 + 2,
            "isDeleted": False,
            "id": f"text_{nid}",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "x": nx + 10,
            "y": ny + (h - 20) / 2,
            "width": w - 20,
            "height": 20,
            "strokeColor": "#1e293b",
            "backgroundColor": "transparent",
            "fontFamily": 1,
            "fontSize": 14,
            "textAlign": "center",
            "verticalAlign": "middle",
            "text": text,
            "containerId": nid,
            "seed": i * 5000 + 4
        }
        elements.append(text_elem)
        
    # Conexões
    connections = connections or []
    for j, conn in enumerate(connections):
        start_id = conn.get("from")
        end_id = conn.get("to")
        start_node = next((n for n in nodes if n["id"] == start_id), None)
        end_node = next((n for n in nodes if n["id"] == end_id), None)
        
        if start_node and end_node:
            sx = start_node.get("x", 100) + start_node.get("width", 180)
            sy = start_node.get("y", 100) + start_node.get("height", 80) / 2
            ex = end_node.get("x", 100)
            ey = end_node.get("y", 100) + end_node.get("height", 80) / 2
            
            arrow = {
                "type": "arrow",
                "version": 1,
                "versionNonce": j * 2000 + 5,
                "isDeleted": False,
                "id": f"arrow_{j}",
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "solid",
                "roughness": 1,
                "opacity": 100,
                "angle": 0,
                "x": sx,
                "y": sy,
                "width": ex - sx,
                "height": ey - sy,
                "strokeColor": "#64748b",
                "backgroundColor": "transparent",
                "points": [[0, 0], [ex - sx, ey - sy]],
                "startBinding": {"elementId": start_id, "focus": 0, "gap": 1},
                "endBinding": {"elementId": end_id, "focus": 0, "gap": 1},
                "seed": j * 6000 + 6
            }
            elements.append(arrow)
            
    payload = {
        "type": "excalidraw",
        "version": 2,
        "source": "sentury",
        "elements": elements,
        "appState": { "viewBackgroundColor": "#ffffff" }
    }
    
    if not filename.endswith(".excalidraw"):
        filename += ".excalidraw"
    filename = str(_confined_path(filename, for_write=True))

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return f"Diagrama Excalidraw salvo com sucesso em '{filename}'"


def _reliable_font(size: int, bold: bool = True):
    """Fonte TTF que existe em qualquer ambiente (usa a DejaVu que vem com o
    matplotlib), com fallback pro bitmap default do Pillow."""
    from PIL import ImageFont
    try:
        from matplotlib import font_manager
        path = font_manager.findfont(font_manager.FontProperties(weight="bold" if bold else "normal"))
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _meme_helper(top_text: str, bottom_text: str = "", filename: str = "meme", bg: str = "#111827") -> str:
    """Gera um 'card meme' PNG (fundo colorido + texto em cima/embaixo, branco com
    contorno preto). Sem imagem-base externa: confiável em local/Render/VPS."""
    from PIL import Image, ImageDraw

    W, H = 900, 600
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)
    fonte = _reliable_font(56)

    def _wrap(texto, max_chars=24):
        palavras, linhas, atual = (texto or "").upper().split(), [], ""
        for p in palavras:
            if len(atual) + len(p) + 1 <= max_chars:
                atual = (atual + " " + p).strip()
            else:
                linhas.append(atual); atual = p
        if atual:
            linhas.append(atual)
        return linhas

    def _draw_bloco(linhas, y_base):
        y = y_base
        for ln in linhas:
            try:
                bbox = draw.textbbox((0, 0), ln, font=fonte)
                w = bbox[2] - bbox[0]
            except Exception:
                w = len(ln) * 28
            x = (W - w) / 2
            # contorno preto
            for dx in (-2, 2):
                for dy in (-2, 2):
                    draw.text((x + dx, y + dy), ln, font=fonte, fill="#000000")
            draw.text((x, y), ln, font=fonte, fill="#ffffff")
            y += 66

    _draw_bloco(_wrap(top_text), 30)
    bottom = _wrap(bottom_text)
    if bottom:
        _draw_bloco(bottom, H - 30 - 66 * len(bottom))

    if not filename.endswith(".png"):
        filename += ".png"
    filename = str(_confined_path(filename, for_write=True))
    img.save(filename)
    return f"Meme gerado com sucesso em '{filename}'"


def _ascii_banner_helper(text: str, font: str = "standard") -> str:
    """Banner ASCII com pyfiglet (fontes: standard, slant, big, banner3, block...)."""
    pyfiglet = _load_optional_module("pyfiglet")
    if pyfiglet is None:
        return _ascii_banner_fallback(text)
    try:
        return pyfiglet.figlet_format(text or "Sentury", font=font)
    except Exception:
        return pyfiglet.figlet_format(text or "Sentury")


def _save_pptx_helper(filename: str, slides: list, titulo_deck: str = "Sentury") -> str:
    """Gera um .pptx a partir de uma lista de slides:
    [{"title": "...", "bullets": ["...", "..."]}]."""
    if not filename.endswith(".pptx"):
        filename += ".pptx"
    filename = str(_confined_path(filename, for_write=True))

    pptx_module = _load_optional_module("pptx")
    pptx_util = _load_optional_module("pptx.util")
    if pptx_module is None or pptx_util is None:
        template_path = _find_local_pptx_template()
        if template_path:
            try:
                Path(filename).write_bytes(template_path.read_bytes())
                return f"Apresentação gerada com sucesso em '{filename}' (modo compatibilidade)"
            except Exception:
                pass
        return _write_minimal_pptx(filename, slides, titulo_deck)

    Presentation = pptx_module.Presentation
    Pt = pptx_util.Pt

    prs = Presentation()
    # Capa
    capa = prs.slides.add_slide(prs.slide_layouts[0])
    capa.shapes.title.text = titulo_deck
    if capa.placeholders and len(capa.placeholders) > 1:
        capa.placeholders[1].text = "Análise do Sentury"

    for s in (slides or []):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = str(s.get("title", ""))
        corpo = slide.placeholders[1].text_frame
        corpo.clear()
        bullets = s.get("bullets") or []
        for i, b in enumerate(bullets):
            p = corpo.paragraphs[0] if i == 0 else corpo.add_paragraph()
            p.text = str(b)
            p.font.size = Pt(18)

    prs.save(filename)
    return f"Apresentação gerada com sucesso em '{filename}' ({len(slides or [])} slides + capa)"


# (fill, stroke, texto) por cor: cards com contraste bom.
_SVG_COLORS = {
    "red": ("#fee2e2", "#ef4444", "#7f1d1d"),
    "yellow": ("#fef9c3", "#eab308", "#713f12"),
    "green": ("#dcfce7", "#22c55e", "#14532d"),
    "blue": ("#dbeafe", "#3b82f6", "#1e3a8a"),
    "purple": ("#ede9fe", "#8b5cf6", "#4c1d95"),
    "gray": ("#f1f5f9", "#94a3b8", "#334155"),
}


def _svg_escape(t: str) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _wrap_svg(texto: str, max_chars: int = 18) -> list:
    palavras, linhas, atual = str(texto).split(), [], ""
    for p in palavras:
        if len(atual) + len(p) + 1 <= max_chars:
            atual = (atual + " " + p).strip()
        else:
            linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return (linhas or [""])[:3]


def _sanitize_svg(svg: str) -> str:
    """Defesa em profundidade: tira <script>, handlers on*, e javascript: do SVG
    livre escrito pelo modelo (o frontend também sanitiza)."""
    import re
    svg = re.sub(r"<script[\s\S]*?</script>", "", svg, flags=re.IGNORECASE)
    svg = re.sub(r"\son\w+\s*=\s*\"[^\"]*\"", "", svg, flags=re.IGNORECASE)
    svg = re.sub(r"\son\w+\s*=\s*'[^']*'", "", svg, flags=re.IGNORECASE)
    svg = re.sub(r"javascript:", "", svg, flags=re.IGNORECASE)
    return svg


def _save_svg_helper(filename: str, svg_content: str) -> str:
    """Salva um SVG LIVRE (o modelo escreve o markup completo: qualquer forma,
    cor, ícone, layout). É o caminho RICO: o limite é a criatividade do modelo,
    não "caixa e seta". Sanitiza e salva; o arquivo é anexado E renderizado inline.
    O SVG deve ter width/height ou viewBox para dimensionar bem."""
    svg = str(svg_content or "").strip()
    low = svg.lower()
    if "<svg" not in low or "</svg>" not in low:
        return "Erro: o conteúdo não é um SVG válido (precisa de <svg>...</svg>)."
    svg = _sanitize_svg(svg)
    if not filename.endswith(".svg"):
        filename += ".svg"
    filename = str(_confined_path(filename, for_write=True))
    with open(filename, "w", encoding="utf-8") as f:
        f.write(svg)
    return f"SVG salvo com sucesso em '{filename}'"


def _save_svg_diagram_helper(filename: str, boxes: list, arrows: list = None,
                             layout: str = "flow", title: str = None) -> str:
    """Diagrama SVG com AUTO-LAYOUT e estilo. O modelo passa só id/text (e opcional
    color/level): as posições são calculadas pelo `layout`, então cada diagrama
    fica diferente e adaptado ao conteúdo. layouts:
    - 'flow'  : esteira horizontal (etapas de uma jornada/processo)
    - 'tree'  : árvore de cima p/ baixo, por 'level' (0,1,2…), bom p/ causa-raiz
    - 'star'  : hub central (1º box) com os demais em leque, efeito x causas
    - 'funnel': funil vertical que estreita, funil de conversão/abandono
    Cores: red/yellow/green/blue/purple/gray."""
    import math
    boxes = boxes or []
    arrows = arrows or []
    n = len(boxes)
    bw, bh, gap = 200, 80, 64
    top = 92 if title else 44
    pos = {}  # id -> (x, y, largura)

    def _infer_tree_levels(items: list[dict]) -> dict[int, list[dict]]:
        if not items:
            return {}
        if any("level" in item for item in items):
            levels = {}
            for item in items:
                levels.setdefault(int(item.get("level", 0)), []).append(item)
            return levels

        root = items[:1]
        remaining = items[1:]
        if not remaining:
            return {0: root}

        levels = {0: root}
        first_row = min(3, len(remaining))
        levels[1] = remaining[:first_row]
        tail = remaining[first_row:]
        level_index = 2
        while tail:
            levels[level_index] = tail[:4]
            tail = tail[4:]
            level_index += 1
        return levels

    def _centered_row_x(canvas_width: float, count: int, box_width: float) -> float:
        row_width = count * box_width + max(0, count - 1) * gap
        return max(gap, (canvas_width - row_width) / 2)

    if layout == "star" and n >= 2:
        cx = 540
        cy = top + 210
        pos[boxes[0]["id"]] = (cx - bw / 2, cy - bh / 2, bw)
        outros = boxes[1:]
        R = 260
        for i, b in enumerate(outros):
            frac = i / max(1, len(outros) - 1) if len(outros) > 1 else 0.5
            ang = math.pi * (1.12 + 0.76 * frac)  # leque na metade de baixo
            pos[b["id"]] = (cx + R * math.cos(ang) - bw / 2, max(top, cy + R * math.sin(ang) - bh / 2), bw)
        W, H = 1080, cy + 290
    elif layout == "tree":
        niveis = _infer_tree_levels(boxes)
        W = max(1080, max(len(v) for v in niveis.values()) * (bw + gap) + gap * 2)
        for lv, bs in sorted(niveis.items()):
            y = top + lv * (bh + gap + 24)
            x0 = _centered_row_x(W, len(bs), bw)
            for j, b in enumerate(bs):
                pos[b["id"]] = (x0 + j * (bw + gap), y, bw)
        H = top + (max(niveis) + 1) * (bh + gap + 24) + 32
    elif layout == "funnel":
        W = 860
        for i, b in enumerate(boxes):
            w = max(240, 700 - i * 72)
            pos[b["id"]] = ((W - w) / 2, top + i * (bh + 22), w)
        H = top + n * (bh + 22) + 36
    else:  # flow
        cols = n if n <= 4 else (3 if n <= 6 else 4)
        rows = max(1, math.ceil(n / max(1, cols)))
        W = max(1080, cols * (bw + gap) + gap * 2)
        y = top + 110
        for i, b in enumerate(boxes):
            row = i // cols
            col = i % cols
            current_cols = min(cols, n - row * cols)
            x0 = _centered_row_x(W, current_cols, bw)
            pos[b["id"]] = (x0 + col * (bw + gap), y + row * (bh + gap), bw)
        H = y + rows * (bh + gap) + 48

    P = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(W)}" height="{int(H)}" '
         f'viewBox="0 0 {int(W)} {int(H)}" font-family="Segoe UI, system-ui, sans-serif">',
         '<defs>',
         '<marker id="arw" markerWidth="12" markerHeight="12" refX="9" refY="4" orient="auto">'
         '<path d="M0,0 L9,4 L0,8 Z" fill="#94a3b8"/></marker>',
         '<filter id="sh" x="-20%" y="-20%" width="140%" height="160%">'
         '<feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.18"/></filter>',
         '</defs>',
         '<rect width="100%" height="100%" fill="#f8fafc"/>']
    if title:
        P.append(f'<text x="{int(W)/2:.0f}" y="52" font-size="23" font-weight="700" '
                 f'fill="#0f172a" text-anchor="middle">{_svg_escape(str(title)[:64])}</text>')

    for a in arrows:
        s, e = pos.get(a.get("from")), pos.get(a.get("to"))
        if not s or not e:
            continue
        x1, y1 = s[0] + s[2] / 2, s[1] + bh / 2
        x2, y2 = e[0] + e[2] / 2, e[1] + bh / 2
        P.append(f'<path d="M{x1:.0f},{y1:.0f} C{(x1+x2)/2:.0f},{y1:.0f} {(x1+x2)/2:.0f},{y2:.0f} {x2:.0f},{y2:.0f}" '
                 f'fill="none" stroke="#94a3b8" stroke-width="2.5" marker-end="url(#arw)"/>')

    for b in boxes:
        p = pos.get(b["id"])
        if not p:
            continue
        x, y, w = p
        fill, stroke, tcol = _SVG_COLORS.get(b.get("color", "blue"), _SVG_COLORS["blue"])
        P.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{bh}" rx="14" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="2.5" filter="url(#sh)"/>')
        linhas = _wrap_svg(b.get("text", ""), max_chars=max(10, int(w / 9)))
        ty = y + bh / 2 - (len(linhas) - 1) * 9 + 5
        for ln in linhas:
            P.append(f'<text x="{x + w/2:.0f}" y="{ty:.0f}" font-size="14.5" font-weight="600" '
                     f'fill="{tcol}" text-anchor="middle">{_svg_escape(ln)}</text>')
            ty += 18

    P.append('</svg>')
    if not filename.endswith(".svg"):
        filename += ".svg"
    filename = str(_confined_path(filename, for_write=True))
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(P))
    return f"Diagrama SVG '{layout}' salvo com sucesso em '{filename}'"


def _save_html_dashboard_helper(filename: str, html_content: str) -> str:
    html = str(html_content or "").strip()
    if not html:
        return "Erro: o conteudo HTML esta vazio."
    if "<html" not in html.lower():
        html = (
            "<!doctype html>\n"
            "<html>\n"
            "<head><meta charset=\"utf-8\"><title>Sentury Dashboard</title></head>\n"
            f"<body>{html}</body>\n"
            "</html>"
        )
    if not filename.endswith(".html"):
        filename += ".html"
    filename = str(_confined_path(filename, for_write=True))
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    return f"Dashboard HTML salvo com sucesso em '{filename}'"


def _coerce_html_codigo(codigo: str) -> str:
    """Corrige o erro comum de o modelo enfiar HTML CRU no `codigo` (às vezes com
    um marcador 'html'/```html na frente, como se fosse um fence) em vez de
    save_html('x.html', '''...'''). Sem isso o sandbox tenta EXECUTAR HTML como
    Python e quebra (ex.: "invalid character ', '"). Embrulha em save_html pra virar
    Python válido e produzir o artefato: mesma filosofia do bridge de SQL."""
    if not codigo:
        return codigo
    # já é Python com um helper de artefato? não mexe.
    if any(h in codigo for h in ("save_html(", "save_svg", "save_pptx", "save_excalidraw")):
        return codigo
    body = codigo.lstrip()
    if body.startswith("```"):
        body = body[3:].lstrip()
    low = body.lower()
    if low.startswith("html\n") or low.startswith("html\r\n") or low == "html":
        body = body.split("\n", 1)[1] if "\n" in body else ""
    body = body.strip()
    while body.endswith("`"):
        body = body[:-1].rstrip()
    head = body[:60].lower()
    if head.startswith((
        "<!doctype", "<html", "<div", "<section", "<main", "<header", "<style",
        "<table", "<article", "<body",
    )):
        quote = '"""' if "'''" in body else "'''"
        return f"save_html('artefato-sentury.html', {quote}{body}{quote})"
    return codigo


async def executar_python(store: Any, codigo: str) -> Dict[str, Any]:
    """Executa o codigo do modelo. Com `SENTURY_PY_CHILD`, num processo filho.

    O desvio fica aqui, no topo, e nao no chamador: assim toda rota que executa
    Python ganha a fronteira de uma vez, e nao so a que alguem lembrou de
    trocar. O filho chama esta mesma funcao la dentro, com a variavel de
    ambiente marcada: sem isso seria recursao infinita.
    """
    if not os.environ.get("SENTURY_EXEC_TRABALHADOR"):
        try:
            from ..exec import provider_python

            if provider_python.habilitado():
                do_filho = await provider_python.executar_em_filho(store, codigo)
                if do_filho is not None:
                    return do_filho
                logger.info("Processo filho indisponivel; executando em processo.")
        except Exception as exc:  # a fronteira e melhoria, nao pode ser bloqueio
            logger.warning("Desvio para o processo filho falhou (%s); seguindo em processo.", exc)

    _orig = (codigo or "").strip()
    codigo = _coerce_html_codigo(_orig)
    if codigo != _orig and codigo.startswith("save_html("):
        try:
            from ..observability import record_intervention
            record_intervention("html_coercion", detail="HTML cru no codigo -> save_html")
        except Exception:
            pass
    # O contextvar separa os arquivos desta execução dos de tarefas concorrentes.
    _arquivos_da_execucao.set([])

    if not codigo:
        return {"erro": "código vazio.", "modo": "em_processo"}
    motivo = _validar(codigo)
    if motivo:
        from ..exec.contrato import CodigoDeErro

        codigo_erro = (
            CodigoDeErro.IMPORT_NEGADO if motivo.startswith("importar '")
            else CodigoDeErro.SANDBOX_NEGADO
        )
        return {
            "erro": motivo, "codigo": codigo, "codigo_erro": codigo_erro,
            "modo": "em_processo",
        }

    # `while` é permitido, mas com teto de iterações injetado no AST (guard). Se a
    # transformação/compilação falhar, cai pro código original (defensivo).
    try:
        arvore = _WhileGuardInjector().visit(ast.parse(codigo))
        ast.fix_missing_locations(arvore)
        codigo_compilado: Any = compile(arvore, "<sandbox>", "exec")
        # Os nomes que o codigo realmente cita. Serve para nao ler tabela
        # que ninguem vai usar.
        citados = {
            no.id for no in ast.walk(arvore) if isinstance(no, ast.Name)
        }
    except Exception:
        codigo_compilado = codigo
        # Sem árvore sintática, mantém a leitura conservadora.
        citados = None

    # Cópia LOCAL dos dados (via o store, que já pagina/cacheia). Read-only.
    async def _read_store(method_name: str, expoe: str = "") -> Any:
        # Evita carregar tabelas que o código não cita.
        if expoe and citados is not None and expoe not in citados:
            return pd.DataFrame()
        method = getattr(store, method_name, None)
        if not callable(method):
            return pd.DataFrame()
        try:
            value = method()
            return await value if inspect.isawaitable(value) else value
        except Exception as exc:
            # Backend fora do ar nao pode derrubar script que nem depende
            # dele. Vazio e o mesmo que o store devolve sem a tabela.
            logger.warning("sandbox: %s indisponivel (%s); seguindo vazio", method_name, exc)
            return pd.DataFrame()

    # Fontes de produção podem ser assíncronas; adaptadores locais também podem
    # oferecer o contrato de leitura de forma síncrona.
    namespace: Dict[str, Any] = {
        "pd": pd,
        "np": np,
        # Pre-exposto para permitir que a LLM gere gráficos usando matplotlib no sandbox.
        # Como o AST bloqueia imports (ast.Import/ImportFrom), expor 'plt' diretamente
        # dá total liberdade à LLM de plotar visualizações e salvá-las no disco (ex: plt.savefig('chart.png')).
        # O orquestrador detecta novos arquivos *.png criados e anexa automaticamente na resposta do chat.
        "plt": _plt_registrado(),
        "gif_search": _gif_search_helper,
        "gif_": _gif_search_helper,
        "arxiv_search": _arxiv_search_helper,
        "save_excalidraw": _save_excalidraw_helper,
        "generate_meme": _meme_helper,
        "ascii_banner": _ascii_banner_helper,
        "save_pptx": _save_pptx_helper,
        "save_svg_diagram": _save_svg_diagram_helper,
        "save_svg": _save_svg_helper,
        "save_html_dashboard": _save_html_dashboard_helper,
        "save_html": _save_html_dashboard_helper,
        "ascii_table": _render_ascii_table_helper,
    }
    # QUAIS tabelas aparecem aqui e declaracao do SETOR. Eram `feedbacks`,
    # `tickets` e `technicians` cravados: tres nomes de CX dentro da ferramenta
    # mais generica do motor. Num pacote de e-commerce o agente abria o Python
    # e encontrava tres variaveis que nao existem no negocio dele; sem pacote,
    # tres tabelas que ninguem pediu.
    for tabela in _tabelas_do_setor():
        if tabela in namespace:
            continue
        try:
            namespace[tabela] = await _read_store(f"get_{tabela}", tabela)
        except Exception:
            namespace[tabela] = pd.DataFrame()
    namespace["__builtins__"] = _SAFE_BUILTINS
    namespace["__loopguard__"] = _make_loopguard()  # teto de iterações do while

    saida = io.StringIO()
    erro: Dict[str, Any] = {}

    def _rodar():
        try:
            with contextlib.redirect_stdout(saida):
                exec(codigo_compilado, namespace)  # noqa: S102 (AST validado + guard de while + builtins restritos)
        except Exception as exc:  # erro do código do agente, não crash do app
            erro["msg"] = f"{type(exc).__name__}: {exc}"

    # Copia o contexto para a thread compartilhar o registro de arquivos
    # desta execução com o chamador.
    _ctx = contextvars.copy_context()
    thread = threading.Thread(target=lambda: _ctx.run(_rodar), daemon=True)
    thread.start()
    thread.join(_TIMEOUT_S)
    if thread.is_alive():
        from ..exec.contrato import CodigoDeErro

        return {
            "erro": f"o código excedeu o limite de {int(_TIMEOUT_S)}s.",
            "codigo": codigo, "codigo_erro": CodigoDeErro.TIMEOUT,
            "modo": "em_processo",
        }
    if erro:
        return {"erro": erro["msg"], "codigo": codigo, "modo": "em_processo"}

    impresso = saida.getvalue().strip()
    resultado = namespace.get("resultado")
    gerados = list(_arquivos_da_execucao.get() or [])
    # Gravar arquivo E devolver. Um script que so escreve o .md pedido caia
    # neste aviso ("voce nao devolveu nada") e a lista de arquivos ia com
    # ele, entao o anexo se perdia e sobrava uma reclamacao no lugar da
    # entrega. Era exatamente a forma da tarefa "me entrega um .md".
    if resultado is None and not impresso and not gerados:
        return {
            "aviso": "o código rodou mas não definiu `resultado` nem imprimiu nada. "
            "Atribua o que quer devolver a uma variável chamada `resultado`.",
            "codigo": codigo,
            "modo": "em_processo",
        }
    return {
        "codigo": codigo,
        "resultado": _serializar(resultado),
        "saida": impresso or None,
        # Quem o orquestrador deve anexar. Lista explícita > varredura por data.
        "arquivos_gerados": gerados,
        "modo": "em_processo",
    }
