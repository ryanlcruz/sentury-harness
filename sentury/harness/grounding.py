"""Validador de grounding (determinístico): confere se os números que o
responder citou de fato vieram de um resultado de ferramenta desta sessão.
É a contramedida para a classe de bug em que o modelo fraco inventa dado:
"economia de R$ 100.000", "redução de 28%", "satisfação 4,5/5": sem nenhuma
ferramenta ter retornado isso.

Duas regras, calibradas para precisão (evitar falso-positivo que rejeite
resposta legítima):

1. MOEDA: o dataset de CX/Operação não tem valor monetário. Logo, QUALQUER
   "R$ ..." na resposta é fabricado. Regra de precisão 100%, segura para
   acionar correção.
2. DECIMAIS: números com casa decimal (NPS -30,1; CSAT 4,5; 49,4%) deveriam
   aparecer em algum resultado de ferramenta. Quando não aparecem, é sinal de
   invenção: mas como a normalização pt-BR é imperfeita, isso é só LOGADO
   (observabilidade), não bloqueia a resposta.
"""
import re
from typing import Any, Dict, List

from .state import AnalysisState

# Dinheiro em qualquer notacao que apareca numa resposta em pt-BR ou en.
# O anterior era so `R$`: uma de sete formas, e as outras seis passavam.
_CURRENCY_RE = re.compile(
    r"(?:R\$|US\$|\bUSD\b|\bEUR\b|\bGBP\b|[$€£])\s*[\d.,]+"
    r"|\d[\d.,]*\s*(?:mil|milh(?:ao|oes|ão|ões)|bilh(?:ao|oes|ão|ões))?\s*"
    r"(?:reais|d[oó]lares|euros)",
    re.IGNORECASE,
)

# So os digitos de dentro da expressao de dinheiro, para conferir contra a
# evidencia. "R$ 1.234,50" -> 1234.50
_SO_DIGITOS = re.compile(r"[\d.,]+")
_DECIMAL_RE = re.compile(r"-?\d+[.,]\d+")


_BLOCO_RE = re.compile(r"```(?:vivo|html|svg)[ \t]*\n(.*?)```", re.S | re.I)
_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.S | re.I)
_ESTILO_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.S | re.I)
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_NUMERO_NO_SCRIPT = re.compile(r"(?<![\w.])-?\d+\.\d+(?![\w.])")


def texto_para_conferir(texto: str) -> str:
    """O que a pessoa lê, para conferir os números da resposta.

    Num bloco vivo (HTML ou SVG), entram o texto visível e os números com casa
    decimal do script, que é onde mora o dado de uma simulação; tag, CSS e
    atributos ficam de fora, senão `0.06em` e `opacity: .5` virariam número
    sem lastro.
    """
    import html

    def visivel(trecho: str) -> str:
        numeros = _NUMERO_NO_SCRIPT.findall(" ".join(_SCRIPT_RE.findall(trecho)))
        sem_codigo = _TAG_RE.sub(" ", _SCRIPT_RE.sub(" ", _ESTILO_RE.sub(" ", trecho)))
        return html.unescape(sem_codigo) + (" " + " ".join(numeros) if numeros else "")

    texto = _PAINEL_RE.sub(lambda m: _valores_do_painel(m.group(1)), texto or "")
    texto = _BLOCO_RE.sub(lambda m: visivel(m.group(1)), texto)
    # HTML solto na prosa também vira bloco na tela.
    return visivel(texto) if _TAG_RE.search(texto) else texto


_PAINEL_RE = re.compile(r"```painel[ \t]*\n(.*?)```", re.S | re.I)


def _valores_do_painel(fonte: str) -> str:
    """Os textos e números que o painel mostra; a fórmula do simulador fica de
    fora, porque o resultado dela muda com o controle."""
    import json

    try:
        dado = json.loads(fonte)
    except ValueError:
        return fonte
    folhas: List[str] = []

    def andar(valor: Any, chave: str = "") -> None:
        if chave == "formula":
            return
        if isinstance(valor, dict):
            for k, v in valor.items():
                andar(v, str(k))
        elif isinstance(valor, list):
            for v in valor:
                andar(v, chave)
        elif isinstance(valor, (str, int, float)) and not isinstance(valor, bool):
            folhas.append(str(valor))

    andar(dado)
    return " ".join(folhas)


def _decimals(text: str) -> List[float]:
    valores: List[float] = []
    for token in _DECIMAL_RE.findall(text or ""):
        # pt-BR usa vírgula decimal; o resultado bruto da ferramenta usa ponto.
        # Removemos separador de milhar e unificamos a vírgula como decimal.
        normal = token.replace(".", "").replace(",", ".") if "," in token else token
        try:
            valores.append(round(float(normal), 2))
        except ValueError:
            continue
    return valores


def evidence_text(state: AnalysisState) -> str:
    """Texto de evidência: tudo que veio de ferramenta nesta sessão, os blocos
    'RESULTADO DA FERRAMENTA' (mensagens de sistema) e os resumos registrados."""
    partes: List[str] = []
    for m in state.history:
        if m.get("role") != "system":
            continue
        content = str(m.get("content") or "")
        # Skills and prompt examples also live as system messages, but are not evidence.
        if "RESULTADO DA FERRAMENTA" in content or content.startswith("ID DO RESULTADO"):
            partes.append(content)
    for receita in state.results.values():
        partes.append(str(receita.get("summary", "")))
    return "\n".join(partes)


