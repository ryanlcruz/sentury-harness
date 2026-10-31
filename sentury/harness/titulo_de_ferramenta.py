"""O que a linha de execução diz em cada passo.

O título autoral vem do setor (`titulos_de_passo`) ou do `tools.yaml`
(`titulo`, `titulos_pelo_codigo`). Sem ele, o registro já sabe o resto:

- `descricao` diz o que a ferramenta faz;
- `parametros.properties` declara os argumentos **na ordem em que importam**,
  então o primeiro que veio preenchido é o alvo: o caminho, a URL, a tabela.

Título continua sendo autoral onde alguém escreveu um: isto é o que entra no
lugar do genérico, não por cima da voz que já existe.
"""
from __future__ import annotations

import logging
import string
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Caminho do Windows estoura qualquer linha; o fim é a parte que identifica.
TETO_DO_VALOR = 72
# Rótulo de linha, não frase: acima disto ele empurra tool, duração e estado
# para fora da tela.
TETO_DO_TITULO = 58


def _meta(tool: str) -> Dict[str, Any]:
    from ..tools.registry import TOOL_REGISTRY

    return dict(TOOL_REGISTRY.get(str(tool or "").strip().lower()) or {})


def _encurtar(valor: str) -> str:
    valor = " ".join(str(valor).split())
    if len(valor) <= TETO_DO_VALOR:
        return valor
    # O começo de um caminho é o disco e a pasta do usuário: igual em todos.
    return "…" + valor[-(TETO_DO_VALOR - 1):]


def alvo(tool: str, arguments: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """`chave: valor` do argumento principal, qual pasta, qual URL, qual tabela.

    Sem isto a linha dizia que uma ferramenta rodou e não em cima de quê, que é
    justamente o que quem lê precisa conferir.
    """
    args = arguments or {}
    if not args:
        return None
    try:
        declarados = list(((_meta(tool).get("parametros") or {}).get("properties") or {}).keys())
    except Exception:
        logger.debug("Registro nao respondeu pelos parametros de %s", tool, exc_info=True)
        declarados = []
    # Argumento declarado primeiro ganha; sem declaração, a ordem que chegou.
    for chave in declarados + [k for k in args if k not in declarados]:
        valor = args.get(chave)
        if isinstance(valor, bool) or valor is None or valor == "":
            continue
        if isinstance(valor, (dict, list)):
            continue
        return f"{chave}: {_encurtar(valor)}"
    return None


def titulo(tool: str, arguments: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """A descrição que o registro dá para a ferramenta, em uma linha."""
    descricao = str(_meta(tool).get("descricao") or "").strip()
    if not descricao:
        return None
    # Aqui a descrição é rótulo de linha, não frase: o ponto final vira
    # sujeira, e a segunda frase costuma ser instrução de uso ("Aceita inicio
    # e linhas para ler so um trecho"), que não cabe na lista.
    descricao = descricao.split("\n")[0].split(". ")[0].strip().rstrip(".")
    # A descrição do registro é escrita para o MODELO escolher a ferramenta, e
    # por isso é longa (a maior tem 146 caracteres). Como rótulo de linha ela
    # empurra o resto para fora da tela. Antes da vírgula costuma estar a
    # oração principal; só depois dela é que se corta no braço.
    if len(descricao) > TETO_DO_TITULO and "," in descricao:
        descricao = descricao.split(",")[0].strip()
    if len(descricao) > TETO_DO_TITULO:
        corte = descricao[:TETO_DO_TITULO].rsplit(" ", 1)[0]
        # Parêntese aberto que o corte deixou para trás fica pior que o corte:
        # "Roda um comando de LEITURA (git status/log/diff" parece truncado por
        # engano, e não por decisão.
        if corte.count("(") > corte.count(")"):
            corte = corte[:corte.rindex("(")].rstrip()
        descricao = (corte or descricao[:TETO_DO_TITULO]).rstrip(" ,;:—-") + "…"
    # O alvo NAO entra aqui: ele vai no corpo do cartao de execucao, e ter o
    # caminho nos dois lugares fazia o titulo quebrar em tres linhas com a
    # mesma informacao que ja estava logo ao lado.
    return descricao


GENERICO = "Executando ferramenta…"


def _declarado(tool: str, args: Dict[str, Any]) -> Optional[str]:
    """O título que o `tools.yaml` declara: pelo trecho do código quando houver,
    senão o `titulo`, com `{argumento}` trocado pelo valor. Argumento ausente
    deixa o título de lado em vez de mostrar a chave crua."""
    meta = _meta(tool)
    codigo = str(args.get("codigo") or args.get("code") or "").lower()
    for regra in meta.get("titulos_pelo_codigo") or []:
        if codigo and any(str(t).lower() in codigo for t in regra.get("trechos") or []):
            return str(regra.get("titulo") or "") or None
    modelo = str(meta.get("titulo") or "")
    if not modelo:
        return None
    try:
        campos = [c for _, c, _, _ in string.Formatter().parse(modelo) if c]
        valores = {c: str(args.get(c) or "").strip() for c in campos}
        if any(not v for v in valores.values()):
            return None
        return modelo.format_map(valores)
    except (KeyError, IndexError, ValueError):
        return None


def _do_setor(tool: str) -> Optional[str]:
    from ..domains.do_setor import titulos_de_passo

    return titulos_de_passo().get(tool) or None


def _recorte(args: Dict[str, Any]) -> str:
    """Região e período reais dos argumentos: especificidade sem inventar."""
    partes = []
    regiao = str(args.get("regiao") or "").strip()
    inicio, fim = str(args.get("periodo_inicio") or "").strip(), str(args.get("periodo_fim") or "").strip()
    if regiao:
        partes.append(regiao.title())
    if inicio or fim:
        partes.append(" a ".join(p for p in (inicio, fim) if p))
    return (" · " + " · ".join(partes)) if partes else ""


def titulo_do_passo(tool: str, arguments: Optional[Dict[str, Any]] = None) -> str:
    """Título do passo na voz do agente: o do setor, o declarado no `tools.yaml`,
    a descrição do registro, nessa ordem. O recorte vai junto quando a voz é
    autoral; a descrição do registro já é a linha inteira."""
    nome, args = str(tool or "").strip().lower(), arguments or {}
    base = _do_setor(nome) or _declarado(nome, args)
    if base:
        return base + _recorte(args)
    return titulo(nome, args) or GENERICO


def rotulo_de_progresso(tool: str, arguments: Optional[Dict[str, Any]] = None) -> str:
    """O mesmo título pelo canal de progresso, que fica no processo da conversa;
    sem o recorte, que lá vira repetição."""
    nome, args = str(tool or "").strip().lower(), arguments or {}
    return _do_setor(nome) or _declarado(nome, args) or titulo(nome, args) or GENERICO
