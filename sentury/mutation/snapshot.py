"""Guarda cópias de arquivos pelo hash de seu conteúdo.

O snapshot preserva a versão anterior mesmo se a worktree desaparecer. Arquivos
idênticos compartilham a mesma cópia, e gravar o mesmo conteúdo é idempotente.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Fora do repositório, pela mesma razão das cópias: um snapshot dentro dele
# apareceria no `git status` e viajaria no deploy.
PASTA = "snapshots"


def pasta_dos_snapshots() -> Path:
    casa = os.environ.get("SENTURY_HOME") or str(Path.home() / ".sentury")
    return Path(casa) / PASTA


def _hash_do_conteudo(dados: bytes) -> str:
    # Curto o bastante para ler num log, longo o bastante para não colidir
    # numa base de código. É a mesma escolha do git com o hash abreviado.
    return hashlib.sha256(dados).hexdigest()[:16]


def guardar(arquivo: str | Path, *, mutacao_id: str = "", nota: str = "") -> Dict[str, Any]:
    """Guarda o conteúdo atual do arquivo e devolve o hash.

    Gravar o mesmo conteúdo de novo não cria nada: o hash já existe, e o que
    volta é ele. Quem chama não precisa saber se é a primeira vez.
    """
    origem = Path(arquivo)
    if not origem.is_file():
        return {"ok": False, "erro": f"nao e um arquivo: {origem}"}
    try:
        dados = origem.read_bytes()
    except OSError as exc:
        return {"ok": False, "erro": str(exc)}

    digest = _hash_do_conteudo(dados)
    destino = pasta_dos_snapshots() / digest
    try:
        destino.mkdir(parents=True, exist_ok=True)
        alvo = destino / "conteudo"
        if not alvo.exists():
            alvo.write_bytes(dados)
        # O manifesto diz de ONDE veio. O conteúdo é compartilhado entre
        # arquivos iguais, então a procedência tem que ficar do lado de fora
        # dele: senão dois arquivos idênticos brigariam pelo mesmo registro.
        manifesto = destino / "de.jsonl"
        with manifesto.open("a", encoding="utf-8") as saida:
            saida.write(json.dumps({
                "caminho": str(origem.resolve()),
                "mutacao": mutacao_id,
                "nota": nota[:200],
                "em": time.time(),
                "bytes": len(dados),
            }, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Nao consegui guardar o snapshot de %s: %s", origem, exc)
        return {"ok": False, "erro": str(exc)}

    return {"ok": True, "hash": digest, "bytes": len(dados), "caminho": str(origem)}


def ler(digest: str) -> Optional[bytes]:
    """O conteúdo exato de um snapshot. `None` se não existe."""
    alvo = pasta_dos_snapshots() / str(digest or "").strip() / "conteudo"
    try:
        return alvo.read_bytes()
    except OSError:
        return None


def procedencia(digest: str) -> List[Dict[str, Any]]:
    """De onde este conteúdo veio, e quantas vezes. Um mesmo hash pode ter
    vindo de arquivos diferentes: é conteúdo igual, não o mesmo arquivo."""
    alvo = pasta_dos_snapshots() / str(digest or "").strip() / "de.jsonl"
    saida: List[Dict[str, Any]] = []
    try:
        for linha in alvo.read_text(encoding="utf-8").splitlines():
            try:
                saida.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return saida


def restaurar(digest: str, destino: str | Path, *, guardar_o_atual: bool = True) -> Dict[str, Any]:
    """Escreve o snapshot de volta no caminho dado.

    Guarda o conteúdo atual antes, por padrão: desfazer não pode ser uma porta
    de mão única: se a restauração foi um engano, o que estava lá ainda existe.
    """
    dados = ler(digest)
    if dados is None:
        return {"ok": False, "erro": f"snapshot {digest} nao existe"}

    alvo = Path(destino)
    anterior = ""
    if guardar_o_atual and alvo.is_file():
        guardado = guardar(alvo, nota=f"antes de restaurar {digest}")
        anterior = guardado.get("hash", "")

    try:
        alvo.parent.mkdir(parents=True, exist_ok=True)
        temporario = alvo.with_name(f".{alvo.name}.restaurando")
        temporario.write_bytes(dados)
        temporario.replace(alvo)   # troca atômica: nunca fica pela metade
    except OSError as exc:
        return {"ok": False, "erro": str(exc)}

    return {"ok": True, "hash": digest, "destino": str(alvo), "anterior": anterior}


def guardar_muitos(arquivos: List[str], *, mutacao_id: str = "", nota: str = "") -> Dict[str, Any]:
    """O conjunto tocado por uma mutação, de uma vez.

    Devolve caminho → hash: é esse mapa que permite voltar arquivo por arquivo
    em vez de reverter o trabalho inteiro.
    """
    mapa: Dict[str, str] = {}
    falhas: Dict[str, str] = {}
    for caminho in arquivos:
        resultado = guardar(caminho, mutacao_id=mutacao_id, nota=nota)
        if resultado.get("ok"):
            mapa[str(caminho)] = resultado["hash"]
        else:
            falhas[str(caminho)] = resultado.get("erro", "")
    return {"ok": not falhas, "hashes": mapa, "falhas": falhas}


def esquecer(digest: str) -> bool:
    alvo = pasta_dos_snapshots() / str(digest or "").strip()
    try:
        shutil.rmtree(alvo)
        return True
    except OSError:
        return False


def inventario() -> List[Dict[str, Any]]:
    """O que está guardado. Serve para o painel e para achar o que podar."""
    base = pasta_dos_snapshots()
    if not base.is_dir():
        return []
    saida = []
    for pasta in sorted(base.iterdir()):
        conteudo = pasta / "conteudo"
        if not conteudo.is_file():
            continue
        vindos = procedencia(pasta.name)
        saida.append({
            "hash": pasta.name,
            "bytes": conteudo.stat().st_size,
            "vezes": len(vindos),
            "ultimo_caminho": vindos[-1]["caminho"] if vindos else "",
            "mutacoes": sorted({v.get("mutacao", "") for v in vindos if v.get("mutacao")}),
        })
    return saida


__all__ = [
    "esquecer", "guardar", "guardar_muitos", "inventario",
    "ler", "pasta_dos_snapshots", "procedencia", "restaurar",
]
