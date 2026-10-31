"""A aparência do residente: o Sentury monta, a pessoa troca os acessórios.

Cada coruja sai do nome: a plumagem e um acessório extra são sorteados por ele,
então cada residente tem a sua cara e ela não muda entre uma abertura e outra.
A família, que vem do papel, entra só com o objeto-símbolo. O que o Sentury
escolheu fica guardado em `sugeridos`, para o "voltar aos do Sentury".
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

GERAL = "geral"


class AparenciaInvalida(ValueError):
    pass


@lru_cache(maxsize=1)
def catalogo() -> Dict[str, Any]:
    with open(Path(__file__).with_name("aparencia.yaml"), encoding="utf-8") as arquivo:
        return yaml.safe_load(arquivo)


def familias() -> Dict[str, Any]:
    return catalogo()["familias"]


def _sorteio(nome: str, sal: str, opcoes: List[str]) -> str:
    """Sorteio estável: o mesmo nome dá sempre a mesma escolha."""
    numero = int(hashlib.sha256(f"{sal}:{nome}".encode("utf-8")).hexdigest(), 16)
    return opcoes[numero % len(opcoes)]


def _sugeridos(nome: str, familia: str) -> Dict[str, str]:
    """O símbolo da família e, às vezes, um extra num encaixe livre."""
    escolha = dict(familias().get(familia, {}).get("simbolo") or {})
    # O símbolo de outra família não vira enfeite: lupa é pesquisa, capacete é infraestrutura.
    simbolos = {peca for dados in familias().values() for peca in (dados.get("simbolo") or {}).values()}
    livres = [(encaixe, peca) for encaixe, pecas in catalogo()["encaixes"].items()
              if encaixe not in escolha for peca in pecas if peca not in simbolos]
    # Um em cada três fica só com o símbolo: nem toda coruja anda enfeitada.
    if livres and _sorteio(nome, "extra", ["nao", "sim", "sim"]) == "sim":
        encaixe, peca = _sorteio(nome, "peca", [f"{e}:{p}" for e, p in livres]).split(":")
        escolha[encaixe] = peca
    return escolha


def validar_acessorios(acessorios: Any) -> Dict[str, str]:
    if acessorios in (None, ""):
        return {}
    if not isinstance(acessorios, dict):
        raise AparenciaInvalida("acessórios vão como {encaixe: peça}")
    encaixes = catalogo()["encaixes"]
    limpos: Dict[str, str] = {}
    for encaixe, peca in acessorios.items():
        if encaixe not in encaixes:
            raise AparenciaInvalida(f"encaixe '{encaixe}' não existe: use {', '.join(encaixes)}")
        peca = str(peca or "").strip()
        if not peca:
            continue
        if peca not in encaixes[encaixe]:
            raise AparenciaInvalida(f"'{peca}' não cabe em {encaixe}: use {', '.join(encaixes[encaixe])}")
        limpos[encaixe] = peca
    return limpos


def montar(nome: str, familia: str = "", acessorios: Any = None) -> Dict[str, Any]:
    """A aparência que o Sentury dá. Acessórios passados substituem os sugeridos.

    Família fora do catálogo vira `geral`: ela só decide o símbolo, e o modelo
    que inventou "monitoramento" não deve perder a criação por isso.
    """
    familia = str(familia or "").strip().lower() or GERAL
    if familia not in familias():
        familia = GERAL
    sugeridos = _sugeridos(nome, familia)
    return {
        "familia": familia,
        "plumagem": _sorteio(nome, "plumagem", sorted(catalogo()["plumagens"])),
        "sugeridos": sugeridos,
        "acessorios": dict(sugeridos) if acessorios is None else validar_acessorios(acessorios),
    }


def trocar_acessorios(aparencia: Dict[str, Any], acessorios: Any) -> Dict[str, Any]:
    """A pessoa só mexe aqui: família, plumagem e sugeridos ficam."""
    return {**aparencia, "acessorios": validar_acessorios(acessorios)}


def cores(aparencia: Dict[str, Any]) -> Dict[str, str]:
    return dict(catalogo()["plumagens"].get(aparencia.get("plumagem"), {}))