def havia_dado_de_fora(state: AnalysisState, ferramentas) -> bool:
    """Algum resultado de ferramenta que traz dado já está na conversa.

    `last_result_id` só nasce das análises do setor; o CSV lido por
    `ler_arquivo` ou a saída de um comando também são dado real.
    """
    for m in state.history:
        chamada = m.get("chamada") if isinstance(m, dict) else None
        if isinstance(chamada, dict) and chamada.get("nome") in ferramentas:
            return True
    return False


def _derivavel(alvo: float, base: List[float], tol: float = 0.05) -> bool:
    """O número é uma conta simples sobre valores que ESTÃO na evidência?

    Analista soma, subtrai e tira média o tempo todo: com NPS -49,3 e -37,8 na
    mesa, dizer "11,5 pontos de diferença" é legítimo, ainda que 11,5 não
    apareça em lugar nenhum. Sem reconhecer isso, o guard chama de invenção o
    trabalho que a gente PEDE que ele faça: e é por isso que ele nunca pôde
    bloquear.
    """
    if any(abs(alvo - e) < tol for e in base):
        return True
    for a in base:
        for b in base:
            if a is b:
                continue
            for cand in (a - b, a + b, (a + b) / 2):
                if abs(alvo - cand) < tol:
                    return True
        # variação percentual entre dois valores da evidência
        for b in base:
            if b and abs(b) > 1e-9:
                for cand in (a / b * 100.0, (a - b) / abs(b) * 100.0):
                    if abs(alvo - cand) < tol:
                        return True
    return False


def classify_numbers(message: str, evidence: str, limite_base: int = 40) -> Dict[str, List[float]]:
    """Separa os decimais da resposta em: `grounded` (aparece na evidência),
    `derived` (conta simples sobre ela) e `suspect` (nem um nem outro).

    O guard só observa: sem separar derivado de inventado, bloquear acusaria
    conta correta como invenção.
    """
    base = _decimals(evidence)[:limite_base]  # teto: a busca é O(n²)
    grounded: List[float] = []
    derived: List[float] = []
    suspect: List[float] = []
    for v in _decimals(message):
        if any(abs(v - e) < 0.05 for e in base):
            grounded.append(v)
        elif _derivavel(v, base):
            derived.append(v)
        else:
            suspect.append(v)
    return {"grounded": grounded, "derived": derived, "suspect": suspect}


_MILHAR_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?:,\d+)?|(?<![\d.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?")


def _milhares(text: str) -> List[float]:
    """Números com separador de milhar, como texto formatado os escreve
    (`5.490,00`, `5,490.00`). `_decimals` lê `5.490,00` como 5,49: resultado de
    ferramenta vem sem milhar, mas a resposta de um colega vem formatada."""
    saida = []
    for token in _MILHAR_RE.findall(text or ""):
        # Com os dois separadores, o último é o decimal; com um só, o padrão já
        # garante grupos de três dígitos, então ele é de milhar.
        if "." in token and "," in token:
            decimal = "," if token.rindex(",") > token.rindex(".") else "."
            normal = token.replace("." if decimal == "," else ",", "").replace(decimal, ".")
        else:
            normal = token.replace(".", "").replace(",", "")
        try:
            saida.append(round(float(normal), 2))
        except ValueError:
            continue
    return saida


def _inteiros(text: str) -> List[float]:
    """Numeros sem casa decimal. `_decimals` so pega os que tem virgula/ponto,
    e valor de dinheiro costuma vir redondo do banco (`150`, `100000`)."""
    saida = []
    for token in re.findall(r"(?<![\d.,])\d+(?![\d.,])", text or ""):
        try:
            saida.append(float(token))
        except ValueError:
            continue
    return saida


def _valor_na_evidencia(achado: str, base: List[float]) -> bool:
    """O valor dentro da expressao de dinheiro tem lastro?

    Reusa `_derivavel`, entao conta que o analista faz (diferenca entre dois
    valores, media) continua legitima. Sem digito reconhecivel, nao acusa: o
    guard nunca deve chutar na duvida.
    """
    digitos = _SO_DIGITOS.search(achado or "")
    if not digitos:
        return True
    bruto = digitos.group(0).strip(".,")
    # pt-BR: 1.234,50 -> 1234.50. en: 1,234.50 -> 1234.50
    if "," in bruto and "." in bruto:
        normal = bruto.replace(".", "").replace(",", ".") if bruto.rindex(",") > bruto.rindex(".") else bruto.replace(",", "")
    elif "," in bruto:
        normal = bruto.replace(",", ".") if len(bruto.split(",")[-1]) <= 2 else bruto.replace(",", "")
    else:
        normal = bruto.replace(".", "") if len(bruto.split(".")[-1]) == 3 else bruto
    try:
        valor = float(normal)
    except ValueError:
        return True
    return _derivavel(valor, base)


def find_ungrounded(message: str, evidence: str) -> Dict[str, List[Any]]:
    """Devolve os números da resposta que NÃO têm respaldo na evidência.
    `currency` aciona correção (precisão 100%); `decimals` é só para log."""
    # A pergunta NAO e "tem simbolo de moeda na evidencia?": e "este NUMERO
    # existe nela?". Num banco de e-commerce a ferramenta devolve
    # `ticket_medio: 150.0`, sem simbolo, e o modelo escrevendo "R$ 150,00"
    # estava CERTO; a versao anterior marcava como fabricado e reescrevia.
    base = _decimals(evidence) + _inteiros(evidence) + _milhares(evidence)
    currency = [
        achado for achado in _CURRENCY_RE.findall(message or "")
        if not _valor_na_evidencia(achado, base)
    ]

    evidencia_decimais = _decimals(evidence)
    decimais_sem_lastro = [
        v for v in _decimals(message) if not any(abs(v - e) < 0.05 for e in evidencia_decimais)
    ]
    return {"currency": currency, "decimals": decimais_sem_lastro}
