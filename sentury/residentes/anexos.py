"""O anexo acompanha a tarefa; seu conteúdo só entra pela ferramenta de leitura."""
import asyncio
import base64
import binascii
import json
from pathlib import Path

from pydantic import BaseModel, Field

from ..artifacts.arquivo_anexado import ArquivoAnexado
from ..artifacts.imagens_recebidas import _DATA_URL, guardar_arquivos
from ..tools.recebidos import _TETO_BYTES, guardar, linha_para_a_mensagem
from . import hq


class PedidoNaConversa(BaseModel):
    pedido: str = Field(min_length=1, max_length=8000)
    user_id: str = Field(min_length=1, max_length=128, pattern=r"^[^:]+$")
    arquivos: list[ArquivoAnexado] = Field(default_factory=list, max_length=6)


def _validar(arquivos):
    for arquivo in arquivos:
        dado = _DATA_URL.fullmatch(arquivo["data_url"])
        if not dado:
            raise ValueError("O anexo não tem um formato válido.")
        try:
            conteudo = base64.b64decode(dado.group(2), validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Não consegui decodificar o anexo.") from None
        if not conteudo or len(conteudo) > _TETO_BYTES:
            raise ValueError("O anexo precisa ter conteúdo e no máximo 8 MB.")


async def enviar(nome, corpo):
    agente = hq.ver(nome)
    if agente["estado"] == "aposentado":
        raise ValueError("O residente está aposentado.")
    arquivos = [a.model_dump() for a in corpo.arquivos]
    if not arquivos:
        return hq.pedir(nome, corpo.pedido, f"conversa:{corpo.user_id}:agente:{nome}")
    if "ler_arquivo" not in agente["ferramentas"]:
        raise ValueError("Este residente não tem ler_arquivo. Libere a ferramenta na ficha antes de enviar anexos.")
    _validar(arquivos)
    from ..main import _load_state, _persist_state, trava_da_sessao

    sessao = hq.sessao_do(nome)
    async with trava_da_sessao.da(sessao):
        caminhos = await asyncio.to_thread(guardar, sessao, arquivos)
        if len(caminhos) != len(arquivos):
            raise ValueError("Não consegui guardar todos os anexos; a tarefa não foi enviada.")
        _, state = await _load_state(sessao, "hq")
        guardar_arquivos(state, arquivos)
        await _persist_state(state)
    anexos = [{"nome": c.name, "caminho": str(c)} for c in caminhos]
    return hq.pedir(nome, corpo.pedido, f"conversa:{corpo.user_id}:agente:{nome}", anexos=anexos)


def nomes_na_mensagem(tarefa):
    return linha_para_a_mensagem([Path(a["nome"]) for a in tarefa.anexos])


async def contexto_dos_anexos(agente, tarefa):
    if not tarefa.anexos:
        return ""
    if "ler_arquivo" not in agente.ferramentas:
        return "\n\nOs anexos desta tarefa não foram lidos: ler_arquivo não está no manifesto."
    from . import caixa
    from .destino import caixa_obrigatoria
    from ..tools.arquivos import pasta_de_rascunho
    from ..llm.prompts import envelope_de_terceiros

    raiz = (pasta_de_rascunho(hq.sessao_do(agente.nome)) / "recebidos").resolve()
    anexos = []
    docker = await asyncio.to_thread(caixa.disponivel)
    if not docker and caixa_obrigatoria():
        raise ValueError("A caixa está indisponível; os anexos não foram enviados para execução na HQ.")
    for anexo in tarefa.anexos:
        origem = Path(anexo["caminho"]).resolve()
        if not origem.is_relative_to(raiz) or not origem.is_file():
            raise ValueError("O anexo não está na pasta de recebidos desta conversa.")
        if docker:
            destino = f"/workspace/recebidos/{tarefa.id}/{origem.name}"
            await asyncio.to_thread(caixa.receber_anexo, agente, origem, destino)
        else:
            destino = str(origem)
        anexos.append({"nome": origem.name, "caminho": destino})
    return "\n\nArquivos anexados à tarefa, disponíveis para ler_arquivo:\n" + envelope_de_terceiros(json.dumps(anexos, ensure_ascii=False))
