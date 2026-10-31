"""Quais ferramentas vão em cada chamada ao modelo.

Duas formas. Enquanto o catálogo inteiro cabe no teto de tokens, ele vai todo:
carregar no meio do turno é um passo a mais em que o modelo erra. Acima do teto,
vai o núcleo, o mapa e o que a busca achou, e o resto entra pelo `search_tools`
ou pela ponte, que chama pelo nome sem a lista mudar. Em nenhuma das formas
carregar autoriza ou executa: isso continua com a policy e o dispatcher.
"""
from __future__ import annotations

import json
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..tools.capability_catalog import build_catalog, render_manifest, render_matches, search_catalog
from ..tools.registry import TOOL_REGISTRY


@dataclass
class _Turno:
    carregadas: set[str] = field(default_factory=set)
    oferecidas: set[str] | None = None
    # O catálogo inteiro foi recusado por tamanho neste turno: segue sob demanda.
    forcada: bool = False


_TURNO: ContextVar[_Turno | None] = ContextVar("descoberta_do_turno", default=None)


def abrir() -> Token:
    return _TURNO.set(_Turno())


def fechar(token: Token) -> None:
    _TURNO.reset(token)


def carregar(nome: str) -> None:
    """Deixa uma ferramenta pronta para as próximas chamadas do turno."""
    turno = _TURNO.get()
    if turno is not None and nome in TOOL_REGISTRY:
        turno.carregadas.add(nome)


def nomes_da_chamada(fallback: set[str]) -> set[str] | None:
    turno = _TURNO.get()
    if turno is None:
        return set(fallback)
    return set(turno.oferecidas) if turno.oferecidas is not None else None


def _pontes() -> set[str]:
    return {nome for nome, meta in TOOL_REGISTRY.items() if meta.get("ponte")}


def _do_catalogo(state: Any) -> set[str]:
    funcoes = getattr(state, "funcoes_ativas", None) or ()
    return {entry.name for entry in build_catalog(TOOL_REGISTRY, funcoes=funcoes) if entry.kind == "tool"} - _pontes()


def sob_demanda(state: Any) -> bool:
    """A carga sob demanda vale nesta volta: o catálogo inteiro passa do teto,
    ou já foi recusado por tamanho neste turno."""
    from ..config import settings
    from ..llm.tool_schemas import build_tool_schemas

    turno = _TURNO.get()
    if turno is not None and turno.forcada:
        return True
    teto = int(getattr(settings, "SENTURY_FERRAMENTAS_TETO_TOKENS", 20000) or 0)
    esquemas = build_tool_schemas(_do_catalogo(state), com_orientacao=True)
    return len(json.dumps(esquemas, ensure_ascii=False)) // 4 > teto


def inteiro(state: Any) -> set[str]:
    """O catálogo inteiro na chamada, inclusive o que uma função do `@` ligou."""
    nomes = _do_catalogo(state)
    turno = _TURNO.get()
    if turno is not None:
        turno.oferecidas = set(nomes)
    return nomes


def forcada() -> bool:
    turno = _TURNO.get()
    return bool(turno is not None and turno.forcada)


def passar_para_sob_demanda() -> bool:
    """O pedido com o catálogo inteiro não coube na janela do modelo: o resto do
    turno segue sob demanda. Devolve se mudou, para quem chamou remontar e tentar."""
    turno = _TURNO.get()
    if turno is None or turno.forcada or turno.oferecidas is None:
        return False
    from ..tools.registry import do_nucleo

    if not (turno.oferecidas - do_nucleo()):
        return False
    turno.forcada = True
    return True


def desembrulhar(passo: Any) -> Any:
    """A chamada pela ponte vira a chamada da ferramenta de dentro antes da
    policy: permissão, cartão e tela veem a ferramenta de verdade. A de dentro
    fica carregada, e o histórico passa a citar uma ferramenta que está na lista."""
    if not isinstance(passo, dict) or str(passo.get("tool") or "") not in _pontes():
        return passo
    from ..llm.tool_schemas import _nome_limpo

    argumentos = passo.get("arguments") if isinstance(passo.get("arguments"), dict) else {}
    nome = _nome_limpo(str(argumentos.get("nome") or ""))
    de_dentro = argumentos.get("argumentos")
    if isinstance(de_dentro, str):
        try:
            de_dentro = json.loads(de_dentro)
        except ValueError:
            de_dentro = None
    if not nome or nome in _pontes():
        return passo
    carregar(nome)
    return {**passo, "tool": nome, "arguments": de_dentro if isinstance(de_dentro, dict) else {}}


