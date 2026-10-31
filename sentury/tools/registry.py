"""Registro de ferramentas: a declaracao mora em YAML, o codigo so deriva.

`tools.yaml` (motor) e `domains/setores/<setor>/tools.yaml` (um por setor)
declaram categoria, descricao, orientacao, parametros e propriedades. Mudar
como uma ferramenta se apresenta, ou marcar uma propriedade, e editar o YAML.
Serve para:
  - o endpoint /sentury/tools (inspecao em runtime);
  - o teste de DRIFT (tests/test_registry.py): policy, catalogo e prompt nao
    saem de sincronia;
  - `names_for_gate`, `com_propriedade` e cia, que o resto do motor le em vez
    de manter lista propria.
"""
from pathlib import Path
from typing import Any, Dict, List

import yaml

_AQUI = Path(__file__).resolve().parent
_SETORES = _AQUI.parent / "domains" / "setores"
# Ausente no YAML = objeto livre. `additionalProperties` continua ligado porque
# o catalogo ainda aceita aliases antigos (`code`, `command`, `path`).
_PARAMETROS_LIVRES = {"type": "object", "properties": {}, "additionalProperties": True}


def _carregar(arquivo: Path, setor: str = "") -> Dict[str, Dict[str, Any]]:
    declaradas = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
    saida: Dict[str, Dict[str, Any]] = {}
    for nome, meta in declaradas.items():
        meta = dict(meta or {})
        if setor:
            meta["setor"] = setor
        meta.setdefault("parametros", dict(_PARAMETROS_LIVRES))
        saida[nome] = meta
    return saida


def _registro() -> Dict[str, Dict[str, Any]]:
    registro = _carregar(_AQUI / "tools.yaml")
    for arquivo in sorted(_SETORES.glob("*/tools.yaml")):
        for nome, meta in _carregar(arquivo, arquivo.parent.name).items():
            if nome in registro:
                raise ValueError(f"ferramenta '{nome}' declarada duas vezes ({arquivo})")
            registro[nome] = meta
    return registro


TOOL_REGISTRY: Dict[str, Dict[str, Any]] = _registro()


def ferramenta_exposta(meta: Dict[str, Any]) -> bool:
    """Se a tool deve aparecer para o modelo e nas superfícies públicas."""
    return meta.get("exposta_ao_modelo", True) is not False


def so_com_funcao(meta: Dict[str, Any]) -> str:
    """A função do `@` sem a qual a tool não aparece ao modelo, ou "".

    O `computador` mexe no mouse e no teclado da pessoa: só com `@computador`
    ligado ele entra na mesa (`funcoes.ferramentas_ligadas`), e o catálogo e a
    descoberta nunca o sugerem.
    """
    return str(meta.get("so_com_funcao") or "")


def so_residente(meta: Dict[str, Any]) -> bool:
    """Só existe no turno de um agente residente (a memória dele, por exemplo)."""
    return bool(meta.get("so_residente"))


def de_todo_residente(meta: Dict[str, Any]) -> bool:
    """Todo residente recebe, esteja ou não no manifesto dele."""
    return bool(meta.get("todo_residente"))


def sempre_exposta(meta: Dict[str, Any]) -> bool:
    """Exposta e sem depender de função nem da carga sob demanda: o que o
    modelo vê em todo turno."""
    return (ferramenta_exposta(meta) and not so_com_funcao(meta) and not so_residente(meta)
            and not meta.get("ponte"))


CATEGORIAS_INTERROMPIVEIS = frozenset({"analise", "conhecimento"})


def interrompivel(nome: str, argumentos: dict | None = None) -> bool:
    """Se o Parar pode cortar a ferramenta no meio.

    Leitura pode: cortada, não deixa nada pela metade. Escrita, envio e
    comando não: o Parar espera a ferramenta acabar e para antes da seguinte
    (ver harness/turno_em_curso.py). A declaração `interrompivel` na entrada
    vence; sem ela, vale a categoria. Ferramenta desconhecida não é cortada.
    """
    meta = ferramentas_do_setor_ativo().get(nome) or TOOL_REGISTRY.get(nome)
    if not meta:
        return False
    if "interrompivel" in meta:
        return bool(meta["interrompivel"])
    # Ferramenta com várias ações: a de leitura pode ser cortada mesmo quando a
    # ferramenta é de execução por causa das outras.
    if meta.get("acoes") and efeito_de(nome, argumentos) == "leitura":
        return True
    return meta.get("categoria") in CATEGORIAS_INTERROMPIVEIS


def tools_by_category() -> Dict[str, List[Dict[str, str]]]:
    agrupado: Dict[str, List[Dict[str, str]]] = {}
    for nome, meta in ferramentas_do_setor_ativo().items():
        # O que só o residente usa fica num grupo à parte: o Sentury não as tem.
        grupo = "residentes" if so_residente(meta) else meta["categoria"]
        agrupado.setdefault(grupo, []).append({"nome": nome, "descricao": meta["descricao"]})
    return agrupado


