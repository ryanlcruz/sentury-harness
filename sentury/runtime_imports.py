from __future__ import annotations

import importlib
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType


@lru_cache(maxsize=1)
def ensure_local_site_packages() -> tuple[str, ...]:
    """Tenta aproveitar dependencias opcionais instaladas na venv local do repo.

    Isso ajuda a execucao local/testes quando o comando `python` atual nao foi
    iniciado a partir da `.venv`, sem introduzir dependencia obrigatoria em
    producao. Em ambientes sem `.venv`, a funcao simplesmente nao faz nada.
    """

    repo_root = Path(__file__).resolve().parents[1]
    major = sys.version_info.major
    minor = sys.version_info.minor
    candidates = (
        repo_root / ".venv" / "Lib" / "site-packages",
        repo_root / ".venv" / "lib" / f"python{major}.{minor}" / "site-packages",
    )

    added: list[str] = []
    for candidate in candidates:
        path_str = str(candidate)
        if candidate.exists() and path_str not in sys.path:
            sys.path.append(path_str)
            added.append(path_str)
    return tuple(added)


def optional_import(module_name: str) -> ModuleType | None:
    try:
        return importlib.import_module(module_name)
    except ImportError:
        ensure_local_site_packages()
        try:
            return importlib.import_module(module_name)
        except ImportError:
            return None
