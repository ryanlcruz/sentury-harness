"""Unidades de trabalho que sobrevivem ao processo morrer no meio.

O plano (`plano.py`) é o checklist que uma pessoa lê. Isto é a granularidade de
baixo: no case da vaga, cada `(vaga, fonte)` investigada é uma unidade, e um
dossiê de 5 vagas × 4 fontes são 20. Se o processo cai na 13ª, a volta começa
na 13ª, sem refazer as doze e sem duplicar nenhuma.

Três regras fazem a retomada funcionar:

- **A chave é do trabalho, não da execução.** `(alvo, item)` identifica a
  unidade; registrar de novo a mesma chave não cria outra.
- **`abrir` grava antes de agir.** Se gravasse só no fim, a unidade que morreu
  no meio sumia em vez de voltar como pendente. Ela volta com a tentativa
  contada, e a terceira que morre para de ser tentada e vai para revisão.
- **Cada `fechar` grava na hora.** Gravar no fim do lote perderia o lote.

O estado mora em `~/.sentury/missoes/<nome>.json`, fora do repositório, pelo
mesmo motivo do plano.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

PENDENTE = "pendente"
FAZENDO = "fazendo"
FEITO = "feito"
FALHOU = "falhou"
# A vaga não serve: é resultado bom, não falha.
DESCARTADA = "descartada"
REVISAR = "revisar"
PRECISA_USUARIO = "precisa_usuario"

ESTADOS = (PENDENTE, FAZENDO, FEITO, FALHOU, DESCARTADA, REVISAR, PRECISA_USUARIO)
# Fechadas não voltam para a fila; as outras voltam.
_FECHADOS = {FEITO, DESCARTADA, REVISAR}


def _casa() -> Path:
    return Path(os.environ.get("SENTURY_HOME") or (Path.home() / ".sentury"))


def _limpar(nome: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(nome or "").lower()).strip("-") or "missao"


def chave(alvo: str, item: str) -> str:
    return f"{str(alvo).strip()}::{str(item).strip()}"


class Missao:
    """Um lote de unidades com estado em disco."""

    def __init__(self, nome: str, *, raiz: Optional[Path] = None, max_tentativas: int = 3):
        self.nome = _limpar(nome)
        self.max_tentativas = max(1, int(max_tentativas))
        pasta = Path(raiz) if raiz else _casa() / "missoes"
        pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = pasta / f"{self.nome}.json"

    # ------------------------------------------------------------ disco

    def _ler(self) -> Dict[str, Any]:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            dados = {}
        dados.setdefault("unidades", {})
        return dados

    def _gravar(self, dados: Dict[str, Any]) -> None:
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.arquivo)

    # ------------------------------------------------------------ ciclo

    def registrar(self, unidades: Iterable[Tuple[str, str]]) -> int:
        """Põe na fila o que ainda não existe. Devolve quantas entraram."""
        with _LOCK:
            dados = self._ler()
            novas = 0
            for alvo, item in unidades:
                k = chave(alvo, item)
                if k in dados["unidades"]:
                    continue
                dados["unidades"][k] = {
                    "alvo": str(alvo), "item": str(item), "estado": PENDENTE,
                    "tentativas": 0, "evidencia": None, "confianca": None,
                    "nota": "", "ordem": len(dados["unidades"]), "updated_at": time.time(),
                }
                novas += 1
            self._gravar(dados)
            return novas

    def abrir(self, alvo: str, item: str, *, sessao: str = "") -> Optional[Dict[str, Any]]:
        """Marca a unidade como em curso ANTES de agir.

        None quando não há o que fazer: já fechada, ou esgotou as tentativas
        (aí ela vai para revisão em vez de morrer de novo).
        """
        with _LOCK:
            dados = self._ler()
            reg = dados["unidades"].get(chave(alvo, item))
            if reg is None or reg["estado"] in _FECHADOS:
                return None
            if reg["tentativas"] >= self.max_tentativas:
                reg.update(estado=REVISAR, updated_at=time.time(),
                           nota=f"{reg['tentativas']} tentativas sem fechar")
                self._gravar(dados)
                return None
            reg.update(estado=FAZENDO, tentativas=reg["tentativas"] + 1,
                       sessao=str(sessao or ""), updated_at=time.time())
            self._gravar(dados)
            return dict(reg)

    def fechar(
        self,
        alvo: str,
        item: str,
        estado: str = FEITO,
        *,
        evidencia: Any = None,
        confianca: Optional[float] = None,
        nota: str = "",
    ) -> Dict[str, Any]:
        if estado not in ESTADOS or estado in (PENDENTE, FAZENDO):
            raise ValueError(f"estado de fechamento invalido: {estado}")
        with _LOCK:
            dados = self._ler()
            reg = dados["unidades"].get(chave(alvo, item))
            if reg is None:
                raise KeyError(chave(alvo, item))
            reg.update(estado=estado, evidencia=evidencia, confianca=confianca,
                       nota=str(nota or "")[:500], updated_at=time.time())
            self._gravar(dados)
            return dict(reg)

    # ------------------------------------------------------------ leitura

    def unidades(self) -> List[Dict[str, Any]]:
        return sorted(self._ler()["unidades"].values(), key=lambda r: r["ordem"])

    def proximas(self) -> List[Dict[str, Any]]:
        """O que falta, na ordem em que entrou.

        `fazendo` entra aqui: se ninguém fechou, o processo que abriu morreu.
        """
        return [r for r in self.unidades() if r["estado"] not in _FECHADOS]

    def resumo(self) -> Dict[str, Any]:
        contagem: Dict[str, int] = {}
        for reg in self.unidades():
            contagem[reg["estado"]] = contagem.get(reg["estado"], 0) + 1
        return {"missao": self.nome, "total": sum(contagem.values()), "por_estado": contagem}


def listar(raiz: Optional[Path] = None) -> List[Dict[str, Any]]:
    """As missões desta máquina, com quanto falta em cada uma."""
    pasta = Path(raiz) if raiz else _casa() / "missoes"
    if not pasta.is_dir():
        return []
    saida = []
    for arquivo in sorted(pasta.glob("*.json")):
        missao = Missao(arquivo.stem, raiz=pasta)
        resumo = missao.resumo()
        resumo["faltam"] = len(missao.proximas())
        resumo["atualizada"] = max((u.get("updated_at") or 0 for u in missao.unidades()), default=0)
        saida.append(resumo)
    # A que mexeu por último primeiro: é a que a pessoa quer acompanhar.
    return sorted(saida, key=lambda m: m["atualizada"], reverse=True)


__all__ = [
    "DESCARTADA", "ESTADOS", "FALHOU", "FAZENDO", "FEITO", "Missao", "PENDENTE",
    "PRECISA_USUARIO", "REVISAR", "chave", "listar",
]
