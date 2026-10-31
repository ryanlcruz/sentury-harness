"""Modelos que rodam nesta máquina: o que já foi baixado, pôr para rodar, achar e testar.

O runtime é o LM Studio que a pessoa já tem: a linha de comando dele (`lms`) liga
o servidor, carrega o modelo e baixa do Hugging Face. O Sentury lê a pasta de
modelos direto do disco, então a lista aparece mesmo com o LM Studio fechado.

Escolhido um modelo, ele vira a lista de modelos do provedor `lmstudio` do
roteador, pela mesma escolha que a tela de Modelos dos provedores grava: vale na
hora e continua valendo depois de reiniciar.

Os modelos para baixar vêm do Hugging Face, que é a biblioteca pública de onde o
LM Studio também baixa.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from . import ajustes

logger = logging.getLogger(__name__)

PROVEDOR = "lmstudio"
ENDERECO_PADRAO = "http://127.0.0.1:1234/v1"
PEDIDO_DE_TESTE = "Em uma frase curta: o que é rodar um modelo de linguagem localmente?"
_baixando: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def _casa_do_lmstudio() -> Path:
    return Path.home() / ".lmstudio"


def lms() -> Optional[str]:
    """O executável do `lms`, onde o LM Studio instala ou no PATH."""
    nome = "lms.exe" if sys.platform == "win32" else "lms"
    instalado = _casa_do_lmstudio() / "bin" / nome
    return str(instalado) if instalado.exists() else shutil.which("lms")


def pasta_de_modelos() -> Path:
    try:
        lido = json.loads((_casa_do_lmstudio() / "settings.json").read_text(encoding="utf-8"))
        if lido.get("downloadsFolder"):
            return Path(lido["downloadsFolder"])
    except Exception:
        pass
    return _casa_do_lmstudio() / "models"


def memoria_da_maquina() -> Dict[str, int]:
    """Memória total e livre em bytes; zero quando o sistema não diz."""
    if sys.platform == "win32":
        class _Estado(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        estado = _Estado()
        estado.dwLength = ctypes.sizeof(_Estado)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
            return {"total": int(estado.ullTotalPhys), "livre": int(estado.ullAvailPhys)}
    try:
        paginas, tamanho = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        livres = os.sysconf("SC_AVPHYS_PAGES")
        return {"total": paginas * tamanho, "livre": livres * tamanho}
    except Exception:
        return {"total": 0, "livre": 0}


def cabe(tamanho: int, memoria: Optional[Dict[str, int]] = None) -> str:
    """'folgado', 'apertado' ou 'pesado': o modelo ocupa mais ou menos o arquivo, mais o contexto."""
    memoria = memoria or memoria_da_maquina()
    if not memoria["total"]:
        return "desconhecido"
    precisa = tamanho * 1.2
    if precisa <= memoria["total"] * 0.5:
        return "folgado"
    return "apertado" if precisa <= memoria["total"] * 0.8 else "pesado"


def baixados() -> List[Dict[str, Any]]:
    """Os modelos de texto na pasta do LM Studio, um por arquivo GGUF."""
    raiz = pasta_de_modelos()
    if not raiz.exists():
        return []
    memoria = memoria_da_maquina()
    achados = []
    for arquivo in sorted(raiz.rglob("*.gguf")):
        # O projetor de imagem acompanha o modelo de visão; sozinho, não roda.
        if arquivo.name.lower().startswith("mmproj"):
            continue
        relativo = arquivo.relative_to(raiz).as_posix()
        tamanho = arquivo.stat().st_size
        achados.append({"chave": relativo, "nome": arquivo.stem, "repositorio": "/".join(relativo.split("/")[:2]),
                        "tamanho": tamanho, "cabe": cabe(tamanho, memoria)})
    return achados


def _raiz(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def servidor(base_url: str = ENDERECO_PADRAO) -> Dict[str, Any]:
    """Se o servidor responde e o que está carregado nele."""
    try:
        resposta = httpx.get(f"{_raiz(base_url)}/api/v0/models", timeout=2.0)
        resposta.raise_for_status()
        modelos = resposta.json().get("data") or []
        return {"ligado": True, "carregados": [m["id"] for m in modelos if m.get("state") == "loaded"],
                "disponiveis": [{"id": m["id"], "tipo": m.get("type", "")} for m in modelos]}
    except Exception:
        try:
            resposta = httpx.get(f"{base_url.rstrip('/')}/models", timeout=2.0)
            resposta.raise_for_status()
            ids = [m["id"] for m in resposta.json().get("data") or []]
            return {"ligado": True, "carregados": ids, "disponiveis": [{"id": i, "tipo": ""} for i in ids]}
        except Exception:
            return {"ligado": False, "carregados": [], "disponiveis": []}


def _rodar_lms(*argumentos: str, tempo: float) -> Dict[str, Any]:
    executavel = lms()
    if not executavel:
        return {"ok": False, "saida": "O LM Studio não está instalado nesta máquina."}
    try:
        feito = subprocess.run([executavel, *argumentos], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=tempo, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"ok": False, "saida": "O LM Studio não respondeu a tempo. Abra o aplicativo do LM Studio e tente de novo."}
    saida = (feito.stdout + "\n" + feito.stderr).strip()
    return {"ok": feito.returncode == 0, "saida": saida[-1500:]}


def ligar_servidor() -> Dict[str, Any]:
    return _rodar_lms("server", "start", tempo=90)


def carregar(chave: str) -> Dict[str, Any]:
    """Liga o servidor se preciso e carrega o modelo, escolhendo contexto e GPU pelo que a máquina tem."""
    if not servidor()["ligado"]:
        ligado = ligar_servidor()
        if not ligado["ok"]:
            return ligado
    return _rodar_lms("load", chave, "--yes", "--auto", tempo=300)


def descarregar(identificador: str) -> Dict[str, Any]:
    return _rodar_lms("unload", identificador, tempo=60)


def testar(modelo: str, base_url: str = ENDERECO_PADRAO) -> Dict[str, Any]:
    """Um pedido curto, com o tempo e a velocidade de geração."""
    inicio = time.monotonic()
    try:
        resposta = httpx.post(f"{base_url.rstrip('/')}/chat/completions", timeout=120.0, json={
            "model": modelo, "max_tokens": 96, "temperature": 0.2,
            "messages": [{"role": "user", "content": PEDIDO_DE_TESTE}]})
        resposta.raise_for_status()
        dados = resposta.json()
    except Exception as exc:
        return {"ok": False, "erro": f"{type(exc).__name__}: {str(exc)[:200]}"}
    segundos = max(time.monotonic() - inicio, 0.001)
    tokens = int((dados.get("usage") or {}).get("completion_tokens") or 0)
    texto = ((dados.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return {"ok": True, "resposta": texto.strip()[:600], "segundos": round(segundos, 1),
            "tokens_por_segundo": round(tokens / segundos, 1) if tokens else None}


def escolhido() -> Dict[str, str]:
    """O modelo que o provedor `lmstudio` do roteador usa, ou vazio."""
    try:
        from robinbandit.accounts.account_config import overrides_de_modelos

        modelos = overrides_de_modelos().get(PROVEDOR) or []
    except Exception:
        modelos = []
    return {"base_url": ENDERECO_PADRAO, "modelo": modelos[0] if modelos else ""}


def usar(modelo: str) -> Dict[str, str]:
    """O modelo passa a ser o do provedor `lmstudio`; vazio tira a escolha."""
    from robinbandit.accounts.account_config import definir_modelos_de_provedor

    definir_modelos_de_provedor(PROVEDOR, [modelo.strip()] if modelo.strip() else [], "texto")
    return escolhido()


# Servidores locais do roteador ------------------------------------------------

def _instalado(executaveis: List[str]) -> bool:
    for item in executaveis:
        caminho = os.path.expandvars(os.path.expanduser(item))
        if ("/" in caminho or "\\" in caminho) and Path(caminho).exists():
            return True
        if "/" not in item and shutil.which(caminho):
            return True
    return False


def detectar(provedores: Dict[str, Dict[str, Any]], modelos_por_provedor: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    """Cada provedor local do roteador: se está instalado, se o servidor responde e com quais modelos.
    `provedores` é o catálogo do roteador; os executáveis que denunciam a instalação estão em `ajustes.yaml`."""
    receitas = ajustes.cardapio().get("locais") or {}
    achados = []
    for chave, spec in provedores.items():
        if str(spec.get("cost_class") or "") != "local":
            continue
        receita = receitas.get(chave) or {}
        base = str(os.environ.get(str(spec.get("base_url_env") or "")) or spec.get("base_url") or "").rstrip("/")
        modelos: List[str] = []
        ligado = False
        if base:
            try:
                resposta = httpx.get(f"{base}/models", timeout=1.5)
                if resposta.status_code == 200:
                    modelos = [m["id"] for m in resposta.json().get("data") or [] if m.get("id")]
                    ligado = True
            except Exception:
                pass
        achados.append({"provedor": chave, "rotulo": str(spec.get("label") or chave), "base_url": base,
                        "instalado": ligado or _instalado(list(receita.get("executaveis") or [])),
                        "ligado": ligado, "modelos": modelos, "em_uso": list(modelos_por_provedor.get(chave) or []),
                        "onde_rodar": str(receita.get("onde_rodar") or "")})
    return achados


# Modelos para baixar ----------------------------------------------------------

HF = "https://huggingface.co"


def buscar_para_baixar(termo: str, limite: int = 12) -> List[Dict[str, Any]]:
    """Repositórios GGUF mais baixados que casam com o termo; a API é pública e sem chave."""
    resposta = httpx.get(f"{HF}/api/models", timeout=10.0, params={
        "search": termo, "filter": "gguf", "sort": "downloads", "direction": -1, "limit": limite})
    resposta.raise_for_status()
    return [{"repositorio": m["id"], "downloads": m.get("downloads", 0), "curtidas": m.get("likes", 0)}
            for m in resposta.json()]


def arquivos_do_repositorio(repositorio: str) -> List[Dict[str, Any]]:
    """Os GGUF do repositório com tamanho e se cabem nesta máquina, do menor ao maior."""
    resposta = httpx.get(f"{HF}/api/models/{repositorio}/tree/main", timeout=10.0, params={"recursive": "true"})
    resposta.raise_for_status()
    memoria = memoria_da_maquina()
    arquivos = [{"arquivo": item["path"], "tamanho": int(item.get("size") or 0)}
                for item in resposta.json() if str(item.get("path", "")).lower().endswith(".gguf")
                and not item["path"].split("/")[-1].lower().startswith("mmproj")]
    for arquivo in arquivos:
        arquivo["cabe"] = cabe(arquivo["tamanho"], memoria)
    return sorted(arquivos, key=lambda a: a["tamanho"])


def baixar(repositorio: str, arquivo: str) -> Dict[str, Any]:
    """Começa a baixar pelo LM Studio, em segundo plano; `andamento` diz como está."""
    executavel = lms()
    if not executavel:
        return {"ok": False, "saida": "O LM Studio não está instalado nesta máquina."}
    url = f"{HF}/{repositorio}/blob/main/{arquivo}"
    with _LOCK:
        atual = _baixando.get(url)
        if atual and atual["processo"].poll() is None:
            return {"ok": True, "url": url, "estado": "baixando"}
        processo = subprocess.Popen([executavel, "get", url, "--yes"], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                    encoding="utf-8", errors="replace")
        registro = {"processo": processo, "saida": "", "inicio": time.time()}
        _baixando[url] = registro

    def ler():
        for linha in processo.stdout:
            registro["saida"] = (registro["saida"] + linha)[-2000:]

    threading.Thread(target=ler, daemon=True).start()
    return {"ok": True, "url": url, "estado": "baixando"}


def andamento() -> List[Dict[str, Any]]:
    with _LOCK:
        itens = list(_baixando.items())
    saida = []
    for url, registro in itens:
        codigo = registro["processo"].poll()
        estado = "baixando" if codigo is None else ("pronto" if codigo == 0 else "falhou")
        ultima = next((l for l in reversed(registro["saida"].splitlines()) if l.strip()), "")
        saida.append({"url": url, "estado": estado, "ultima_linha": ultima[-200:]})
    return saida
