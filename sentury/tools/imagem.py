"""Geração de imagem, por intenção declarada.

Mesma regra da execução de Python: a intenção mora no pedido, não numa
adivinhação. Gerar imagem custa e demora, e "me mostra um gráfico" quase
sempre quer um gráfico de dados: não um desenho. Por isso o gatilho é
explícito: `@image` na mensagem.

O modelo usado é o que estiver escolhido no papel `imagem` do catálogo
(Nano Banana e afins). Sem modelo escolhido e sem chave, não há geração: a
função diz isso em vez de devolver um placeholder.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# `@image` isolado, não no meio de um e-mail ou de um nome de arquivo.
MARCADOR = re.compile(r"(?:^|\s)@image\b", re.IGNORECASE)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELO_PADRAO = "gemini-3.1-flash-image"
TIMEOUT = 90.0


def pediu_imagem(mensagem: str) -> bool:
    """A pessoa declarou que quer uma imagem gerada."""
    return bool(MARCADOR.search(str(mensagem or "")))


def limpar_marcador(mensagem: str) -> str:
    """Texto sem o `@image`, que é comando e não parte do pedido."""
    return MARCADOR.sub(" ", str(mensagem or "")).strip()


def modelos_de_imagem() -> List[str]:
    """Modelos escolhidos para o papel `imagem`, na ordem do usuário."""
    try:
        from robinbandit.account_config import modelos_por_papel

        escolhidos: List[str] = []
        for modelos in modelos_por_papel("imagem").values():
            for modelo in modelos:
                # O catalogo guarda "google/gemini-3.1-flash-image"; a API do
                # Gemini quer so o nome do modelo.
                nome = str(modelo).split("/")[-1]
                if nome and nome not in escolhidos:
                    escolhidos.append(nome)
        return escolhidos
    except Exception:
        return []


def disponivel(settings: Any) -> Dict[str, Any]:
    """Se dá para gerar imagem agora, e por quê não quando não dá."""
    chave = str(getattr(settings, "GEMINI_API_KEY", "") or "").split(",")[0].strip()
    escolhidos = modelos_de_imagem()
    if not chave:
        return {"ok": False, "motivo": "sem GEMINI_API_KEY configurada", "modelos": escolhidos}
    return {"ok": True, "modelos": escolhidos or [MODELO_PADRAO]}


def _imagens_da_resposta(dados: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extrai as imagens inline da resposta do Gemini."""
    saida: List[Dict[str, str]] = []
    for candidato in (dados.get("candidates") or []):
        for parte in ((candidato.get("content") or {}).get("parts") or []):
            inline = parte.get("inline_data") or parte.get("inlineData")
            if not isinstance(inline, dict):
                continue
            dado = inline.get("data")
            if not dado:
                continue
            mime = str(inline.get("mime_type") or inline.get("mimeType") or "image/png")
            saida.append({"mime": mime, "base64": str(dado)})
    return saida


async def gerar_imagem(prompt: str, settings: Any, modelo: Optional[str] = None) -> Dict[str, Any]:
    """Gera uma imagem a partir do texto. Nunca levanta."""
    import httpx

    pedido = limpar_marcador(prompt)
    if not pedido:
        return {"ok": False, "motivo": "pedido vazio depois de tirar o marcador"}

    estado = disponivel(settings)
    if not estado["ok"]:
        return {"ok": False, "motivo": estado["motivo"]}

    chave = str(getattr(settings, "GEMINI_API_KEY", "") or "").split(",")[0].strip()
    tentativas = [modelo] if modelo else (estado["modelos"] or [MODELO_PADRAO])
    inicio = time.time()
    ultimo_erro = ""

    async with httpx.AsyncClient(timeout=TIMEOUT) as cliente:
        for alvo in tentativas:
            try:
                resposta = await cliente.post(
                    GEMINI_URL.format(model=alvo),
                    headers={"x-goog-api-key": chave, "Content-Type": "application/json"},
                    json={"contents": [{"role": "user", "parts": [{"text": pedido}]}]},
                )
                resposta.raise_for_status()
                imagens = _imagens_da_resposta(resposta.json())
                if not imagens:
                    ultimo_erro = f"{alvo} respondeu sem imagem"
                    continue
                primeira = imagens[0]
                return {
                    "ok": True,
                    "modelo": alvo,
                    "prompt": pedido,
                    "mime": primeira["mime"],
                    "base64": primeira["base64"],
                    "bytes": len(base64.b64decode(primeira["base64"] + "===")),
                    "ms": int((time.time() - inicio) * 1000),
                }
            except httpx.HTTPStatusError as exc:
                # "HTTPStatusError" nao ajuda ninguem: quem le precisa saber se
                # foi cota, chave invalida ou modelo inexistente.
                codigo = exc.response.status_code
                detalhe = ""
                try:
                    detalhe = str((exc.response.json().get("error") or {}).get("message") or "")[:160]
                except Exception:
                    detalhe = exc.response.text[:160]
                if codigo == 429:
                    ultimo_erro = f"{alvo}: cota do provedor esgotada ({detalhe})"
                elif codigo in (401, 403):
                    ultimo_erro = f"{alvo}: credencial recusada ({detalhe})"
                elif codigo == 404:
                    ultimo_erro = f"{alvo}: modelo nao existe nesta conta"
                else:
                    ultimo_erro = f"{alvo}: HTTP {codigo} ({detalhe})"
                logger.info("Geracao de imagem falhou em %s: %s", alvo, ultimo_erro)
            except Exception as exc:
                ultimo_erro = f"{alvo}: {type(exc).__name__}"
                logger.info("Geracao de imagem falhou em %s: %s", alvo, exc)

    return {"ok": False, "motivo": ultimo_erro or "nenhum modelo de imagem respondeu"}