def preparar(state: Any, mensagem: str, skills: Iterable[Any]):
    """Revalida o catálogo vivo, incluindo o que o modelo já carregou."""
    from .funcoes import ferramentas_ligadas

    funcoes = getattr(state, "funcoes_ativas", None) or ()
    catalogo = build_catalog(TOOL_REGISTRY, skills, funcoes=funcoes)
    matches = search_catalog(catalogo, mensagem, limit=3)
    permitidas = {entry.name for entry in catalogo if entry.kind == "tool"}
    nomes = {entry.name for entry, _ in matches if entry.kind == "tool"}
    nomes |= ferramentas_ligadas(funcoes) & permitidas
    # Sob demanda, a ponte chama o que o mapa mostra sem esperar outra volta.
    nomes |= _pontes()
    turno = _TURNO.get()
    if turno is not None:
        turno.carregadas.intersection_update(permitidas)
        nomes |= turno.carregadas
        turno.oferecidas = nomes
    return ([entry.public_dict(score) for entry, score in matches], nomes,
            render_manifest(catalogo), render_matches(matches))


def consultar(state: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """Busca/lista ferramentas ou carrega pelo nome exato, sem executar."""
    from ..llm.tool_schemas import build_tool_schemas

    catalogo = build_catalog(TOOL_REGISTRY, funcoes=getattr(state, "funcoes_ativas", None) or ())
    por_nome = {entry.name: entry for entry in catalogo}
    nomes = arguments.get("nomes") or []
    if isinstance(nomes, str):
        nomes = [nomes]
    if not isinstance(nomes, list) or any(not isinstance(nome, str) for nome in nomes):
        return {"erro": "nomes deve ser uma lista de nomes exatos do mapa de capacidades"}
    if len(nomes) > 8:
        return {"erro": "carregue no máximo 8 ferramentas por chamada"}
    consulta = str(arguments.get("consulta") or arguments.get("query") or arguments.get("q") or "").strip()
    categoria = str(arguments.get("categoria") or "").strip()
    if nomes:
        selecionadas = [por_nome[nome] for nome in dict.fromkeys(nomes) if nome in por_nome]
        resultado = {"achadas": [entry.public_dict() for entry in selecionadas],
                     "nao_encontradas": [nome for nome in dict.fromkeys(nomes) if nome not in por_nome]}
    elif consulta:
        matches = search_catalog(catalogo, consulta, limit=8)
        selecionadas = [entry for entry, _ in matches]
        resultado = {"consulta": consulta, "achadas": [entry.public_dict(score) for entry, score in matches]}
        if not selecionadas:
            resultado["catalogo"] = render_manifest(catalogo)
    else:
        try:
            offset = int(arguments.get("offset") or 0)
        except (ValueError, TypeError, OverflowError):
            return {"erro": "offset deve ser um inteiro não negativo"}
        if offset < 0:
            return {"erro": "offset deve ser um inteiro não negativo"}
        entradas = sorted((entry for entry in catalogo if not categoria or entry.category == categoria),
                          key=lambda entry: entry.name)
        pagina = entradas[offset:offset + 20]
        return {"categoria": categoria or None, "total": len(entradas),
                "achadas": [entry.public_dict() for entry in pagina],
                "proximo_offset": offset + len(pagina) if offset + len(pagina) < len(entradas) else None,
                "como_usar": "Escolha pelo que precisa fazer e carregue com search_tools(nomes=[nome_exato])."}
    carregadas = {entry.name for entry in selecionadas}
    schemas = build_tool_schemas(carregadas, com_orientacao=True)
    resultado["schemas"] = [schema for schema in schemas if schema["function"]["name"] in carregadas]
    turno = _TURNO.get()
    if turno is not None:
        turno.carregadas.update(carregadas)
    resultado["como_usar"] = (
        "Os schemas encontrados já valem na sua próxima resposta, ainda neste turno: "
        "se o pedido pede uma delas, chame-a direto. Aprovação e permissões continuam valendo."
        if carregadas else
        "Nenhuma correspondência encontrada. Consulte o mapa e carregue pelo nome exato, ou liste uma categoria."
    )
    return resultado
