"""O que funcionou em cada site, para não pagar a escada inteira de novo.

A escada de percepção começa barata (ler o texto da página) e sobe (abrir o
navegador, olhar o print). Sem memória, cada página do mesmo site repete a
subida: a leitura simples volta vazia porque o site monta com JavaScript, o
agente descobre, abre o navegador, e na página seguinte descobre de novo.

Isto guarda, por origem, quantas vezes cada degrau funcionou e falhou, e
devolve uma dica curta. Não decide nada: quem escolhe o degrau é o agente.
O estado mora em `~/.sentury/estrategias.json`, fora do repositório.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

_LOCK = threading.RLock()

LER_PAGINA = "ler_pagina"
BROWSER = "browser"


def _arquivo() -> Path:
    casa = Path(os.environ.get("SENTURY_HOME") or (Path.home() / ".sentury"))
    casa.mkdir(parents=True, exist_ok=True)
    return casa / "estrategias.json"


def origem(url: str) -> str:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _ler() -> Dict[str, Any]:
    try:
        return json.loads(_arquivo().read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def registrar(url: str, degrau: str, funcionou: bool, motivo: str = "") -> None:
    chave = origem(url)
    if not chave:
        return
    with _LOCK:
        dados = _ler()
        reg = dados.setdefault(chave, {}).setdefault(degrau, {"funcionou": 0, "falhou": 0})
        reg["funcionou" if funcionou else "falhou"] += 1
        if motivo:
            reg["ultimo_motivo"] = str(motivo)[:120]
        reg["em"] = time.time()
        alvo = _arquivo()
        tmp = alvo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(alvo)


def do_site(url: str) -> Dict[str, Any]:
    return _ler().get(origem(url), {})


def dica(url: str, degrau: str) -> Optional[str]:
    """Uma frase quando o histórico do site aponta outro degrau, ou None."""
    site = do_site(url)
    leitura = site.get(LER_PAGINA, {})
    navegador = site.get(BROWSER, {})
    if degrau == LER_PAGINA and leitura.get("falhou", 0) > leitura.get("funcionou", 0) \
            and navegador.get("funcionou", 0):
        return (f"em {origem(url)}, a leitura simples voltou vazia antes e o navegador funcionou: "
                "prefira `browser` para este site")
    if degrau == BROWSER and navegador.get("falhou", 0) > navegador.get("funcionou", 0) \
            and navegador.get("ultimo_motivo"):
        return (f"em {origem(url)}, o navegador foi barrado antes ({navegador['ultimo_motivo']}): "
                "considere outra fonte para a mesma informação")
    return None


# Abaixo disto a leitura simples nao trouxe a pagina: o texto que sobra e menu
# e rodape, e o conteudo monta com JavaScript.
_TEXTO_MINIMO = 200


# --- o medidor da escada -------------------------------------------------------
#
# Para provar que "reduzimos screenshot" faltava contar. O tracer e um anel de
# 100 em memoria: morre com o processo e nao separa texto de print. Isto e um
# diario append-only, uma linha por leitura, em `~/.sentury/leituras.jsonl`:
# da para somar por site, por dia e por conversa.
TEXTO, PRINT = "texto", "print"
_DIAS_NO_DIARIO = 90
_PODA_ACIMA_DE_BYTES = 2 * 1024 * 1024
# O que cada acao do navegador devolve. `esperar`, `conferir`, `pensar` e
# `console` nao sao leitura da pagina.
_TIPO_DA_ACAO = {"imagens": PRINT, "ver": PRINT, "snapshot": TEXTO, "navegar": TEXTO,
                 "clicar": TEXTO, "digitar": TEXTO, "rolar": TEXTO}


def _diario() -> Path:
    return _arquivo().with_name("leituras.jsonl")


def anotar_leitura(url: str, degrau: str, tipo: str, sessao: str = "", *,
                   agora: Optional[float] = None) -> None:
    """Uma leitura: de qual site, por qual degrau, e se foi texto ou print."""
    quando = time.time() if agora is None else agora
    linha = json.dumps({
        "em": round(quando, 3), "dia": time.strftime("%Y-%m-%d", time.localtime(quando)),
        "sessao": str(sessao or ""), "origem": origem(url), "degrau": degrau, "tipo": tipo,
    }, ensure_ascii=False)
    with _LOCK:
        try:
            with _diario().open("a", encoding="utf-8") as arquivo:
                arquivo.write(linha + "\n")
            if _diario().stat().st_size > _PODA_ACIMA_DE_BYTES:
                _podar_diario(quando)
        except OSError:
            pass  # medir nunca derruba a leitura que esta sendo medida


def _linhas(desde: float = 0.0):
    try:
        conteudo = _diario().read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for bruta in conteudo:
        try:
            linha = json.loads(bruta)
        except json.JSONDecodeError:
            continue
        if float(linha.get("em") or 0) >= desde:
            yield linha


def _podar_diario(agora: float) -> None:
    mantidas = [json.dumps(l, ensure_ascii=False) for l in _linhas(agora - _DIAS_NO_DIARIO * 86400)]
    tmp = _diario().with_suffix(".tmp")
    tmp.write_text("\n".join(mantidas) + ("\n" if mantidas else ""), encoding="utf-8")
    tmp.replace(_diario())


def resumo_da_escada(dias: int = 30, *, agora: Optional[float] = None) -> Dict[str, Any]:
    """Quantas leituras foram texto e quantas foram print, no todo e por site,
    por dia e por conversa. `parcela_print` e o numero que tem que cair."""
    desde = (time.time() if agora is None else agora) - int(dias) * 86400
    total = {TEXTO: 0, PRINT: 0}
    por: Dict[str, Dict[str, Dict[str, int]]] = {"site": {}, "dia": {}, "sessao": {}}
    for linha in _linhas(desde):
        tipo = linha.get("tipo")
        if tipo not in total:
            continue
        total[tipo] += 1
        for eixo, chave in (("site", linha.get("origem")), ("dia", linha.get("dia")),
                            ("sessao", linha.get("sessao"))):
            if chave:
                por[eixo].setdefault(chave, {TEXTO: 0, PRINT: 0})[tipo] += 1
    leituras = total[TEXTO] + total[PRINT]
    return {
        "dias": int(dias), "leituras": leituras, **total,
        "parcela_print": round(total[PRINT] / leituras, 3) if leituras else None,
        "por_site": por["site"], "por_dia": por["dia"], "por_sessao": por["sessao"],
    }


def apos_ler_pagina(url: str, resultado: Dict[str, Any], sessao: str = "") -> Dict[str, Any]:
    """Registra o que a leitura simples trouxe e acrescenta a dica ao resultado."""
    if not isinstance(resultado, dict) or not resultado.get("ok"):
        return resultado
    anotar_leitura(url, LER_PAGINA, TEXTO, sessao)
    anterior = dica(url, LER_PAGINA)
    vazia = len(str(resultado.get("texto") or "").strip()) < _TEXTO_MINIMO
    registrar(url, LER_PAGINA, not vazia, "voltou quase vazia" if vazia else "")
    if vazia:
        resultado["dica"] = ("a página voltou quase vazia: ela provavelmente monta com JavaScript; "
                             "use `browser` para ler")
    elif anterior:
        resultado["dica"] = anterior
    return resultado


def _leituras_do_navegador(arguments: Dict[str, Any], meta: Dict[str, Any]):
    """Os tipos de leitura que a acao (ou cada passo do roteiro) produziu."""
    acao = str((arguments or {}).get("acao") or "")
    if acao == "roteiro":
        passos = ((arguments or {}).get("argumentos") or {}).get("passos") or []
        return [_TIPO_DA_ACAO[str(p.get("acao"))] for p in passos
                if isinstance(p, dict) and str(p.get("acao")) in _TIPO_DA_ACAO]
    if meta.get("screenshot") is True:
        return [PRINT]
    return [_TIPO_DA_ACAO[acao]] if acao in _TIPO_DA_ACAO else []


def apos_browser(arguments: Dict[str, Any], resultado: Dict[str, Any], sessao: str = "") -> Dict[str, Any]:
    """Registra se o navegador chegou na pagina ou foi barrado."""
    if not isinstance(resultado, dict) or not resultado.get("executado"):
        return resultado
    obs = resultado.get("observation") or {}
    meta = obs.get("metadados") or {}
    url = (meta.get("url") or resultado.get("url")
           or ((arguments or {}).get("argumentos") or {}).get("url") or "")
    for tipo in _leituras_do_navegador(arguments, meta):
        anotar_leitura(url, BROWSER, tipo, sessao)
    if not origem(url):
        return resultado
    anterior = dica(url, BROWSER)
    bloqueio = meta.get("bloqueio")
    registrar(url, BROWSER, not bloqueio, str(bloqueio or ""))
    if anterior and bloqueio:
        resultado["dica"] = anterior
    return resultado


__all__ = [
    "BROWSER", "LER_PAGINA", "PRINT", "TEXTO", "anotar_leitura", "apos_browser", "apos_ler_pagina",
    "dica", "do_site", "origem", "registrar", "resumo_da_escada",
]
