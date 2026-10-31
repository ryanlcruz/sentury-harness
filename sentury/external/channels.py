"""Catálogo de canais: por onde a Sentury conversa com alguém.

A lista cresce: cada canal novo é uma entrada aqui, com a própria categoria e
os próprios campos. A interface lista e agrupa a partir disto, então nada
precisa ser escrito de novo do lado do client.

Cada canal declara os próprios campos de configuração. A interface monta o
formulário a partir desta declaração, então um canal novo nasce aqui e não
em mais uma tela escrita à mão.

Campo `type` "secret" nunca volta preenchido: o valor fica no servidor e a
API responde apenas se existe (`configured`).
"""
from typing import Any, Dict, List, Optional

# transporte: como o canal fala com o mundo. Muda o que dá para configurar.
CANAIS: List[Dict[str, Any]] = [
    {
        "id": "web",
        "label": "Web",
        "categoria": "aplicacao",
        "transport": "http",
        "description": "Esta própria interface. Sempre disponível enquanto o backend responde.",
        "implemented": True,
        "configurable": False,
        "fields": [],
        "actions": [],
    },
    {
        "id": "telegram",
        "label": "Telegram",
        "categoria": "mensageria",
        "transport": "long_polling",
        "description": "Bot do BotFather. A Sentury responde no chat de quem estiver autorizado.",
        "implemented": True,
        "configurable": True,
        "fields": [
            {
                "name": "token",
                "label": "Token do BotFather",
                "type": "secret",
                "required": True,
                "placeholder": "123456:ABC…",
                "hint": "Salvar um novo token substitui o anterior.",
            },
            {
                "name": "allowed_ids",
                "label": "IDs permitidos",
                "type": "text",
                "required": False,
                "placeholder": "12345678, 98765432",
                "hint": "Opcional; separe vários IDs por vírgula. Vazio libera qualquer pessoa.",
            },
        ],
        "actions": ["start", "stop"],
    },
    {
        "id": "voz",
        "label": "Voz ao vivo",
        "categoria": "voz",
        "transport": "websocket",
        "description": "Ligação por voz em tempo real. Só existe quando há um modelo com áudio bidirecional.",
        "implemented": True,
        "configurable": False,
        # Sem chave ou sem a lib do provedor, o canal não aparece.
        "requires_capability": "audio_bidirecional",
        "fields": [],
        "actions": [],
    },
]

_POR_ID = {c["id"]: c for c in CANAIS}


def declaracao(canal_id: str) -> Optional[Dict[str, Any]]:
    return _POR_ID.get(canal_id)


def catalogo(estados: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Junta a declaração estática ao estado de runtime de cada canal."""
    saida = []
    for canal in CANAIS:
        estado = estados.get(canal["id"], {})
        saida.append({**canal, **estado})
    return saida
