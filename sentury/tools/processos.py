"""Comando que demora não morre: sai de cena e continua.

O shell era síncrono com teto de 60s. Um `npm install`, um build ou um teste
grande batia no teto e era **encerrado**: o agente perdia o trabalho já feito
e não tinha como saber se aquilo tinha terminado depois.

Aqui o teto muda de significado. Ele não é mais "tempo de vida do comando", é
"tempo que eu espero antes de ir fazer outra coisa". Passou do teto, o processo
continua rodando e o agente recebe um identificador para voltar e perguntar.
É o mesmo contrato de uma tarefa em segundo plano: começa, você segue, e o
resultado está lá quando você volta.

A saída é lida enquanto roda, não no fim, porque um processo que demora dez
minutos e só fala no fim não deixa ninguém acompanhar nada.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_PROCESSOS: Dict[str, Dict[str, Any]] = {}

# Um processo terminado ainda é consultável por um tempo: o agente pode voltar
# só no turno seguinte. Depois disso vira lixo e sai da memória.
RETENCAO_S = 3600.0
MAX_GUARDADOS = 40
# Linhas guardadas em ordem de chegada para a tela (saida e erro misturados,
# como num terminal). Acima disso ficam as mais novas.
MAX_LINHAS = 2000

# Quem ouve cada linha assim que ela sai: (fluxo, texto), fluxo "out" ou "err".
OuvinteDeLinha = Callable[[str, str], None]


def _agora() -> float:
    return time.time()


def _limpar_antigos() -> None:
    with _LOCK:
        mortos = [
            pid for pid, item in _PROCESSOS.items()
            if item["fim"] and (_agora() - item["fim"]) > RETENCAO_S
        ]
        for pid in mortos:
            _PROCESSOS.pop(pid, None)
        if len(_PROCESSOS) > MAX_GUARDADOS:
            # Descarta os terminados mais velhos primeiro; quem ainda roda fica.
            terminados = sorted(
                (item for item in _PROCESSOS.values() if item["fim"]),
                key=lambda item: item["fim"],
            )
            for item in terminados[: len(_PROCESSOS) - MAX_GUARDADOS]:
                _PROCESSOS.pop(item["id"], None)


def _drenar(item: Dict[str, Any], fluxo, campo: str, teto: int,
            ao_linha: Optional[OuvinteDeLinha] = None) -> None:
    """Lê linha a linha enquanto o processo vive, para dar acompanhamento."""
    origem = "err" if campo == "erro" else "out"
    try:
        for linha in iter(fluxo.readline, ""):
            with _LOCK:
                if len(item[campo]) < teto:
                    item[campo] += linha
                else:
                    item["truncado"] = True
                item["linhas"].append((origem, linha.rstrip("\r\n")))
                if len(item["linhas"]) > MAX_LINHAS:
                    del item["linhas"][0]
                    item["linhas_cortadas"] += 1
            if ao_linha is not None:
                try:
                    ao_linha(origem, linha.rstrip("\r\n"))
                except Exception:
                    pass
    except (ValueError, OSError):
        pass
    finally:
        try:
            fluxo.close()
        except Exception:
            pass


def iniciar(
    partes: List[str],
    *,
    diretorio: str,
    comando: str,
    teto_saida: int = 20_000,
    ao_linha: Optional[OuvinteDeLinha] = None,
) -> str:
    """Dispara o processo e devolve o identificador na hora."""
    _limpar_antigos()
    pid = f"proc-{uuid.uuid4().hex[:8]}"
    processo = subprocess.Popen(
        partes,
        cwd=diretorio,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        shell=False,
    )
    item: Dict[str, Any] = {
        "id": pid,
        "comando": comando,
        "diretorio": diretorio,
        "processo": processo,
        "saida": "",
        "erro": "",
        "linhas": [],
        "linhas_cortadas": 0,
        "truncado": False,
        "inicio": _agora(),
        "fim": None,
        "codigo": None,
        "encerrado_por_nos": False,
    }
    with _LOCK:
        _PROCESSOS[pid] = item

    leitores = [
        threading.Thread(target=_drenar, args=(item, fluxo, campo, teto_saida, ao_linha), daemon=True)
        for fluxo, campo in ((processo.stdout, "saida"), (processo.stderr, "erro"))
    ]
    for leitor in leitores:
        leitor.start()

    def _aguardar() -> None:
        codigo = processo.wait()
        # O processo sair nao quer dizer que a saida ja foi lida: sem esperar
        # os leitores, quem pergunta logo depois recebe codigo 0 e saida vazia.
        for leitor in leitores:
            leitor.join(timeout=5)
        with _LOCK:
            item["codigo"] = codigo
            item["fim"] = _agora()

    threading.Thread(target=_aguardar, daemon=True).start()
    return pid


def _instantaneo(item: Dict[str, Any], com_saida: bool = True) -> Dict[str, Any]:
    rodando = item["fim"] is None
    dados: Dict[str, Any] = {
        "id": item["id"],
        "comando": item["comando"],
        "rodando": rodando,
        "codigo": item["codigo"],
        "duracao_ms": int(((item["fim"] or _agora()) - item["inicio"]) * 1000),
        "diretorio": item["diretorio"],
    }
    if not rodando:
        dados["ok"] = item["codigo"] == 0 and not item["encerrado_por_nos"]
    if com_saida:
        dados["saida"] = item["saida"]
        dados["erro"] = item["erro"]
        dados["truncado"] = item["truncado"]
        dados["linhas"] = list(item["linhas"])
        dados["linhas_cortadas"] = item["linhas_cortadas"]
    return dados


def estado(pid: str, com_saida: bool = True) -> Dict[str, Any]:
    """Como está aquele comando. É o que o agente chama quando volta."""
    with _LOCK:
        item = _PROCESSOS.get(str(pid or ""))
    if not item:
        return {
            "ok": False,
            "encontrado": False,
            "motivo": f"nao existe processo '{pid}' (pode ter expirado)",
        }
    return {"encontrado": True, **_instantaneo(item, com_saida)}


def esperar(pid: str, timeout: float = 30.0) -> Dict[str, Any]:
    """Espera até o teto. Se não terminar, devolve o parcial e segue vivo."""
    with _LOCK:
        item = _PROCESSOS.get(str(pid or ""))
    if not item:
        return {"ok": False, "encontrado": False, "motivo": f"nao existe processo '{pid}'"}
    limite = _agora() + max(0.0, float(timeout))
    while item["fim"] is None and _agora() < limite:
        time.sleep(0.1)
    return {"encontrado": True, **_instantaneo(item)}


def encerrar(pid: str) -> Dict[str, Any]:
    """Mata o processo. Só por pedido explícito: teto de tempo não mata mais."""
    with _LOCK:
        item = _PROCESSOS.get(str(pid or ""))
    if not item:
        return {"ok": False, "encontrado": False, "motivo": f"nao existe processo '{pid}'"}
    if item["fim"] is not None:
        return {"encontrado": True, "ja_terminou": True, **_instantaneo(item, com_saida=False)}
    item["encerrado_por_nos"] = True
    processo = item["processo"]
    try:
        processo.terminate()
        try:
            processo.wait(timeout=5)
        except subprocess.TimeoutExpired:
            processo.kill()
    except OSError as exc:
        return {"ok": False, "encontrado": True, "motivo": f"{type(exc).__name__}: {exc}"}
    return {"encontrado": True, "encerrado": True, **_instantaneo(item, com_saida=False)}


def listar(apenas_rodando: bool = False) -> List[Dict[str, Any]]:
    _limpar_antigos()
    with _LOCK:
        itens = list(_PROCESSOS.values())
    saida = [_instantaneo(item, com_saida=False) for item in itens]
    if apenas_rodando:
        saida = [item for item in saida if item["rodando"]]
    return sorted(saida, key=lambda item: item["duracao_ms"], reverse=True)


def limpar_tudo() -> None:
    """Só para teste: derruba o que ficou de pé."""
    with _LOCK:
        itens = list(_PROCESSOS.values())
        _PROCESSOS.clear()
    for item in itens:
        if item["fim"] is None:
            try:
                item["processo"].kill()
            except Exception:
                pass
