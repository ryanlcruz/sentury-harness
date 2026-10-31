"""Onde os agentes moram: uma pasta por agente, com manifesto, memória e workspace."""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import manifesto as _m

_LOCK = threading.RLock()
# A memória é um acervo: o turno recebe só uma parte dela (`memoria.para_o_turno`), então
# este teto só protege o arquivo de crescer sem fim.
TETO_DA_MEMORIA = 200_000


def _pasta_dos_agentes() -> Path:
    pasta = _m.casa() / "agentes"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pasta_do(nome: str) -> Path:
    if not _m.NOME_VALIDO.match(str(nome or "")):
        raise _m.ManifestoInvalido(f"nome de agente inválido: '{nome}'")
    return _pasta_dos_agentes() / nome


def workspace_do(nome: str) -> Path:
    pasta = pasta_do(nome) / "workspace"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _gravar(manifesto: _m.Manifesto) -> _m.Manifesto:
    manifesto.atualizado_em = time.time()
    pasta = pasta_do(manifesto.nome)
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / "manifesto.json"
    tmp = alvo.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifesto.para_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(alvo)
    return manifesto


def carregar(nome: str) -> Optional[_m.Manifesto]:
    try:
        bruto = (pasta_do(nome) / "manifesto.json").read_text(encoding="utf-8")
        return _m.Manifesto.de_dict(json.loads(bruto))
    except (OSError, json.JSONDecodeError, _m.ManifestoInvalido):
        return None


def listar(*, com_aposentados: bool = False) -> List[_m.Manifesto]:
    achados = []
    for pasta in _pasta_dos_agentes().iterdir():
        agente = carregar(pasta.name) if pasta.is_dir() else None
        if agente and (com_aposentados or agente.estado != _m.APOSENTADO):
            achados.append(agente)
    return sorted(achados, key=lambda a: a.criado_em)


def criar(dados: Dict[str, Any], *, criado_por: str = "") -> _m.Manifesto:
    """Grava um agente novo. A aprovação da pessoa acontece antes de chegar aqui."""
    with _LOCK:
        manifesto = _m.validar({**dados, "estado": _m.DORMINDO})
        existente = carregar(manifesto.nome)
        if existente and existente.estado != _m.APOSENTADO:
            raise _m.ManifestoInvalido(f"já existe um agente chamado '{manifesto.nome}'")
        manifesto.criado_por = criado_por or manifesto.criado_por
        manifesto.criado_em = time.time()
        _gravar(manifesto)
        workspace_do(manifesto.nome)
        memoria = pasta_do(manifesto.nome) / "memoria.md"
        if not memoria.exists():
            memoria.write_text("", encoding="utf-8")
        return manifesto


def _exigir(nome: str) -> _m.Manifesto:
    agente = carregar(nome)
    if agente is None:
        raise _m.ManifestoInvalido(f"não existe agente '{nome}'")
    return agente


def mudar_estado(nome: str, estado: str) -> _m.Manifesto:
    if estado not in _m.ESTADOS:
        raise _m.ManifestoInvalido(f"estado '{estado}' não existe")
    with _LOCK:
        agente = _exigir(nome)
        if agente.estado == _m.APOSENTADO and estado != _m.APOSENTADO:
            raise _m.ManifestoInvalido(f"'{nome}' está aposentado")
        agente.estado = estado
        return _gravar(agente)


def pausar(nome: str) -> _m.Manifesto:
    return mudar_estado(nome, _m.PAUSADO)


def retomar(nome: str) -> _m.Manifesto:
    return mudar_estado(nome, _m.DORMINDO)


def aposentar(nome: str) -> _m.Manifesto:
    """O agente para de existir para a fila; a pasta fica, para consulta."""
    return mudar_estado(nome, _m.APOSENTADO)


# O que a pessoa edita depois de criado. Ferramentas ficam fora: ampliar o que
# o agente pode fazer passa pela fábrica, com o cartão.
EDITAVEIS = ("papel", "objetivo", "personalidade", "instrucoes", "orcamento", "cerebro", "canais",
             "autonomia", "rede")


def editar(nome: str, campos: Dict[str, Any]) -> _m.Manifesto:
    fora = [chave for chave in campos if chave not in EDITAVEIS]
    if fora:
        raise _m.ManifestoInvalido(f"não dá para editar {', '.join(fora)} aqui")
    with _LOCK:
        agente = _exigir(nome)
        novo = _m.validar({**agente.para_dict(), **campos})
        novo.criado_por, novo.criado_em = agente.criado_por, agente.criado_em
        return _gravar(novo)


def liberar_ferramenta(nome: str, ferramenta: str) -> _m.Manifesto:
    """A ferramenta que a pessoa liberou entra no manifesto, validada como as outras."""
    with _LOCK:
        agente = _exigir(nome)
        if ferramenta in agente.ferramentas:
            return agente
        novo = _m.validar({**agente.para_dict(), "ferramentas": [*agente.ferramentas, ferramenta]})
        novo.criado_por, novo.criado_em = agente.criado_por, agente.criado_em
        return _gravar(novo)


def trocar_acessorios(nome: str, acessorios: Any) -> _m.Manifesto:
    """O que a pessoa muda na aparência: só os acessórios."""
    from . import aparencia as _aparencia

    with _LOCK:
        agente = _exigir(nome)
        try:
            agente.aparencia = _aparencia.trocar_acessorios(agente.aparencia, acessorios)
        except _aparencia.AparenciaInvalida as exc:
            raise _m.ManifestoInvalido(str(exc)) from None
        return _gravar(agente)


def apagar(nome: str) -> None:
    """Some com a pasta. Só para teste e para quem pediu de propósito."""
    with _LOCK:
        shutil.rmtree(pasta_do(nome), ignore_errors=True)


def ler_memoria(nome: str) -> str:
    try:
        return (pasta_do(nome) / "memoria.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def anotar_memoria(nome: str, nota: str, substitui: str = "") -> str:
    """Acrescenta uma nota; acima do teto, as mais antigas saem. Com `substitui`, a
    nota troca as anteriores que começam assim, para o mesmo assunto não se repetir."""
    # Uma nota por linha: é a linha que a busca e a troca da nota repetida enxergam.
    nota = " ".join(str(nota or "").split())
    if not nota:
        return ler_memoria(nome)
    with _LOCK:
        _exigir(nome)
        atual = ler_memoria(nome).rstrip()
        if substitui:
            atual = "\n".join(l for l in atual.split("\n")
                              if not l.split(": ", 1)[-1].startswith(substitui)).strip()
        linha = f"- {time.strftime('%Y-%m-%d')}: {nota}"
        novo = f"{atual}\n{linha}".strip() if atual else linha
        while len(novo) > TETO_DA_MEMORIA and "\n" in novo:
            novo = novo.split("\n", 1)[1]
        (pasta_do(nome) / "memoria.md").write_text(novo + "\n", encoding="utf-8")
        return novo
