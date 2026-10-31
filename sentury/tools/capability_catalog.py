"""Descoberta progressiva de capacidades do Sentury.

O catálogo é reconstruído a partir dos registros vivos de tools e skills em
cada consulta. Isso evita um índice de sessão ficar desatualizado quando um
plugin entra, sai ou muda de escopo. A recuperação é local e determinística:
BM25 para o catálogo pequeno, sem chamada de LLM e sem serviço externo.

Esta camada só encontra capacidades candidatas. Ela nunca escreve a resposta,
nunca autoriza uma tool e nunca substitui o Harness.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Mapping, Sequence


_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos",
    "e", "em", "eu", "me", "meu", "minha", "na", "nas", "no", "nos", "o",
    "os", "ou", "para", "por", "pra", "qual", "quais", "que", "sem", "seu",
    "sua", "um", "uma",
}


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _raiz(token: str) -> str:
    """Radical grosseiro: "lembra", "lembre" e "lembrete" viram "lembr".

    Pedido e catalogo passam pelo mesmo corte, entao variacoes da mesma
    palavra casam.
    """
    if not token.isascii():
        return token
    if len(token) > 4 and token.endswith("s"):
        token = token[:-1]
    if len(token) > 4 and token[-1] in "aeo":
        token = token[:-1]
    return token[:5]


def _tokens(text: str) -> List[str]:
    normalized = _normalize(text).replace("_", " ").replace("-", " ").replace(".", " ")
    return [_raiz(token) for token in _TOKEN_RE.findall(normalized)
            if len(token) > 1 and token not in _STOPWORDS]


@dataclass(frozen=True)
class CapabilityEntry:
    """Resumo pequeno e seguro de uma capacidade carregada no runtime."""

    name: str
    kind: str
    description: str
    category: str = "general"
    source: str = "sentury"
    search_terms: Sequence[str] = field(default_factory=tuple)

    @property
    def search_text(self) -> str:
        return " ".join((self.name, self.description, self.category, *self.search_terms))

    def public_dict(self, score: float | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "category": self.category,
            "description": self.description[:400],
            "source": self.source,
        }
        if score is not None:
            result["score"] = round(float(score), 4)
        return result


def build_catalog(
    tool_registry: Mapping[str, Mapping[str, Any]],
    skills: Iterable[Any] = (),
    *,
    funcoes: Iterable[str] = (),
) -> List[CapabilityEntry]:
    """Projeta o catálogo atual de tools e skills sem manter estado paralelo."""
    entries: List[CapabilityEntry] = []
    # Ferramenta de setor so entra quando o pacote dela esta ligado. Sem isto,
    # a descoberta oferecia ao generalista 24 das 71 entradas que o gate depois
    # recusaria: "qual a causa do problema" devolvia `root_cause` e
    # `generate_insights`, o modelo chamava, o harness barrava, e a volta era
    # gasta sem nada observado. Sugerir o que nao existe e o jeito mais caro de
    # dizer nao.
    try:
        from .registry import ferramentas_do_setor_ativo

        permitidas = ferramentas_do_setor_ativo()
    except Exception:
        permitidas = None

    from ..residentes.escopo import ferramentas_permitidas

    do_agente = ferramentas_permitidas()
    ligadas = {str(funcao).strip().casefold() for funcao in (funcoes or ())}
    for name, metadata in tool_registry.items():
        # A ponte não é capacidade a descobrir: vai oferecida direto sob demanda.
        if metadata.get("exposta_ao_modelo", True) is False or metadata.get("ponte"):
            continue
        if metadata.get("so_com_funcao") and metadata["so_com_funcao"] not in ligadas:
            continue
        if do_agente is not None and name not in do_agente:
            continue
        if do_agente is None and metadata.get("so_residente"):
            continue
        if permitidas is not None and name not in permitidas:
            continue
        raw_terms = metadata.get("quando_usar") or metadata.get("tags") or ()
        if isinstance(raw_terms, str):
            raw_terms = (raw_terms,)
        entries.append(CapabilityEntry(
            name=name,
            kind="tool",
            description=str(metadata.get("descricao") or ""),
            category=str(metadata.get("categoria") or "general"),
            source="tool-registry",
            search_terms=tuple(str(term) for term in raw_terms),
        ))

    for skill in skills:
        name = str(getattr(skill, "name", "") or "").strip()
        if not name:
            continue
        tags = tuple(str(tag) for tag in (getattr(skill, "tags", None) or ()))
        tools = tuple(str(tool) for tool in (getattr(skill, "tools_used", None) or ()))
        entries.append(CapabilityEntry(
            name=name,
            kind="skill",
            description=str(getattr(skill, "description", "") or ""),
            category=str(getattr(skill, "category", "general") or "general"),
            source="skill-registry",
            search_terms=tags + tools + (str(getattr(skill, "family", "") or ""),),
        ))
    return entries


def search_catalog(
    catalog: Sequence[CapabilityEntry],
    query: str,
    limit: int = 6,
) -> List[tuple[CapabilityEntry, float]]:
    """Ranqueia o catálogo com BM25 e boosts exatos, sem decidir pelo agente."""
    if not catalog or limit <= 0:
        return []
    query_tokens = _tokens(query)
    if not query_tokens:
        return []

    docs = [_tokens(entry.search_text) for entry in catalog]
    lengths = [len(doc) for doc in docs]
    average_length = sum(lengths) / max(len(lengths), 1)
    document_frequency: dict[str, int] = {}
    for doc in docs:
        for token in set(doc):
            document_frequency[token] = document_frequency.get(token, 0) + 1

    scored: List[tuple[CapabilityEntry, float]] = []
    query_normalized = _normalize(query)
    query_set = set(query_tokens)
    for entry, doc in zip(catalog, docs):
        if not doc:
            continue
        term_frequency: dict[str, int] = {}
        for token in doc:
            term_frequency[token] = term_frequency.get(token, 0) + 1

        score = 0.0
        for token in query_set:
            frequency = term_frequency.get(token, 0)
            if not frequency:
                continue
            df = document_frequency.get(token, 0)
            inverse_frequency = math.log(1 + (len(catalog) - df + 0.5) / (df + 0.5))
            norm = frequency * 2.5 / (
                frequency + 1.5 * (1 - 0.75 + 0.75 * len(doc) / max(average_length, 1.0))
            )
            score += inverse_frequency * norm

        normalized_name = _normalize(entry.name).replace("_", " ").replace("-", " ")
        if normalized_name and normalized_name in query_normalized:
            score += 4.0
        elif set(_tokens(entry.name)).issubset(query_set):
            score += 2.0

        if score > 0:
            scored.append((entry, score))

    scored.sort(key=lambda item: (-item[1], item[0].kind, item[0].name))
    return scored[:limit]


def render_matches(matches: Sequence[tuple[CapabilityEntry, float]]) -> str:
    """Renderiza apenas resumos; schemas e corpos completos continuam sob demanda."""
    if not matches:
        return "A busca lexical não encontrou candidatas. Consulte o mapa de capacidades; isto não significa que a capacidade não existe."
    lines = [
        "Índice local de capacidades candidatas (é uma dica de descoberta, não uma ordem):",
    ]
    for entry, _score in matches:
        lines.append(f"- `{entry.name}` [{entry.kind}/{entry.category}]: {entry.description[:240]}")
    lines.append("Escolha você se alguma delas é necessária; ferramentas continuam sujeitas ao Harness.")
    return "\n".join(lines)


def render_manifest(catalog: Sequence[CapabilityEntry], max_chars: int = 6000) -> str:
    """Mapa estável de ferramentas; o idioma do pedido não muda sua visibilidade.

    Catálogos maiores degradam para nomes e depois categorias. A listagem
    paginada de `search_tools` mantém o restante acessível.
    """
    tools = sorted((entry for entry in catalog if entry.kind == "tool"),
                   key=lambda entry: (entry.category, entry.name))
    header = (
        "Mapa das ferramentas disponíveis nesta conversa:\n"
        "Interprete o pedido no idioma da pessoa e escolha pelo que a ferramenta faz. "
        "Para carregar os parâmetros de uma ferramenta fora da chamada, use "
        "`search_tools(nomes=[nome_exato])`. Para listar uma categoria, use "
        "`search_tools(categoria=categoria, offset=0)`. A busca por `consulta` é lexical "
        "e pode não reconhecer sinônimos ou outro idioma; uma busca vazia não indica ausência. "
        "Disponibilidade não obriga execução: converse normalmente quando nenhuma ferramenta for necessária. "
        "Se perguntarem o que você sabe fazer, responda por este mapa e pelo catálogo de skills: "
        "o que não aparece neles não existe aqui, e vale dizer isso em vez de citar um nome parecido."
    )
    if not tools:
        return header + "\nNenhuma ferramenta está disponível."
    lines = [f"- `{entry.name}` [{entry.category}]: "
             + " ".join(entry.description.split())[:100] for entry in tools]
    detailed = header + "\n" + "\n".join(lines)
    if len(detailed) <= max_chars:
        return detailed
    groups: dict[str, list[str]] = {}
    for entry in tools:
        groups.setdefault(entry.category, []).append(f"`{entry.name}`")
    names = header + "\n" + "\n".join(
        f"- {category}: {', '.join(group)}" for category, group in groups.items())
    if len(names) <= max_chars:
        return names
    return header + "\n" + "\n".join(
        f"- {category}: {len(group)} ferramentas; liste a categoria para ver os nomes."
        for category, group in groups.items())


__all__ = [
    "CapabilityEntry",
    "build_catalog",
    "render_matches",
    "render_manifest",
    "search_catalog",
]
