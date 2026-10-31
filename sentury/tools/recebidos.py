"""Arquivo que a pessoa anexa no chat entra no turno já lido.

Antes, o que não era imagem nem texto chegava como `[anexados sem leitura:
curriculo.pdf]`: só o nome. E o texto dos anexos ia colado dentro da mensagem,
que tem teto de 2.000 caracteres, então um `.txt` de duas páginas dava 422.

Anexo não passa por `ler_arquivo`: essa ferramenta é para o que o agente acha
ou para o arquivo que a pessoa aponta numa pasta. Quem anexou já entregou o
arquivo, então o harness lê na chegada (PDF, DOCX e planilha viram Markdown
pelo MarkItDown) e o conteúdo entra no turno com fronteira de texto de
terceiro. O arquivo fica no rascunho da sessão para o agente reusar depois.
"""
from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from typing import Iterable, List, Mapping

from .arquivos import CONVERTIVEIS, _converter, casa_do_sentury, pasta_de_rascunho

_TETO_BYTES = 8 * 1024 * 1024
# O que entra no turno de cada anexo. Currículo e contrato cabem; o resto fica
# no arquivo, e o agente sabe onde.
_TETO_CARACTERES = 20_000


def _nome_seguro(nome: str) -> str:
    base = Path(str(nome or "arquivo").replace("\\", "/")).name
    limpo = re.sub(r"[^\w.\- ]+", "_", base).strip(" .") or "arquivo"
    return limpo[:120]


_PODA_NO_MAXIMO_A_CADA_S = 24 * 3600


def _dias_de_recebido() -> int:
    try:
        from ..config import settings

        return int(getattr(settings, "SENTURY_RECEBIDOS_DIAS", 30))
    except Exception:
        return 30


def podar(dias: int | None = None, *, agora: float | None = None) -> int:
    """Apaga anexo recebido mais velho que o prazo, em todas as sessoes.

    So `recebidos/`: o anexo ja foi lido no turno em que chegou, e o texto dele
    esta no historico. O resto do rascunho fica: e onde mora o que o agente
    entregou, e conversa antiga aponta para la. Devolve quantos saíram.
    """
    import time

    dias = _dias_de_recebido() if dias is None else int(dias)
    if dias <= 0:
        return 0
    corte = (time.time() if agora is None else agora) - dias * 86400
    base = casa_do_sentury() / "rascunho"
    apagados = 0
    for pasta in base.glob("*/recebidos"):
        for arquivo in pasta.iterdir():
            try:
                if arquivo.is_file() and arquivo.stat().st_mtime < corte:
                    arquivo.unlink()
                    apagados += 1
            except OSError:
                continue
        try:
            pasta.rmdir()  # so se ficou vazia
        except OSError:
            pass
    return apagados


def podar_se_preciso(*, agora: float | None = None) -> int | None:
    """Uma vez por dia, na chegada de um anexo. Custa um `stat` nas outras."""
    import time

    agora = time.time() if agora is None else agora
    marca = (casa_do_sentury() / "rascunho") / ".ultima_poda_de_recebidos"
    try:
        ultima = float(marca.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        ultima = 0.0
    if agora - ultima < _PODA_NO_MAXIMO_A_CADA_S:
        return None
    apagados = podar(agora=agora)
    try:
        marca.write_text(str(agora), encoding="utf-8")
    except OSError:
        pass
    return apagados


def guardar(session_id: str, arquivos: Iterable[Mapping[str, str]]) -> List[Path]:
    """Grava cada anexo em `<rascunho da sessão>/recebidos/`. Devolve os caminhos."""
    try:
        podar_se_preciso()
    except Exception:
        pass  # limpeza nunca impede o anexo de chegar
    pasta = pasta_de_rascunho(session_id) / "recebidos"
    pasta.mkdir(parents=True, exist_ok=True)
    gravados: List[Path] = []
    for item in arquivos or []:
        data_url = str(item.get("data_url") or "")
        _, _, corpo = data_url.partition(",")
        try:
            conteudo = base64.b64decode(corpo, validate=True)
        except (binascii.Error, ValueError):
            continue
        if not conteudo or len(conteudo) > _TETO_BYTES:
            continue
        alvo = pasta / _nome_seguro(item.get("nome", ""))
        # Mesmo nome com outro conteúdo: numera em vez de sobrescrever.
        n = 1
        while alvo.exists() and alvo.read_bytes() != conteudo:
            alvo = alvo.with_name(f"{alvo.stem} ({n}){alvo.suffix}")
            n += 1
        alvo.write_bytes(conteudo)
        gravados.append(alvo)
    return gravados


def texto_do_anexo(caminho: Path) -> str:
    """O texto do arquivo, ou uma frase dizendo por que não há texto."""
    if caminho.suffix.lower() in CONVERTIVEIS:
        return _converter(caminho) or "(não consegui extrair texto deste arquivo)"
    try:
        return caminho.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "(arquivo binário sem texto extraível)"
    except OSError as exc:
        return f"(não consegui abrir: {exc})"


def bloco_do_turno(caminhos: List[Path]) -> str:
    """O conteúdo dos anexos para o turno, cada um com fronteira de terceiro."""
    from ..llm.prompts import envelope_de_terceiros

    partes = []
    for caminho in caminhos:
        texto = texto_do_anexo(caminho)
        cortado = len(texto) > _TETO_CARACTERES
        corpo = texto[:_TETO_CARACTERES]
        cabeca = f"ANEXO DA PESSOA: {caminho.name} (arquivo em {caminho})"
        if cortado:
            cabeca += f"; mostrando {_TETO_CARACTERES} de {len(texto)} caracteres, o resto está no arquivo"
        partes.append(f"{cabeca}\n{envelope_de_terceiros(corpo)}")
    return "\n\n".join(partes)


def linha_para_a_mensagem(caminhos: List[Path]) -> str:
    if not caminhos:
        return ""
    return "\n\n[anexos: " + ", ".join(c.name for c in caminhos) + "]"


def entregar_ao_turno(state, session_id: str, imagens: Iterable[Mapping[str, str]],
                      arquivos: Iterable[Mapping[str, str]]) -> List[Path]:
    """O que a pessoa anexou entra no turno pelo mesmo caminho em todo canal: a imagem
    vai ao modelo que enxerga, o arquivo é lido na chegada, e os dois viram artefato.
    Cada item é `{"nome", "data_url"}`. Devolve os caminhos dos arquivos gravados."""
    from ..artifacts import imagens_recebidas

    imagens = [dict(i) for i in imagens or [] if str(i.get("data_url") or "").startswith("data:image/")]
    if imagens:
        state.imagens_do_turno = imagens
        imagens_recebidas.guardar(state, imagens)
    arquivos = [dict(a) for a in arquivos or []]
    if not arquivos:
        return []
    caminhos = guardar(session_id, arquivos)
    imagens_recebidas.guardar_arquivos(state, arquivos)
    if caminhos:
        state.history.append({"role": "system", "content": bloco_do_turno(caminhos), "priority": "HIGH"})
    return caminhos


__all__ = ["bloco_do_turno", "entregar_ao_turno", "guardar", "linha_para_a_mensagem", "texto_do_anexo"]
