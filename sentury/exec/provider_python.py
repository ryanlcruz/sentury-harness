"""Executa o sandbox Python em um processo filho descartavel e preaquecido.

Cada trabalhador importa a pilha numerica, anuncia que esta pronto, atende uma
unica execucao e termina. O pool repoe o processo consumido em background. Isso
combina baixa latencia com isolamento: nenhum namespace sobrevive ao pedido.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ambiente import bandeiras_de_processo, preparar_env
from .contrato import CodigoDeErro
from .limites import LimiteDeProcesso, aplicar_limites, matar_arvore
from .rpc import ServidorRPC

logger = logging.getLogger(__name__)

TIMEOUT_PADRAO_S = 30.0
MEMORIA_MAXIMA_MB = 1536
TAMANHO_DO_POOL = 2


class _TrabalhadorQuente:
    def __init__(self, processo: subprocess.Popen, limite: Optional[LimiteDeProcesso]):
        self.processo = processo
        self.limite = limite


_pool: "queue.LifoQueue[_TrabalhadorQuente]" = queue.LifoQueue()
_pool_ativo = False
_pool_lock = threading.RLock()


def habilitado() -> bool:
    from ..config import settings

    return bool(getattr(settings, "SENTURY_PY_CHILD", False))


async def _materializar_tabelas(store: Any, codigo: str, pasta: Path) -> Dict[str, str]:
    """Materializa somente DataFrames citados no codigo; JSON e o fallback."""
    if store is None:
        return {}
    import ast

    try:
        citados = {no.id for no in ast.walk(ast.parse(codigo)) if isinstance(no, ast.Name)}
    except SyntaxError:
        citados = set()
    if not citados:
        return {}

    from .python_exec import _tabelas_do_setor

    caminhos: Dict[str, str] = {}
    for tabela in _tabelas_do_setor():
        if tabela not in citados:
            continue
        metodo = getattr(store, f"get_{tabela}", None)
        if not callable(metodo):
            continue
        try:
            valor = metodo()
            dados = await valor if asyncio.iscoroutine(valor) else valor
        except Exception as exc:
            logger.warning("Tabela '%s' indisponivel para o filho: %s", tabela, exc)
            continue
        if dados is None:
            continue
        alvo = pasta / f"{tabela}.parquet"
        try:
            dados.to_parquet(alvo)
        except Exception:
            alvo = pasta / f"{tabela}.json"
            try:
                dados.to_json(alvo, orient="records")
            except Exception as exc:
                logger.warning("Tabela '%s' nao pode ser serializada: %s", tabela, exc)
                continue
        caminhos[tabela] = str(alvo)
    return caminhos


def _argv_do_filho() -> List[str]:
    return [sys.executable, "-m", "sentury.exec.trabalhador"]


def _ambiente_do_filho(raiz_do_projeto: Path) -> Dict[str, str]:
    extra = {
        "PYTHONPATH": str(raiz_do_projeto),
        "SENTURY_EXEC_TRABALHADOR": "1",
        "SENTURY_EXEC_MEMORIA_MB": str(MEMORIA_MAXIMA_MB),
    }
    # Politica de caminho, nao segredo. Sem isto o filho pode cair na casa real
    # do usuario quando o pai esta isolado em outra SENTURY_HOME.
    for nome in ("SENTURY_HOME", "SENTURY_WORKSPACE", "SENTURY_DOMAIN"):
        valor = os.environ.get(nome)
        if valor:
            extra[nome] = valor
    # A entrega cai onde o pai entregaria, já resolvida: o filho não refaz a busca
    # pela pasta de documentos nem escapa do isolamento do pai.
    try:
        from ..artifacts.destino import pasta_de_entregas

        extra["SENTURY_ARTEFATOS_DIR"] = str(pasta_de_entregas())
    except OSError:
        pass
    return preparar_env(extra)


def _criar_trabalhador() -> Optional[_TrabalhadorQuente]:
    raiz = Path(__file__).resolve().parents[2]
    try:
        processo = subprocess.Popen(
            _argv_do_filho(), cwd=str(raiz),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=_ambiente_do_filho(raiz), **bandeiras_de_processo(),
        )
    except OSError as exc:
        logger.warning("Processo filho indisponivel: %s", exc)
        return None

    limite = aplicar_limites(processo, MEMORIA_MAXIMA_MB)
    try:
        prontidao: "queue.Queue[str]" = queue.Queue(maxsize=1)

        def _ler_prontidao() -> None:
            prontidao.put(processo.stdout.readline() if processo.stdout else "")

        threading.Thread(target=_ler_prontidao, daemon=True).start()
        linha = prontidao.get(timeout=30)
        pronto = json.loads(linha or "{}")
        if not pronto.get("pronto"):
            raise RuntimeError(pronto.get("erro") or "handshake ausente")
    except Exception as exc:
        logger.warning("Trabalhador Python nao iniciou (%s)", exc)
        matar_arvore(processo, limite)
        return None
    return _TrabalhadorQuente(processo, limite)


def _fechar_trabalhador(trabalhador: _TrabalhadorQuente, *, matar: bool = False) -> None:
    processo = trabalhador.processo
    if matar and processo.poll() is None:
        matar_arvore(processo, trabalhador.limite)
    else:
        try:
            if processo.stdin:
                processo.stdin.close()
        except OSError:
            pass
        try:
            processo.wait(timeout=3)
        except subprocess.TimeoutExpired:
            matar_arvore(processo, trabalhador.limite)
        if trabalhador.limite:
            trabalhador.limite.fechar()
    for fluxo in (processo.stdout, processo.stderr):
        try:
            if fluxo:
                fluxo.close()
        except OSError:
            pass


async def _criar_async() -> Optional[_TrabalhadorQuente]:
    return await asyncio.get_running_loop().run_in_executor(None, _criar_trabalhador)


async def iniciar_pool(tamanho: int = TAMANHO_DO_POOL) -> None:
    """Preaquece trabalhadores no startup da API."""
    global _pool_ativo
    with _pool_lock:
        if _pool_ativo:
            return
        _pool_ativo = True
    criados = await asyncio.gather(*(_criar_async() for _ in range(max(1, int(tamanho)))))
    for trabalhador in criados:
        if trabalhador is not None:
            _pool.put(trabalhador)


async def encerrar_pool() -> None:
    global _pool_ativo
    with _pool_lock:
        _pool_ativo = False
    while True:
        try:
            trabalhador = _pool.get_nowait()
        except queue.Empty:
            break
        _fechar_trabalhador(trabalhador, matar=True)


async def _repor_pool() -> None:
    if not _pool_ativo or _pool.qsize() >= TAMANHO_DO_POOL:
        return
    trabalhador = await _criar_async()
    if trabalhador is None:
        return
    if _pool_ativo and _pool.qsize() < TAMANHO_DO_POOL:
        _pool.put(trabalhador)
    else:
        _fechar_trabalhador(trabalhador, matar=True)


async def _obter_trabalhador() -> Optional[_TrabalhadorQuente]:
    try:
        return _pool.get_nowait()
    except queue.Empty:
        return await _criar_async()


def _registrar_fallback(motivo: Any) -> None:
    try:
        from ..observability import record_intervention

        record_intervention("python_child_fallback", detail=motivo)
    except Exception:
        pass


def _ferramentas_rpc() -> Dict[str, Any]:
    """A unica superficie do pai visivel ao filho."""
    from .python_exec import _arxiv_search_helper, _gif_search_helper

    return {
        "gif_search": _gif_search_helper,
        "arxiv_search": _arxiv_search_helper,
    }


async def executar_em_filho(
    store: Any,
    codigo: str,
    *,
    timeout: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Executa no filho; ``None`` pede fallback para o modo em processo."""
    limite_s = float(timeout if timeout is not None else TIMEOUT_PADRAO_S)
    inicio = time.time()
    with tempfile.TemporaryDirectory(prefix="sentury-exec-") as temporaria:
        pasta = Path(temporaria)
        try:
            tabelas = await _materializar_tabelas(store, codigo, pasta)
        except Exception as exc:
            logger.warning("Nao consegui preparar os dados para o filho: %s", exc)
            _registrar_fallback(exc)
            return None

        trabalhador = await _obter_trabalhador()
        if trabalhador is None:
            _registrar_fallback("processo filho indisponivel")
            return None
        processo = trabalhador.processo
        ferramentas_rpc = _ferramentas_rpc()
        servidor_rpc = ServidorRPC(ferramentas_rpc)

        try:
            servidor_rpc.iniciar()
            pedido = json.dumps({
                "codigo": codigo,
                "tabelas": tabelas,
                # Pipe, nao argv: o token nao aparece no tasklist.
                "rpc_url": servidor_rpc.url,
                "rpc_token": servidor_rpc.token,
                "rpc_ferramentas": list(ferramentas_rpc),
            }, ensure_ascii=False) + "\n"
            if not processo.stdin or not processo.stdout:
                raise OSError("pipes do trabalhador indisponiveis")
            processo.stdin.write(pedido)
            processo.stdin.flush()
            leitura = asyncio.get_running_loop().run_in_executor(None, processo.stdout.readline)
            saida = await asyncio.wait_for(leitura, timeout=max(1.0, limite_s))
        except asyncio.TimeoutError:
            _fechar_trabalhador(trabalhador, matar=True)
            return {
                "erro": f"a execucao passou de {int(limite_s)}s e foi encerrada.",
                "codigo": codigo,
                "codigo_erro": CodigoDeErro.TIMEOUT,
                "modo": "filho",
                "duracao_ms": int((time.time() - inicio) * 1000),
            }
        except Exception as exc:
            logger.warning("Falha ao falar com o filho (%s); caindo no modo em processo", exc)
            _fechar_trabalhador(trabalhador, matar=True)
            _registrar_fallback(exc)
            return None
        finally:
            servidor_rpc.fechar()
            if _pool_ativo:
                try:
                    asyncio.create_task(_repor_pool())
                except RuntimeError:
                    pass

        erro = ""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: processo.wait(timeout=5)
            )
            if processo.stderr:
                erro = processo.stderr.read()
            _fechar_trabalhador(trabalhador)
        except Exception:
            _fechar_trabalhador(trabalhador, matar=True)

        if not (saida or "").strip():
            motivo = (erro or "").strip().splitlines()[-1:] or ["sem saida"]
            if processo.returncode:
                return {
                    "erro": f"a execucao foi encerrada pelo sistema ({motivo[0]}).",
                    "codigo": codigo,
                    "codigo_erro": CodigoDeErro.MEMORIA,
                    "modo": "filho",
                    "duracao_ms": int((time.time() - inicio) * 1000),
                }
            _registrar_fallback(motivo[0])
            return None

        try:
            resultado = json.loads(saida)
        except ValueError:
            _registrar_fallback("resposta ilegivel")
            return None
        if not isinstance(resultado, dict):
            _registrar_fallback("resposta nao e objeto")
            return None
        if str(resultado.get("erro") or "").startswith("MemoryError"):
            resultado["codigo_erro"] = CodigoDeErro.MEMORIA
        resultado["modo"] = "filho"
        resultado["duracao_ms"] = int((time.time() - inicio) * 1000)
        return resultado
