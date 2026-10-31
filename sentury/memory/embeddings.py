"""Semelhança por sentido: o texto vira vetor num modelo de embeddings.

Liga "agora temos 3 vagas" a "decidimos desligar 3 pessoas", que a semelhança
por radical não liga. O provedor e o modelo são escolhidos na tela
(`ajustes.json`); o cardápio está em `ajustes.yaml`. Todos falam o protocolo de
embeddings da OpenAI, então um adaptador serve para API e para servidor local.

O vetor de cada texto guardado fica em cache no disco, por modelo: só o pedido
novo custa uma chamada. Qualquer falha devolve None e quem chamou segue com a
semelhança por radical; depois de uma falha, o provedor descansa um minuto
para o turno não esperar o mesmo erro de novo.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .. import ajustes

logger = logging.getLogger(__name__)

SECAO = "embeddings"
TEMPO_DA_CHAMADA = 4.0
DESCANSO_DEPOIS_DE_FALHA = 60.0
TETO_DO_CACHE = 4000
LOTE = 16
_LOCK = threading.Lock()
_falhou_em: Dict[str, float] = {}


def _do_ambiente() -> Dict[str, str]:
    """A escolha antiga do `.env`, que vale enquanto ninguém escolheu na tela."""
    from ..config import settings

    if getattr(settings, "SENTURY_GEMINI_EMBEDDINGS", False):
        return {"provedor": "gemini", "modelo": str(getattr(settings, "GEMINI_EMBEDDING_MODEL", "") or "")}
    return {}


def escolha() -> Dict[str, Any]:
    """Provedor e modelo ativos, com a entrada do cardápio; `provedor` 'nenhum' desliga.
    `origem` diz de onde veio: da tela, do `.env` ou do padrão."""
    lido, origem = ajustes.ler(SECAO), "tela"
    if not lido.get("provedor"):
        lido, origem = _do_ambiente(), "env"
    if not lido.get("provedor"):
        lido, origem = {"provedor": (ajustes.cardapio().get(SECAO) or {}).get("padrao") or "nenhum"}, "padrao"
    nome = str(lido["provedor"])
    entrada = ajustes.provedor(SECAO, nome)
    modelos = entrada.get("modelos") or {}
    modelo = str(lido.get("modelo") or "")
    if modelos and modelo not in modelos:
        modelo = next(iter(modelos), "")
    return {"provedor": nome, "modelo": modelo, "entrada": entrada, "origem": origem,
            "base_url": str(lido.get("base_url") or entrada.get("base_url") or "").rstrip("/")}


def corte_do(atual: Dict[str, Any]) -> float:
    entrada = atual["entrada"]
    medido = ((entrada.get("modelos") or {}).get(atual["modelo"]) or {}).get("corte")
    return float(medido if medido is not None else entrada.get("corte_padrao", 0.5))


def ligado() -> bool:
    atual = escolha()
    return atual["provedor"] != "nenhum" and bool(atual["modelo"]) and bool(atual["base_url"])


def chamar(base_url: str, chave: str, modelo: str, textos: List[str], tempo: float = TEMPO_DA_CHAMADA) -> List[List[float]]:
    cabecalho = {"Authorization": f"Bearer {chave}"} if chave else {}
    resposta = httpx.post(f"{base_url}/embeddings", headers=cabecalho, json={"model": modelo, "input": textos},
                          timeout=tempo)
    resposta.raise_for_status()
    dados = resposta.json().get("data") or []
    # Nem todo servidor manda `index`; sem ele, vale a ordem da lista.
    ordenados = sorted(enumerate(dados), key=lambda par: (par[1].get("index", par[0])))
    vetores = [item["embedding"] for _, item in ordenados]
    if len(vetores) != len(textos):
        raise ValueError(f"o provedor devolveu {len(vetores)} vetores para {len(textos)} textos")
    return vetores


def _arquivo_do_cache(atual: Dict[str, Any]) -> Path:
    from ..tools.arquivos import casa_do_sentury

    nome = hashlib.sha1(f"{atual['provedor']}|{atual['base_url']}|{atual['modelo']}".encode()).hexdigest()[:16]
    return casa_do_sentury() / "embeddings" / f"{nome}.json"


def _ler_cache(caminho: Path) -> Dict[str, List[float]]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except Exception:
        return {}


def _impressao(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()


def vetores(textos: List[str], *, guardar: bool = True) -> Optional[List[List[float]]]:
    """Um vetor por texto, ou None quando está desligado ou o provedor falhou."""
    if not textos or not ligado():
        return None
    atual = escolha()
    marca = f"{atual['provedor']}|{atual['modelo']}"
    if time.time() - _falhou_em.get(marca, 0.0) < DESCANSO_DEPOIS_DE_FALHA:
        return None
    caminho = _arquivo_do_cache(atual)
    with _LOCK:
        cache = _ler_cache(caminho)
    faltam = list(dict.fromkeys(t for t in textos if _impressao(t) not in cache))
    novos: Dict[str, List[float]] = {}
    try:
        # Em lotes: um acervo inteiro numa chamada só passa do tempo da chamada, e o lote
        # que já voltou fica no cache mesmo quando um seguinte falha.
        for inicio in range(0, len(faltam), LOTE):
            lote = faltam[inicio:inicio + LOTE]
            vindos = chamar(atual["base_url"], ajustes.chave(atual["entrada"]), atual["modelo"], lote)
            novos.update({_impressao(t): v for t, v in zip(lote, vindos)})
    except Exception as exc:
        _falhou_em[marca] = time.time()
        logger.warning("Embeddings de %s falharam (%s); sigo com a semelhança por palavras.", marca, exc)
        return None
    finally:
        if guardar and novos:
            _guardar(caminho, novos)
    cache.update(novos)
    return [cache[_impressao(t)] for t in textos]


def _guardar(caminho: Path, novos: Dict[str, List[float]]) -> None:
    with _LOCK:
        atuais = _ler_cache(caminho)
        atuais.update(novos)
        while len(atuais) > TETO_DO_CACHE:
            atuais.pop(next(iter(atuais)))
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(atuais), encoding="utf-8")


def cosseno(a: List[float], b: List[float]) -> float:
    norma = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / norma if norma else 0.0


def semelhantes(novo: str, acervo: Dict[str, str], *, limite: int = 3) -> Optional[List[Tuple[str, float]]]:
    """Os nomes do acervo com o mesmo sentido de `novo`, do mais perto ao mais longe.
    None quando os embeddings estão desligados ou falharam."""
    if not acervo or not str(novo or "").strip():
        return [] if ligado() else None
    nomes = list(acervo)
    # O pedido muda a cada turno: entra no cálculo, mas não no cache do disco.
    guardados = vetores([acervo[n] for n in nomes])
    if guardados is None:
        return None
    pergunta = vetores([novo], guardar=False)
    if pergunta is None:
        return None
    corte = corte_do(escolha())
    notas = sorted(((n, cosseno(pergunta[0], v)) for n, v in zip(nomes, guardados)), key=lambda par: -par[1])
    return [(n, round(nota, 3)) for n, nota in notas if nota >= corte][:limite]


def repetida(novo: str, acervo: Dict[str, str]) -> Optional[str]:
    """O nome do texto guardado que diz o mesmo que `novo`, ou None. Só responde com
    modelo que tem `repeticao` medida no cardápio: sem a medida, parecido demais e
    igual se confundem, e juntar duas notas distintas apaga uma delas."""
    if not acervo or not str(novo or "").strip() or not ligado():
        return None
    atual = escolha()
    corte = ((atual["entrada"].get("modelos") or {}).get(atual["modelo"]) or {}).get("repeticao")
    if corte is None:
        return None
    nomes = list(acervo)
    guardados = vetores([acervo[n] for n in nomes])
    pergunta = vetores([novo]) if guardados is not None else None
    if pergunta is None:
        return None
    nome, nota = max(((n, cosseno(pergunta[0], v)) for n, v in zip(nomes, guardados)), key=lambda par: par[1])
    return nome if nota >= float(corte) else None
