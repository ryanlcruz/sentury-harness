"""Function-calling nativo a partir do TOOL_REGISTRY.

Fundação da cura do tool-call por texto: gera o `tools=[...]` (formato
OpenAI/OpenRouter) e normaliza os `tool_calls` de volta pro formato interno
{action, tool, arguments} que o harness já entende. Params permissivos (object)
a descrição carrega a intenção; o gate do harness valida os args.

O planner usa estes schemas quando SENTURY_NATIVE_TOOLS está ligada.
"""
import json
from typing import Any, Dict, List, Optional, Tuple

from ..tools.registry import TOOL_REGISTRY, do_nucleo, ferramenta_exposta, so_com_funcao


def _setor_ativo() -> str:
    """Qual setor esta ligado. Vazio quando e o generalista: ou quando a
    leitura falha, porque na duvida a mesa e a do motor."""
    try:
        from ..domains.escolha import GENERALISTA
        from ..domains.registry import get_active_domain

        nome = str(getattr(get_active_domain(), "name", "") or "")
        return "" if nome == GENERALISTA else nome
    except Exception:
        return ""


def _descricao(meta: Dict[str, Any], com_orientacao: bool) -> str:
    """A linha da ferramenta e, se pedido, como usa-la. A orientacao vai so
    nas ferramentas oferecidas, nao no prompt de sistema."""
    descricao = str(meta.get("descricao") or "").strip()
    if meta.get("mostra_shell"):
        from ..tools.shell import dica_do_shell

        descricao = f"{descricao} {dica_do_shell()}".strip()
    orientacao = str(meta.get("orientacao") or "").strip() if com_orientacao else ""
    return f"{descricao}\n\n{orientacao}".strip() if orientacao else descricao


def build_tool_schemas(
    names: Optional[set] = None, com_orientacao: bool = False,
) -> List[Dict[str, Any]]:
    """Schemas function-calling do catálogo. `names` restringe; None = todas.

    `names` reúne candidatas e schemas carregados pelo modelo neste turno.
    Um conjunto vazio oferece o núcleo; o manifesto mantém as demais
    capacidades descobríveis via `search_tools`.
    """
    from ..residentes.escopo import ferramentas_permitidas

    permitidas = None if names is None else set(names) | do_nucleo()
    do_agente = ferramentas_permitidas()
    # A mesa do residente é pequena: vai inteira, sem o corte por relevância.
    if do_agente is not None and permitidas is not None:
        permitidas |= do_agente
    ativo = _setor_ativo()
    out: List[Dict[str, Any]] = []
    for nome, meta in TOOL_REGISTRY.items():
        if not ferramenta_exposta(meta):
            continue
        if permitidas is not None and nome not in permitidas:
            continue
        if do_agente is not None and nome not in do_agente:
            continue
        if do_agente is None and meta.get("so_residente"):
            continue
        # `so_com_funcao` (o `computador`): so quem pediu pelo nome, e o nome
        # so chega aqui pela funcao do `@` ligada (`funcoes.ferramentas_ligadas`).
        # O catalogo inteiro (names None) nunca a leva.
        if so_com_funcao(meta) and (names is None or nome not in names):
            continue
        # A ponte só faz sentido sob demanda, e só entra quando a descoberta a oferece.
        if meta.get("ponte") and (names is None or nome not in names):
            continue
        # Ferramenta de setor so entra quando o setor esta ativo. Sem isto o
        # generalista recebia dezesseis de CX na mesa.
        dono = str(meta.get("setor") or "")
        if dono and dono != ativo:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": nome,
                "description": _descricao(meta, com_orientacao),
                "parameters": meta.get("parametros") or {
                    "type": "object", "properties": {}, "additionalProperties": True,
                },
            },
        })
    # O que vai em toda chamada vem primeiro: o provedor so reaproveita o
    # prefixo identico, e as candidatas do pedido mudam a cada turno.
    nucleo = do_nucleo()
    fixas = [e for e in out if e["function"]["name"] in nucleo]
    variaveis = [e for e in out if e["function"]["name"] not in nucleo]
    return fixas + variaveis


# Alguns provedores prefixam nomes de ferramenta com um namespace. Remover o
# prefixo localmente evita recusar uma ferramenta válida ou gastar outra chamada.
_NAMESPACES_DE_PROVEDOR = ("default_api", "functions", "tools", "tool")
_SEPARADORES = ".:_/-"


def _nome_limpo(name: Any) -> str:
    limpo = str(name).strip()
    for espaco in _NAMESPACES_DE_PROVEDOR:
        for sep in _SEPARADORES:
            prefixo = espaco + sep
            if limpo.startswith(prefixo) and len(limpo) > len(prefixo):
                return limpo[len(prefixo):]
    return limpo


def acao_no_nome(nome: str, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """`computador.ver` é a ferramenta `computador` com `acao: ver`, quando o
    tools.yaml declara `ver` no enum de `acao` dela. Fora disso, nada muda."""
    base, ponto, acao = str(nome).partition(".")
    if not ponto:
        return nome, args
    from ..tools.registry import TOOL_REGISTRY

    propriedades = ((TOOL_REGISTRY.get(base) or {}).get("parametros") or {}).get("properties") or {}
    if acao not in ((propriedades.get("acao") or {}).get("enum") or []):
        return nome, args
    if args.get("acao") not in (None, "", acao):
        return nome, args
    return base, {**args, "acao": acao}


def _one(tc: Any) -> Optional[Dict[str, Any]]:
    fn = (tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)) or {}
    name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
    raw = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", None)
    args: Dict[str, Any] = {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            args = parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            args = {}
    elif isinstance(raw, dict):
        args = raw
    if not name:
        return None
    # O id liga a resposta `tool` a esta chamada na volta seguinte.
    id_ = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
    nome, args = acao_no_nome(_nome_limpo(name), args)
    chamada = {"action": "tool_call", "tool": nome, "arguments": args}
    if id_:
        chamada["id"] = id_
    return chamada


def parse_native_tool_calls(tool_calls: Any) -> List[Dict[str, Any]]:
    """Normaliza os tool_calls nativos do provedor pro formato interno do harness."""
    return [a for a in (_one(tc) for tc in (tool_calls or [])) if a]