# --- Gate do Harness (passo 1 da plugabilidade) -----------------------------
# A `categoria` acima é de EXIBIÇÃO (analise/acao/execucao/…). O Harness gateia
# por uma taxonomia própria (a de policy.py). Este mapa liga uma à outra e passa
# a ser a FONTE ÚNICA: policy.py deriva seus conjuntos daqui (não mais listas
# hardcoded duplicadas). "external" fica reservada pro passo 4 (MCP).
# De quem e cada ferramenta. Sem `setor`, ela e do motor e vale para
# qualquer um; com `setor`, so entra na mesa quando aquele setor esta
# ativo.
#
# O generalista enxergava dezesseis ferramentas de CX: `analyze_nps` e
# companhia: e oferecer NPS e CSAT a quem desligou o setor de proposito e
# pôr ferramenta de dominio na mesa de quem nao tem o dominio.
#
# O nome continua sem prefixo porque renomear para `cx.*` mexeria em
# centenas de pontos sem comprar nada alem do que a declaracao ja compra.
def setor_da_ferramenta(nome: str) -> str:
    """O setor dono da ferramenta, ou "" quando ela e do motor."""
    return str((TOOL_REGISTRY.get(nome) or {}).get("setor") or "")


def do_motor() -> set:
    """As que valem para qualquer setor, inclusive o generalista."""
    return {n for n, m in TOOL_REGISTRY.items() if not m.get("setor")}


CATEGORIA_TO_GATE: Dict[str, str] = {
    "analise": "analysis",
    "acao": "analysis",
    "execucao": "action",
    "exportacao": "export",
    "conhecimento": "read",
    "memoria": "memory",
    "skill": "skill",
    "external": "external",
    "browser": "browser",
}


def do_nucleo() -> set:
    """As tools que nunca saem da chamada.

    O corte por relevância é um chute informado: quando ele erra, o modelo
    precisa de um caminho de volta. Estas são esse caminho.
    """
    return {n for n, m in TOOL_REGISTRY.items() if m.get("nucleo")}


def gate_of(name: str) -> str | None:
    """Categoria de GATE do Harness para uma tool (analysis/action/export/…)."""
    meta = TOOL_REGISTRY.get(name)
    return CATEGORIA_TO_GATE.get(meta["categoria"]) if meta else None


def com_propriedade(chave: str, valor=True) -> frozenset:
    """Nomes das ferramentas cuja declaracao tem `chave == valor`.

    Propriedade de ferramenta mora na entrada dela, aqui. Lista solta em outro
    modulo esquecia a ferramenta nova (o envelope de terceiros nao cobria
    pagina nem busca). O pacote de setor declara as dele no YAML.
    """
    return frozenset(n for n, m in TOOL_REGISTRY.items() if m.get(chave, not valor) == valor)


EFEITOS = ("leitura", "escrita", "destrutiva")
# Ferramenta de setor que não declara o efeito: análise e conhecimento só leem;
# o resto conta como escrita, que é o lado seguro de errar.
_EFEITO_DA_CATEGORIA = {"analise": "leitura", "conhecimento": "leitura"}


def efeito_de(name: str, argumentos: dict | None = None) -> str:
    """O que a chamada faz no mundo: `leitura`, `escrita` ou `destrutiva`.

    Com `acoes` declaradas, decide a ação pedida; ação ausente ou desconhecida
    fica com o efeito da ferramenta, que é o da ação mais forte."""
    meta = TOOL_REGISTRY.get(name) or {}
    acao = (argumentos or {}).get("acao") if isinstance(argumentos, dict) else None
    por_acao = meta.get("acoes") or {}
    if acao in por_acao:
        return por_acao[acao]
    return meta.get("efeito") or _EFEITO_DA_CATEGORIA.get(meta.get("categoria"), "escrita")


def acoes_com_efeito(name: str, *efeitos: str) -> frozenset:
    """As ações da ferramenta com algum desses efeitos, lidas do YAML."""
    return frozenset(a for a, e in ((TOOL_REGISTRY.get(name) or {}).get("acoes") or {}).items() if e in efeitos)


def names_for_gate(gate: str) -> set:
    """Conjunto de tools que gateiam nessa categoria (fonte dos sets de policy)."""
    return {n for n, m in TOOL_REGISTRY.items() if CATEGORIA_TO_GATE.get(m["categoria"]) == gate}


def all_tool_names() -> set:
    return set(TOOL_REGISTRY)


def ferramentas_do_setor_ativo() -> dict:
    """Registro público, derivado dos metadados e do setor ligado agora."""
    from ..domains import get_active_domain

    ativo = get_active_domain().name
    return {
        nome: meta
        for nome, meta in TOOL_REGISTRY.items()
        if ferramenta_exposta(meta)
        and (not meta.get("setor") or meta.get("setor") == ativo)
    }
