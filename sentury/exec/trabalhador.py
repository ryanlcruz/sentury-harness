"""O processo filho que executa o codigo do sandbox.

Roda como `python -m sentury.exec.trabalhador`, le um pedido em JSON pela
entrada padrao e devolve um resultado em JSON pela saida. Nada alem disso: quem
decide o que pode rodar continua sendo `python_exec`, importado aqui dentro.

Por que um processo, e nao uma thread: a thread nao morre. `thread.join(20)`
devolve o controle, mas o codigo continua rodando com o namespace inteiro
pendurado: um `while` que aloca come a memoria do servidor e nao ha o que
fazer. Processo tem fronteira: da para matar, da para limitar, e o que ele
quebra nao atravessa.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

# O pai avisa por variavel de ambiente que este processo e um trabalhador. Sem
# isso, um import acidental deste modulo no servidor nao faz nada: e e assim
# que deve ser.
MARCA = "SENTURY_EXEC_TRABALHADOR"


class _StoreDeArquivos:
    """Store de leitura montado a partir dos arquivos que o pai deixou.

    Responde a `get_<tabela>()`, que e a unica coisa que o sandbox pede de um
    store. Tabela que o pai nao mandou devolve vazio, igual ao backend fora do
    ar: o codigo continua rodando em vez de estourar.
    """

    def __init__(self, tabelas: Dict[str, str]):
        self._tabelas = {str(k): str(v) for k, v in (tabelas or {}).items()}

    def __getattr__(self, nome: str):
        if not nome.startswith("get_"):
            raise AttributeError(nome)
        tabela = nome[4:]

        def _ler():
            import pandas as pd

            caminho = self._tabelas.get(tabela)
            if not caminho:
                return pd.DataFrame()
            try:
                if caminho.endswith(".parquet"):
                    return pd.read_parquet(caminho)
                return pd.read_json(caminho)
            except Exception:
                return pd.DataFrame()

        return _ler


def _aplicar_teto_de_memoria() -> None:
    """Limite de memoria do proprio processo, quando o sistema oferece.

    No POSIX e `RLIMIT_AS`. No Windows nao ha equivalente por processo sem Job
    Object, e o Job fica com o pai: aqui a chamada simplesmente nao faz nada,
    em vez de fingir que limitou.
    """
    teto_mb = int(os.environ.get("SENTURY_EXEC_MEMORIA_MB") or 0)
    if teto_mb <= 0 or os.name == "nt":
        return
    try:
        import resource

        bytes_ = teto_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (bytes_, bytes_))
    except (ImportError, ValueError, OSError):
        pass


def _responder(carga: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(carga, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def principal() -> int:
    # Importar a pilha numerica antes do pedido e o que torna este processo um
    # trabalhador quente. O pai mantem dois destes parados no handshake e
    # consome cada um uma unica vez, evitando tanto o custo frio quanto vazamento
    # de estado entre execucoes.
    try:
        from . import python_exec
    except BaseException as exc:  # noqa: BLE001
        _responder({"pronto": False, "erro": f"{type(exc).__name__}: {exc}"})
        return 1

    _aplicar_teto_de_memoria()
    _responder({"pronto": True})
    try:
        pedido = json.loads(sys.stdin.readline() or "{}")
    except (ValueError, OSError) as exc:
        _responder({"erro": f"pedido ilegivel: {exc}"})
        return 2

    codigo = str(pedido.get("codigo") or "")
    if not codigo.strip():
        _responder({"erro": "codigo vazio"})
        return 2

    try:
        import asyncio
        from . import sentury_tools

        # O store nao atravessa o processo. O pai grava em disco as tabelas que
        # o codigo cita, e aqui elas viram um store de leitura com a mesma cara
        # do original: `executar_python` nao precisa saber que mudou de casa.
        store = _StoreDeArquivos(pedido.get("tabelas") or {})
        sentury_tools.configurar(
            pedido.get("rpc_url") or "",
            pedido.get("rpc_token") or "",
            pedido.get("rpc_ferramentas") or [],
        )
        # A API de helpers continua igual para o codigo do modelo; apenas a rede
        # volta ao pai, que preserva politica e contexto do turno.
        python_exec._gif_search_helper = sentury_tools.gif_search
        python_exec._arxiv_search_helper = sentury_tools.arxiv_search
        resultado = asyncio.run(python_exec.executar_python(store, codigo))
    except BaseException as exc:  # noqa: BLE001 - o filho nunca derruba o pai
        _responder({"erro": f"{type(exc).__name__}: {exc}"})
        return 1

    _responder(resultado if isinstance(resultado, dict) else {"resultado": resultado})
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
