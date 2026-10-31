"""As decisões da equipe, uma por arquivo `.md`, lembradas por quem precisa.

Um assunto da Mesa fecha com um resumo, e o resumo vira um arquivo em
`<casa do Sentury>/decisoes/`, com data e tema no nome. O assunto reaberto e
fechado de novo atualiza o mesmo arquivo: vale o que se decidiu por último.

Não há índice separado para manter: as linhas que entram no turno são montadas
a partir do cabeçalho de cada arquivo. No turno vai uma linha por decisão, com o
caminho; o texto inteiro se lê quando faz falta. O Sentury principal recebe as
recentes e as antigas parecidas com o pedido. O residente recebe só as decisões
em que esteve: quem lembra conta aos colegas, como faria uma pessoa.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PASTA = "decisoes"
DIAS_RECENTES = 60
QUANTAS_RECENTES = 5
QUANTAS_RELACIONADAS = 3
# O que entra em todo turno tem teto fixo: a seção não cresce com o acervo.
TETO_DA_SECAO = 1_500
TETO_DA_LINHA = 150
# A busca devolve a decisão inteira até este teto; o arquivo tem o resto.
TETO_DO_RESUMO_BUSCADO = 1_500

_LOCK = threading.Lock()
_CABECALHO = re.compile(r"^---\n(.*?)\n---\n", re.S)


def pasta() -> Path:
    from ..tools.arquivos import casa_do_sentury

    return casa_do_sentury() / PASTA


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")[:60] or "decisao"


def _ler(arquivo: Path) -> Optional[Dict[str, Any]]:
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except OSError:
        return None
    cabeca = _CABECALHO.match(texto)
    if not cabeca:
        return None
    campos = dict(linha.split(": ", 1) for linha in cabeca.group(1).splitlines() if ": " in linha)
    corpo = texto[cabeca.end():]
    resumo = corpo.split("\n## ", 1)[0]
    resumo = re.sub(r"^# .*\n", "", resumo.strip()).strip()
    return {
        "titulo": campos.get("titulo", arquivo.stem), "origem": campos.get("origem", ""),
        "participantes": [p for p in campos.get("participantes", "").split(", ") if p],
        "em": float(campos.get("em") or arquivo.stat().st_mtime), "resumo": resumo, "caminho": str(arquivo),
    }


def listar() -> List[Dict[str, Any]]:
    """Todas as decisões, da mais nova para a mais antiga."""
    if not pasta().is_dir():
        return []
    achadas = [d for d in (_ler(a) for a in pasta().glob("*.md")) if d]
    return sorted(achadas, key=lambda d: d["em"], reverse=True)


def apagar(origem: str) -> bool:
    """Apaga a decisão que saiu desta origem; False quando não havia."""
    with _LOCK:
        achada = next((Path(d["caminho"]) for d in listar() if d["origem"] == origem), None)
        if achada is None:
            return False
        achada.unlink(missing_ok=True)
        return True


def registrar(origem: str, titulo: str, resumo: str, participantes: List[str],
              em: Optional[float] = None) -> Path:
    """Grava a decisão no arquivo dela; a mesma origem reescreve o arquivo que já existe."""
    em = em or time.time()
    nomes = sorted({p for p in participantes if p})
    with _LOCK:
        destino = pasta()
        destino.mkdir(parents=True, exist_ok=True)
        existente = next((Path(d["caminho"]) for d in listar() if d["origem"] == origem), None)
        if existente is None:
            base = f"{datetime.fromtimestamp(em):%Y-%m-%d}-{_slug(titulo)}"
            existente, n = destino / f"{base}.md", 2
            while existente.exists():
                existente, n = destino / f"{base}-{n}.md", n + 1
        assunto = origem.split(":", 1)[1] if ":" in origem else origem
        texto = (
            "---\n"
            f"titulo: {' '.join(str(titulo).split())}\n"
            f"data: {datetime.fromtimestamp(em):%Y-%m-%d}\n"
            f"origem: {origem}\n"
            f"participantes: {', '.join(nomes)}\n"
            f"em: {em}\n"
            "---\n\n"
            f"# {titulo}\n\n{str(resumo).strip()}\n\n"
            f"## De onde veio\n\nDecidido na Mesa (assunto {assunto}). Para mudar, reabra o assunto e "
            "feche de novo: este arquivo é reescrito com a decisão nova.\n"
        )
        tmp = existente.with_suffix(".tmp")
        tmp.write_text(texto, encoding="utf-8")
        tmp.replace(existente)
    return existente


def _linha(decisao: Dict[str, Any]) -> str:
    quando = datetime.fromtimestamp(decisao["em"]).strftime("%d/%m/%Y")
    essencial = " ".join(decisao["resumo"].split())
    if len(essencial) > TETO_DA_LINHA:
        essencial = essencial[:TETO_DA_LINHA].rsplit(" ", 1)[0] + "…"
    return f"- {quando} · {decisao['titulo']}: {essencial} (`{decisao['caminho']}`)"


def _parecidas(texto: str, acervo: Dict[str, str], limite: int, minimo_comuns: int = 2) -> List[str]:
    from .semelhanca import parecidas

    return parecidas(texto, acervo, limite, minimo_comuns=minimo_comuns)


def para_o_turno(pedido: str, agente: str = "", agora: Optional[float] = None) -> Optional[str]:
    """A seção de decisões do turno, ou None. `agente` restringe às decisões em que ele esteve."""
    todas = [d for d in listar() if not agente or agente in d["participantes"]]
    if not todas:
        return None
    agora = time.time() if agora is None else agora
    recentes = [d for d in todas if d["em"] >= agora - DIAS_RECENTES * 86400][:QUANTAS_RECENTES]
    vistas = {d["caminho"] for d in recentes}
    antigas = {d["caminho"]: f"{d['titulo']} {d['resumo']}" for d in todas if d["caminho"] not in vistas}
    relacionadas = []
    if pedido and antigas:
        por_caminho = {d["caminho"]: d for d in todas}
        relacionadas = [por_caminho[c] for c in _parecidas(pedido, antigas, QUANTAS_RELACIONADAS)]
    linhas, usado = [], 0
    for decisao in relacionadas + recentes:
        linha = _linha(decisao)
        if usado + len(linha) > TETO_DA_SECAO:
            break
        linhas.append(linha)
        usado += len(linha)
    if not linhas:
        return None
    if agente:
        rodape = ("Decisões em que você esteve. Se um pedido mexe numa delas, considere o que foi decidido; "
                  "se um colega que não estava precisa saber, conte a ele.")
    else:
        rodape = ("Decisões já tomadas pela equipe. Se o pedido mexe numa delas, considere o que foi decidido "
                  "e diga a relação; o texto inteiro está no arquivo de cada linha.")
    return "\n".join(["### DECISÕES ANTERIORES", *linhas, rodape])


def agora_id() -> str:
    """Identifica a decisão anotada fora da Mesa: cada anotação é um arquivo novo."""
    return str(int(time.time() * 1000))


def buscar(termo: str, agente: str = "", limite: int = 5) -> List[Dict[str, Any]]:
    """As decisões parecidas com o termo, para quando a do contexto não basta.
    Sem termo, as mais recentes."""
    todas = [d for d in listar() if not agente or agente in d["participantes"]]
    if str(termo or "").strip():
        por_caminho = {d["caminho"]: d for d in todas}
        acervo = {d["caminho"]: f"{d['titulo']} {d['resumo']}" for d in todas}
        escolhidas = [por_caminho[c] for c in _parecidas(termo, acervo, limite, minimo_comuns=1)]
    else:
        escolhidas = todas[:limite]
    return [{"titulo": d["titulo"], "data": datetime.fromtimestamp(d["em"]).strftime("%d/%m/%Y"),
             "participantes": d["participantes"], "decisao": d["resumo"][:TETO_DO_RESUMO_BUSCADO],
             "arquivo": d["caminho"]} for d in escolhidas]
