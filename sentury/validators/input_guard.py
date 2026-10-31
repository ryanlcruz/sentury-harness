import re
from typing import Tuple

MAX_LENGTH = 2000

_INJECTION_PATTERNS = [
    r"ignore (todas |all )?(as )?instru[cç][oõ]es anteriores",
    r"ignore (all )?previous instructions",
    r"voc[eê] (agora )?[eé] (um|uma) (dan|jailbreak)",
    r"you are now (in )?dan",
    r"revele (o |seu )?(system prompt|prompt do sistema)",
    r"reveal (the )?system prompt",
    r"esque[cç]a (suas |todas )?regras",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def validate_message(text: str) -> Tuple[bool, str]:
    if not text or not text.strip():
        return False, "mensagem vazia"
    if len(text) > MAX_LENGTH:
        return False, f"mensagem excede o limite de {MAX_LENGTH} caracteres"
    for pattern in _COMPILED:
        if pattern.search(text):
            return False, "mensagem bloqueada por suspeita de prompt injection"
    return True, ""
