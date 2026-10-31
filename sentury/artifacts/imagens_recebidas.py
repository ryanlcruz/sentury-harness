"""Preserva o anexo da pessoa fora do histórico enviado ao modelo."""
import base64
import binascii
import re
from pathlib import PureWindowsPath


_DATA_URL_DE_IMAGEM = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", re.DOTALL)
# Arquivo de qualquer tipo: o navegador às vezes não sabe o mime e manda vazio.
_DATA_URL = re.compile(r"^data:([a-zA-Z0-9.+/-]*)(?:;[^,;]*)*;base64,(.+)$", re.DOTALL)
# O mesmo teto da pasta de recebidos: acima disso o anexo já não chega ao turno.
_TETO_BYTES = 8 * 1024 * 1024


def _decodificar(corpo: str):
    try:
        conteudo = base64.b64decode("".join(corpo.split()), validate=True)
    except (binascii.Error, ValueError):
        return None
    return conteudo or None


def _nome(bruto, padrao: str) -> str:
    nome = PureWindowsPath(str(bruto or padrao)).name or padrao
    return re.sub(r"[\x00-\x1f\x7f]", "", nome)[:200] or padrao


def _preservar(state, nome: str, mime: str, tipo: str, conteudo: bytes) -> None:
    anexo = {
        "type": tipo, "title": nome, "filename": nome, "mime_type": mime,
        "content_base64": base64.b64encode(conteudo).decode("ascii"), "origem": "anexo_da_pessoa",
    }
    # Uma nova tentativa do mesmo envio reutiliza o artefato já guardado.
    if any(registro.get("attachment") == anexo for registro in state.artifacts.values()
           if isinstance(registro, dict)):
        return
    state.store_artifact(anexo)


def guardar(state, imagens) -> None:
    for imagem in imagens:
        match = _DATA_URL_DE_IMAGEM.fullmatch(str(imagem.get("data_url") or ""))
        if not match:
            continue
        mime, corpo = match.groups()
        conteudo = _decodificar(corpo)
        if not conteudo:
            continue
        mime = mime.lower()
        _preservar(state, _nome(imagem.get("nome"), "imagem"), mime,
                   mime.split("/", 1)[1].split("+", 1)[0], conteudo)


def guardar_arquivos(state, arquivos) -> None:
    """PDF, planilha, texto e o resto entram na biblioteca como a imagem entra.
    O tipo vem da extensão do nome, que é o que a pessoa reconhece na lista."""
    for arquivo in arquivos:
        match = _DATA_URL.fullmatch(str(arquivo.get("data_url") or ""))
        if not match:
            continue
        mime, corpo = match.groups()
        conteudo = _decodificar(corpo)
        if not conteudo or len(conteudo) > _TETO_BYTES:
            continue
        nome = _nome(arquivo.get("nome"), "arquivo")
        mime = (mime or "application/octet-stream").lower()
        extensao = nome.rsplit(".", 1)[1].lower() if "." in nome else ""
        tipo = extensao if re.fullmatch(r"[a-z0-9]{1,8}", extensao) else mime.split("/", 1)[-1].split("+", 1)[0]
        _preservar(state, nome, mime, tipo or "arquivo", conteudo)
