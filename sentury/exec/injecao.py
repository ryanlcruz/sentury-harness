"""Texto de fora que tenta dar ordem ao agente.

Usado antes de carregar `AGENTS.md`, `CLAUDE.md` e `Sentury.md` de um projeto,
que entram como instrução de sistema. Um repositório baixado da internet pode
trazer um desses arquivos escrito para sequestrar o agente. Os padrões são
verificados em português e inglês.

Fica de fora de propósito o que dá falso positivo em instrução legítima: um
"nunca commite o .env" é conselho, não ataque. O que entra é o gesto: ler o
segredo, mandá-lo para fora, esconder da pessoa, trocar de papel.
"""
from __future__ import annotations

import re
from typing import List, Tuple

_PALAVRA = r"(?:[\wÀ-ſ]+\s+)"

_PADROES: List[Tuple[str, str]] = [
    # Anular o que veio antes.
    (r"ignore\s+" + _PALAVRA + r"*(previous|all|above|prior)\s+" + _PALAVRA + r"*instructions", "ignorar instruções"),
    (r"disregard\s+" + _PALAVRA + r"*(your|all|any)\s+" + _PALAVRA + r"*(instructions|rules|guidelines)", "ignorar instruções"),
    (r"(ignore|esqueça|esqueca|desconsidere)\s+" + _PALAVRA + r"{0,4}instruç(ões|oes|ão|ao)\s+" + _PALAVRA + r"{0,2}(anteriores|acima|do sistema|originais)", "ignorar instruções"),
    (r"system\s+prompt\s+override", "trocar o prompt de sistema"),
    # Trocar de papel.
    (r"you\s+are\s+" + _PALAVRA + r"*now\s+(a|an|the)\s+", "trocar de papel"),
    (r"(a\s+partir\s+de\s+agora|agora)\s+voc[êe]\s+(é|e|será|sera)\s+(um|uma|o|a)\s+", "trocar de papel"),
    (r"pretend\s+" + _PALAVRA + r"*(you\s+are|to\s+be)\s+", "trocar de papel"),
    (r"finja\s+(que\s+)?(ser|voc[êe]\s+é|que\s+é)\s+", "trocar de papel"),
    # Esconder da pessoa.
    (r"do\s+not\s+" + _PALAVRA + r"*tell\s+" + _PALAVRA + r"*the\s+user", "esconder da pessoa"),
    (r"n[ãa]o\s+(conte|diga|avise|mostre)\s+" + _PALAVRA + r"{0,3}(ao|à|a)\s+(usu[áa]rio|pessoa|dono)", "esconder da pessoa"),
    # Revelar o prompt.
    (r"output\s+" + _PALAVRA + r"*(system|initial)\s+prompt", "revelar o prompt de sistema"),
    (r"(revele|mostre|imprima)\s+" + _PALAVRA + r"{0,3}prompt\s+(de\s+sistema|do\s+sistema|inicial)", "revelar o prompt de sistema"),
    # Mandar segredo para fora e ler segredo.
    (r"(curl|wget|invoke-webrequest|iwr)\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "mandar segredo para fora"),
    (r"(cat|type|get-content|more)\s+[^\n]*(\.env\b|id_rsa|id_ed25519|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)", "ler segredo"),
    (r"(send|post|upload|envie|mande)\s+[^\n]{0,60}(\.env|token|senha|password|chave|api[_ -]?key)[^\n]{0,60}(to|para)\s+https?://", "mandar segredo para fora"),
    # Esconder ordem no texto.
    (r"<!--[^>]*(ignore|override|system|secret|hidden|instru)[^>]*-->", "ordem escondida em comentário"),
]

_COMPILADOS = [(re.compile(p, re.IGNORECASE), motivo) for p, motivo in _PADROES]
# Largura zero e inversão de direção: texto que o olho não vê e o modelo lê.
_INVISIVEIS = re.compile("[​-‏‪-‮⁦-⁩]")


def achados(texto: str) -> List[str]:
    """Os motivos para desconfiar do texto, sem repetir. Vazio = parece limpo."""
    bruto = str(texto or "")
    motivos: List[str] = []
    for padrao, motivo in _COMPILADOS:
        if motivo not in motivos and padrao.search(bruto):
            motivos.append(motivo)
    if _INVISIVEIS.search(bruto):
        motivos.append("caractere invisível")
    return motivos


__all__ = ["achados"]
