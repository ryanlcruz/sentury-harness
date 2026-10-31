"""A memória da pessoa em arquivos .md, um fato por arquivo.

Cada arquivo traz nome, uma linha de descrição, tipo (pessoa, decisao,
projeto, referencia), de que conversa veio e o texto. O índice `MEMORIA.md` é
refeito a cada escrita: é ele que a pessoa abre para ver tudo, e é a lista que
entra no turno; o texto inteiro de um item se lê pela ferramenta `memoria`.

Arquivo não expira. Memória que envelheceu se corrige ou se apaga, e a idade
vai junto para o modelo pesar. O que estava no backend de sessão é trazido uma
vez, na primeira leitura.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

TIPOS = ("pessoa", "decisao", "projeto", "referencia")
INDICE = "MEMORIA.md"
_MAX_TEXTO = 2000
_MARCA_DE_MIGRACAO = ".migrada"


def _slug(texto: str, limite: int = 48) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:limite].strip("-")


def _uma_linha(texto: str, limite: int = 120) -> str:
    linha = " ".join(str(texto or "").split())
    return linha if len(linha) <= limite else linha[: limite - 1].rstrip() + "…"


class MemoriaEmArquivos:
    """Mesmo contrato do armazenamento antigo (`all`, `remember`, `forget`,
    `remove`, `remove_texto`), mais `ler` e o tipo de cada item."""

    def __init__(self, raiz: Optional[Path] = None, legado: Any = None):
        self._raiz = Path(raiz) if raiz else None
        self._legado = legado

    def _base(self) -> Path:
        if self._raiz is not None:
            return self._raiz
        from ..tools.arquivos import casa_do_sentury

        return casa_do_sentury() / "memoria"

    def _pasta(self, user_id: str) -> Path:
        return self._base() / (_slug(user_id) or "pessoa")

    # ------------------------------------------------------------ leitura

    def _ler_arquivo(self, caminho: Path) -> Optional[Dict[str, Any]]:
        from ..skills.skill_loader import parse_frontmatter

        try:
            meta, corpo = parse_frontmatter(caminho.read_text(encoding="utf-8"))
        except OSError:
            return None
        texto = corpo.strip()
        if not texto:
            return None
        return {
            "id": int(meta.get("id") or 0),
            "nome": caminho.stem,
            "texto": texto,
            "descricao": str(meta.get("descricao") or _uma_linha(texto)),
            "tipo": str(meta.get("tipo") or "pessoa"),
            "ts": float(meta.get("ts") or caminho.stat().st_mtime),
            **({"sessao": str(meta["sessao"])} if meta.get("sessao") else {}),
        }

    async def _migrar(self, user_id: str, pasta: Path) -> None:
        if self._legado is None or (pasta / _MARCA_DE_MIGRACAO).exists():
            return
        pasta.mkdir(parents=True, exist_ok=True)
        try:
            antigas = await self._legado.all(user_id)
        except Exception:
            antigas = []
        (pasta / _MARCA_DE_MIGRACAO).write_text("", encoding="utf-8")
        for m in antigas:
            texto = str(m.get("texto") or "").strip()
            if texto:
                self._escrever(pasta, texto, sessao=m.get("sessao"), ts=m.get("ts"))
        if antigas:
            self._refazer_indice(pasta)

    async def all(self, user_id: str) -> List[Dict[str, Any]]:
        pasta = self._pasta(user_id)
        await self._migrar(user_id, pasta)
        if not pasta.is_dir():
            return []
        itens = [i for i in (self._ler_arquivo(p) for p in pasta.glob("*.md") if p.name != INDICE) if i]
        return sorted(itens, key=lambda i: (i["ts"], i["id"]))

    async def ler(self, user_id: str, nome: str) -> Optional[Dict[str, Any]]:
        alvo = self._pasta(user_id) / f"{_slug(nome)}.md"
        return self._ler_arquivo(alvo) if alvo.is_file() else None

    # ------------------------------------------------------------ escrita

    def _proximo_id(self, pasta: Path) -> int:
        contador = pasta / ".ultimo_id"
        try:
            ultimo = int(contador.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            ultimo = 0
        contador.write_text(str(ultimo + 1), encoding="utf-8")
        return ultimo + 1

    def _escrever(self, pasta: Path, texto: str, *, nome: str = "", descricao: str = "",
                  tipo: str = "pessoa", sessao: Optional[str] = None, ts: Any = None,
                  id_: Optional[int] = None) -> Path:
        pasta.mkdir(parents=True, exist_ok=True)
        base = _slug(nome or texto, 40) or "memoria"
        alvo = pasta / f"{base}.md"
        if not nome:
            n = 2
            while alvo.exists():
                alvo = pasta / f"{base}-{n}.md"
                n += 1
        tipo = tipo if tipo in TIPOS else "pessoa"
        linhas = [
            "---",
            f"id: {id_ if id_ is not None else self._proximo_id(pasta)}",
            "descricao: " + json.dumps(_uma_linha(descricao or texto), ensure_ascii=False),
            f"tipo: {tipo}",
            f"ts: {float(ts) if ts else time.time()}",
        ]
        if sessao:
            linhas.append("sessao: " + json.dumps(str(sessao), ensure_ascii=False))
        linhas += ["---", "", str(texto).strip()[:_MAX_TEXTO], ""]
        alvo.write_text("\n".join(linhas), encoding="utf-8")
        return alvo

    def _refazer_indice(self, pasta: Path) -> None:
        itens = sorted((i for i in (self._ler_arquivo(p) for p in pasta.glob("*.md") if p.name != INDICE) if i),
                       key=lambda i: (i["tipo"], i["nome"]))
        linhas = ["# Memória", ""] + [f"- [{i['descricao']}]({i['nome']}.md) · {i['tipo']}" for i in itens]
        (pasta / INDICE).write_text("\n".join(linhas) + "\n", encoding="utf-8")

    async def parecido(self, user_id: str, texto: str) -> Optional[Dict[str, Any]]:
        """O item guardado sobre quase o mesmo assunto, se houver (memory/semelhanca.py)."""
        from .semelhanca import semelhantes

        itens = {i["nome"]: i for i in await self.all(user_id)}
        achados = semelhantes(texto, {n: i["texto"] for n, i in itens.items()}, corte=0.5, limite=1)
        return itens[achados[0][0]] if achados else None

    async def remember(self, user_id: str, texto: str, sessao: Optional[str] = None, *,
                       tipo: str = "pessoa", nome: str = "", descricao: str = "") -> bool:
        """Guarda um fato. Com `nome` de um item existente, atualiza esse item;
        com nome novo, guarda mesmo havendo parecido; sem nome, recusa o que já
        está guardado sobre o mesmo assunto."""
        texto = str(texto or "").strip()
        if not texto:
            return False
        pasta = self._pasta(user_id)
        await self._migrar(user_id, pasta)
        existentes = await self.all(user_id)
        if nome:
            atual = next((i for i in existentes if i["nome"] == _slug(nome, 40)), None)
            if atual is not None:
                if atual["texto"] == texto and (not descricao or descricao == atual["descricao"]):
                    return False
                self._escrever(pasta, texto, nome=atual["nome"], descricao=descricao, tipo=tipo,
                               sessao=sessao or atual.get("sessao"), id_=atual["id"])
                self._refazer_indice(pasta)
                return True
        if any(i["texto"].lower() == texto.lower() for i in existentes):
            return False
        if not nome and await self.parecido(user_id, texto) is not None:
            return False
        self._escrever(pasta, texto, nome=nome, descricao=descricao, tipo=tipo, sessao=sessao)
        self._refazer_indice(pasta)
        return True

    async def _apagar(self, user_id: str, alvos: List[Dict[str, Any]]) -> int:
        pasta = self._pasta(user_id)
        for i in alvos:
            (pasta / f"{i['nome']}.md").unlink(missing_ok=True)
        if alvos:
            self._refazer_indice(pasta)
        return len(alvos)

    async def forget(self, user_id: str, termo: Optional[str] = None) -> int:
        itens = await self.all(user_id)
        if termo:
            t = termo.lower()
            itens = [i for i in itens if t in i["texto"].lower() or t in i["nome"]]
        return await self._apagar(user_id, itens)

    async def remove_texto(self, user_id: str, texto: str) -> bool:
        alvo = str(texto or "").strip().lower()
        itens = [i for i in await self.all(user_id) if i["texto"].strip().lower() == alvo]
        return bool(alvo) and await self._apagar(user_id, itens) > 0

    async def remove(self, user_id: str, mem_id: int) -> bool:
        itens = [i for i in await self.all(user_id) if i["id"] == int(mem_id)]
        return await self._apagar(user_id, itens) > 0


def idade(ts: Any) -> str:
    if not ts:
        return ""
    try:
        dias = max(0, (datetime.now() - datetime.fromtimestamp(float(ts))).days)
    except (TypeError, ValueError, OSError):
        return ""
    return "hoje" if dias == 0 else "ontem" if dias == 1 else f"há {dias} dias"
