"""Mede uma mutação candidata na cópia isolada, com os portões de qualquer mudança.

Os portões moram aqui, no código, e não num arquivo de dado: eles protegem, e o
que protege é difícil de mudar de propósito, inclusive pela própria mutação. Os
testes que rodam, porém, são os da cópia, que a mutação pode ter editado; por
isso o resultado marca quando o diff toca a pasta de testes, para quem decide ver.

A medição leva minutos. Roda em segundo plano, uma por vez, e o estado vai para o
registro: a tela acompanha pelo estado `em_avaliacao`.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import ciclo, isolamento, registro

logger = logging.getLogger(__name__)

# (nome, argumentos depois do python, prazo em segundos)
PORTOES: Tuple[Tuple[str, Tuple[str, ...], int], ...] = (
    ("suite", ("-m", "pytest", "-q", "-n", "4", "tests"), 1200),
    ("replay", ("scripts/replay_bateria.py", "--conjunto", "avaliacao"), 900),
    ("evals", ("-m", "sentury.evals.dos_tracos", "rodar"), 900),
)

_TRAVA = threading.Lock()
_medindo: Optional[str] = None

Executor = Callable[[List[str], str, int], Tuple[int, str]]


def _executar(comando: List[str], pasta: str, prazo: int) -> Tuple[int, str]:
    ambiente = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        feito = subprocess.run(comando, cwd=pasta, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=prazo, env=ambiente)
    except subprocess.TimeoutExpired:
        return 124, f"passou do prazo de {prazo}s"
    return feito.returncode, (feito.stdout or "") + (feito.stderr or "")


def _numero(padrao: str, texto: str) -> int:
    achado = re.search(padrao, texto)
    return int(achado.group(1)) if achado else 0


def ler_suite(codigo: int, saida: str) -> Dict[str, Any]:
    falhas = _numero(r"(\d+) failed", saida) + _numero(r"(\d+) errors?\b", saida)
    return {"ok": codigo == 0, "passaram": _numero(r"(\d+) passed", saida), "falharam": falhas}


def ler_replay(codigo: int, saida: str) -> Dict[str, Any]:
    falharam = _numero(r"falharam:\s*(\d+)", saida)
    return {"ok": codigo == 0 and falharam == 0, "iguais": _numero(r"iguais a producao:\s*(\d+)", saida),
            "mudaram": _numero(r"mudaram:\s*(\d+)", saida), "falharam": falharam}


def ler_evals(codigo: int, saida: str) -> Dict[str, Any]:
    achado = re.search(r"(\d+)/(\d+) casos reais passaram", saida)
    passaram, total = (int(achado.group(1)), int(achado.group(2))) if achado else (0, 0)
    return {"ok": codigo == 0 and total > 0 and passaram == total, "passaram": passaram, "total": total}


_LEITORES = {"suite": ler_suite, "replay": ler_replay, "evals": ler_evals}

_LINHA_QUE_DECIDE = re.compile(r"^(?:FAILED|ERROR) |\b\d+ (?:passed|failed|errors?)\b")


def evidencia(saida: str, teto: int = 1500) -> str:
    """O que fica no registro: as linhas que dizem o que reprovou, e o fim da saída.

    Os avisos do pytest saem depois do resumo; guardando só o fim, eles empurram
    o nome do teste que falhou para fora e a reprovação fica sem explicação."""
    decisivas = [linha for linha in saida.splitlines() if _LINHA_QUE_DECIDE.search(linha)]
    if not decisivas:
        return saida[-teto:]
    return "\n".join(decisivas[-30:]) + "\n...\n" + saida[-teto:]


def medir(mutacao_id: str, *, executar: Executor = _executar) -> Dict[str, Any]:
    """Roda os portões na cópia e fecha a avaliação com os números."""
    mutacao = registro.carregar(mutacao_id)
    if mutacao is None:
        return {"ok": False, "erro": f"mutacao desconhecida: {mutacao_id}"}
    diff = isolamento.diferenca(mutacao_id, base=mutacao.baseline_commit or "HEAD")
    if not diff.get("ok"):
        return {"ok": False, "erro": diff.get("erro")}
    pasta = diff["caminho"]
    ciclo.avaliar(mutacao_id)

    fitness: Dict[str, Any] = {}
    for nome, argumentos, prazo in PORTOES:
        inicio = time.monotonic()
        codigo, saida = executar([sys.executable, *argumentos], pasta, prazo)
        fitness[nome] = {**_LEITORES[nome](codigo, saida), "segundos": round(time.monotonic() - inicio)}
        registro.registrar_evento(mutacao_id, f"portao_{nome}", evidencia(saida), ok=fitness[nome]["ok"])
    tocados = diff["alterados"] + diff["novos"]
    fitness["mexe_em_teste"] = sorted(c for c in tocados if c.replace("\\", "/").startswith("tests/"))

    reprovados = [nome for nome, _, _ in PORTOES if not fitness[nome]["ok"]]
    motivo = f"nao passou em: {', '.join(reprovados)}" if reprovados else ""
    return ciclo.concluir_avaliacao(mutacao_id, passou=not reprovados, fitness=fitness, motivo=motivo)


def medindo() -> Optional[str]:
    return _medindo


def iniciar(mutacao_id: str, *, executar: Executor = _executar) -> Dict[str, Any]:
    """Começa a medição em segundo plano. Uma por vez: duas suítes juntas
    disputariam a máquina e mediriam o tempo errado."""
    global _medindo
    mutacao = registro.carregar(mutacao_id)
    if mutacao is None:
        return {"ok": False, "erro": f"mutacao desconhecida: {mutacao_id}"}
    if mutacao.estado != "candidata":
        return {"ok": False, "erro": f"so se mede uma candidata; esta esta '{mutacao.estado}'"}
    if not _TRAVA.acquire(blocking=False):
        return {"ok": False, "erro": f"ja ha uma medicao em andamento ({_medindo})"}
    _medindo = mutacao_id

    def rodar() -> None:
        global _medindo
        try:
            medir(mutacao_id, executar=executar)
        except Exception as exc:
            logger.exception("A medicao da mutacao %s falhou.", mutacao_id)
            # Presa em `em_avaliacao` ela nao sairia mais: fecha reprovada, com o motivo.
            try:
                atual = registro.carregar(mutacao_id)
                if atual is not None and atual.estado == "em_avaliacao":
                    ciclo.concluir_avaliacao(mutacao_id, passou=False, fitness={},
                                             motivo=f"a medicao quebrou: {type(exc).__name__}: {exc}"[:300])
            except Exception:
                logger.debug("Nem o fechamento da falha foi gravado.", exc_info=True)
        finally:
            _medindo = None
            _TRAVA.release()

    threading.Thread(target=rodar, name=f"medir-{mutacao_id}", daemon=True).start()
    return {"ok": True, "id": mutacao_id}


__all__ = ["PORTOES", "evidencia", "iniciar", "ler_evals", "ler_replay", "ler_suite", "medindo", "medir"]
