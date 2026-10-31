import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_KV_LINE_RE = re.compile(r'^(\s*"[a-zA-Z0-9_]+"\s*:\s*")(.*)("\s*,?\s*)$')
# Modelos de raciocínio (qwen3, deepseek-r1, etc.) escrevem o "pensamento" em
# <think>...</think> antes do JSON. Removemos isso para não confundir o parser.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# Embrulhos internos que o modelo às vezes papagaia: nunca vão pro usuário.
_SCAFFOLD_LINE = re.compile(
    r"^\s*(?:\[System Notice:|\[Assistant historical output:|RESULTADO DA FERRAMENTA|\]\s*$)",
    re.IGNORECASE,
)


def _strip_reasoning(text: str) -> str:
    text = _THINK_RE.sub("", text)
    # <think> sem fechamento = resposta truncada no meio do raciocínio: descarta
    # tudo a partir dali (não há JSON válido depois mesmo).
    idx = text.lower().find("<think>")
    return text[:idx] if idx != -1 else text


def _first_json_object(text: str) -> Optional[str]:
    """Extrai o PRIMEIRO objeto JSON balanceado do texto. Necessário porque a
    LLM às vezes devolve o objeto duplicado (`{...}{...}`) ou com texto em volta;
    um regex guloso pegaria os dois juntos e o json.loads falharia. Ignora chaves
    dentro de strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]  # chaves não fecharam: devolve o resto p/ tentativa de reparo

def _try_load(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError as erro:
        logger.debug("JSON inválido: %s (linha %s, coluna %s)", erro.msg, erro.lineno, erro.colno)
        return None


def _repair_json(text: str) -> str:
    # LLMs às vezes devolvem JSON quase-válido mesmo instruídas a só mandar
    # JSON: aspas internas não escapadas no valor e vírgula sobrando antes de
    # fechar. Conserta os dois casos mais comuns antes de desistir.
    lines = []
    for line in text.split("\n"):
        kv = _KV_LINE_RE.match(line)
        if kv:
            prefix, value, suffix = kv.groups()
            value = re.sub(r'(?<!\\)"', lambda _: '\\"', value)
            line = prefix + value + suffix
        lines.append(line)
    return _TRAILING_COMMA_RE.sub(r"\1", "\n".join(lines))


# Marcadores que o modelo usa para dizer "este trecho e para RODAR". Sem um
# deles, o bloco e codigo para ler, nao ordem de execucao.
_MARCADORES_DE_EXECUCAO = ("run", "exec", "executar", "sentury:run")


def extrair_bloco_declarado(text: str) -> Optional[str]:
    """Codigo que o proprio modelo marcou para executar.

    Antes a execucao era inferida do texto ao redor ("plt.", ".png"), entao
    "me passa um codigo em python que salva um grafico" rodava no sandbox em
    vez de so mostrar. Agora a intencao precisa estar na cerca:

        ```python run
        ...
        ```
    """
    if not text:
        return None
    padrao = re.compile(r"```[ \t]*(?:python|py)[ \t]+([^\n`]*)\n(.*?)```", re.DOTALL | re.IGNORECASE)
    for match in padrao.finditer(text):
        marcas = match.group(1).strip().lower().replace(",", " ").split()
        if any(marca in _MARCADORES_DE_EXECUCAO for marca in marcas):
            corpo = match.group(2).strip()
            if corpo:
                return corpo
    return None


# Embrulho de chamada que o modelo vazou no texto: nunca aparece como prosa.
_TOOL_WRAPPER_RE = re.compile(
    r"<\s*[a-z_]*(?:tool|function)[a-z_]*\b[^>]*>(.*?)(?:</\s*[a-z_]*(?:tool|function)[a-z_]*\s*>|$)",
    re.IGNORECASE | re.DOTALL,
)
def extract_plain_text(raw_text: str) -> str:
    """Para o RESPONDER: devolve só a prosa para o cliente. Remove <think> e
    QUALQUER objeto JSON de ação que o modelo tenha incluído por engano: nunca
    mostramos JSON cru no chat. Se o JSON for um {"action":"respond","message"},
    aproveita a mensagem; se for um tool_call, descarta."""
    text = _strip_reasoning(raw_text or "")
    original_cleaned = text
    removed_structured_action = False
    for _ in range(5):  # remove no máx. alguns blocos JSON, evita laço infinito
        obj = _first_json_object(text)
        if not obj:
            break
        parsed = _try_load(obj) or _try_load(_repair_json(obj))
        replacement = ""
        if isinstance(parsed, dict):
            action = str(parsed.get("action") or "").strip().lower()
            if action or parsed.get("tool") or parsed.get("skill"):
                removed_structured_action = True
            if isinstance(parsed.get("message"), str):
                replacement = parsed["message"]
        text = text.replace(obj, replacement, 1).strip()

    # Rede de segurança extra: wrapper de tool-call vazado (<serpent_tool>…) que
    # não é JSON: nunca deve aparecer como prosa no chat.
    text = _TOOL_WRAPPER_RE.sub("", text).strip()

    # Linhas de embrulho interno que o modelo às vezes copia do histórico
    # ([System Notice:...], "RESULTADO DA FERRAMENTA...", "]"): marcas do próprio
    # Sentury, não conteúdo.
    linhas = [ln for ln in text.split("\n") if not _SCAFFOLD_LINE.match(ln)]
    result_text = "\n".join(linhas).strip()
    if not result_text and original_cleaned.strip() and not removed_structured_action:
        # Se a limpeza removeu tudo, retorna o texto original limpo de <think>
        return original_cleaned.strip()
    return result_text

