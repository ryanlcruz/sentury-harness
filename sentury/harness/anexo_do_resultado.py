"""O resultado da ferramenta vira o que o usuario ve.

Saiu de `_handle_message_inner`, onde eram 151 das 1.131 linhas. Nao e
orquestracao: e formatacao de saida, sandbox, export binario, ASCII e a
entrega que o setor declara.

A extracao so foi possivel porque o contrato de saida ja existia no codigo,
sem estar escrito: todo `break` vinha depois de setar `export_response`, e o
unico `continue` era o da reescrita. `tests/test_anexo_do_resultado.py`
travou isso ANTES da mudanca, e ja pegou um erro meu de contagem.
"""
from __future__ import annotations

import base64
import glob
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from robinbandit.sentury import is_ultra_active

from ..domains.do_setor import entregas as _entregas_do_setor

logger = logging.getLogger(__name__)

# Ferramentas de exportação binária
# Tipos e MIME vêm de uma fonte única para não divergir entre entregas.
def _extensoes_de_artefato() -> tuple:
    return tuple(_tipos_de_artefato())


def _artefatos() -> Dict[str, Any]:
    from ..policies import carregar

    return carregar("artefatos", {
        "tipos": {}, "export_binario": {},
    })

def _padroes_do_sandbox() -> tuple:
    return tuple(f"*.{ext}" for ext in _tipos_de_artefato())

def _tipos_de_artefato() -> Dict[str, str]:
    return {str(k): str(v) for k, v in (_artefatos().get("tipos") or {}).items()}

# As ajudantes moram aqui porque sao sobre FORMATO de saida: que
# extensao, que mime, que confirmacao: e nao sobre orquestracao. O
# orquestrador importa daqui: a dependencia fica numa direcao so.

def _export_binario() -> Dict[str, tuple]:
    """tool -> (extensão, mime), montado a partir do catálogo."""
    tipos = _tipos_de_artefato()
    saida = {}
    for tool, extensao in (_artefatos().get("export_binario") or {}).items():
        ext = str(extensao)
        saida[str(tool)] = (ext, tipos.get(ext, "application/octet-stream"))
    return saida


def _nota_para_conferir(anexo: Dict[str, Any]) -> str:
    """O que o modelo le junto do resultado quando o codigo gerou um arquivo."""
    onde = f" e ficou em {anexo['caminho']}" if anexo.get("caminho") else ""
    return (
        f"[ARQUIVO GERADO: '{anexo.get('filename')}' ({anexo.get('type')}) vai anexado a resposta{onde}. "
        "Antes de responder, confira se ele saiu como pedido, pelo que o codigo imprimiu ou lendo o "
        "arquivo. Se estiver errado, corrija e gere de novo: o novo substitui este. Na resposta, diga "
        "o que entregou, sem colar o conteudo do arquivo.]"
    )


def _extract_recent_sandbox_artifact(
    gerados: Optional[List[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Anexa o artefato que a execução criou.

    `gerados` é a lista que o sandbox devolve, e é o contrato inteiro: todo
    escritor passa por `_confined_path`, que registra o arquivo daquela execução.
    Não há varredura por "modificado nos últimos 10 segundos": essa janela
    entregava o arquivo de uma requisição para a outra quando duas rodavam
    juntas, e o arquivo certo nunca precisou dela.
    """
    recent_files: List[Tuple[Path, float]] = []

    if gerados:
        for bruto in gerados:
            path = Path(bruto)
            try:
                if path.is_file():
                    recent_files.append((path, path.stat().st_mtime))
            except OSError:
                continue

    if not recent_files:
        return None, None

    recent_files.sort(key=lambda item: item[1], reverse=True)
    file_path = recent_files[0][0]
    extension = file_path.suffix.lower().lstrip(".")

    try:
        content_bytes = file_path.read_bytes()
    except OSError as exc:
        logger.warning("Falha ao ler arquivo gerado no sandbox: %s", exc)
        return None, None

    attachment = {
        "type": extension,
        "filename": file_path.name,
        "mime_type": _tipos_de_artefato().get(extension, "application/octet-stream"),
        "content_base64": base64.b64encode(content_bytes).decode("ascii"),
        # A conversa guarda só este caminho; o cartão lê o arquivo do disco.
        "caminho": str(file_path),
    }

    if extension in {"svg", "html"}:
        try:
            text_payload = content_bytes.decode("utf-8")
        except Exception:
            text_payload = ""
        if extension == "svg":
            message = (
                "Aqui esta o diagrama (tambem disponivel para baixar):\n\n"
                f"```svg\n{text_payload}\n```"
            )
        else:
            # O arquivo segue no attachment. Repetir seu HTML aqui expõe um
            # payload grande ao histórico/LLM e pode duplicar a resposta.
            message = "Pronto — gerei o artefato HTML. Ele está no card abaixo para abrir ou baixar."
        return attachment, message

    return attachment, f"Pronto - gerei o arquivo '{file_path.name}' e anexei a esta resposta. E so baixar."


from ..tools.registry import com_propriedade


async def anexo_do_resultado(
    tool: str,
    arguments: dict,
    result,
    state,
    anexos_do_turno: list,
    validar_html=None,
) -> tuple:
    """Transforma o resultado de uma ferramenta no que o usuario recebe.

    Quatro caminhos: o sandbox (arquivo gerado por script), o export
    binario, o ASCII e a entrega declarada pelo setor. Nenhum deles e
    orquestracao (e formatacao de saida) e juntos eram 151 das 1.131
    linhas do laco do turno.

    O RETORNO E UM CONTRATO, e e a parte delicada. No laco isto eram seis
    `break` e um `continue`, que controlavam o `for` de fora; funcao nao
    quebra o laco de quem a chamou. Entao:

        ("parar", anexo, resposta)  o turno tem o que entregar; o `for` para
        ("anexar", anexo, nota)     o anexo vai com a resposta, e o resultado
                                    volta ao modelo com a `nota` para ele
                                    conferir o arquivo antes de responder
        ("seguir", None, None)      vai para o proximo passo do plano
        ("encerrar", None, texto)   o resto do plano roda, mas o modelo nao e
                                    chamado de novo: `texto` fecha o turno
        ("nada", None, None)        esta ferramenta nao produz anexo

    Confundir "parar" com "seguir" faz o turno continuar quando deveria
    encerrar, e e o erro mais caro possivel aqui. `anexos_do_turno` e
    mutada de proposito: a lista e do turno, nao deste passo.
    """
    attachment = None
    export_response = None

    # Detecção automática de novos arquivos gerados no sandbox
    if tool == "executar_python":
        sandbox_attachment, sandbox_message = _extract_recent_sandbox_artifact(
            (result or {}).get("arquivos_gerados")
            if isinstance(result, dict) else None)
        if sandbox_attachment:
            # Loop de construção: se o HTML autoral quebrou ao
            # renderizar, tenta consertar antes de mostrar.
            if sandbox_attachment.get("type") == "html" and validar_html is not None:
                sandbox_attachment = await validar_html(sandbox_attachment)
            attachment = sandbox_attachment
            # O arquivo nao encerra mais o turno: o modelo confere antes de
            # entregar. Gerou de novo (corrigindo), o novo substitui o anterior.
            attachment["gerado_no_turno"] = True
            anexos_do_turno[:] = [a for a in anexos_do_turno if not a.get("gerado_no_turno")]
            anexos_do_turno.append(attachment)
            logger.info(
                "Detectado arquivo gerado pelo sandbox: %s. Volta ao modelo para conferir.",
                attachment["filename"],
            )
            # A nota vai dentro do resultado, que e o que o modelo le a seguir.
            nota = _nota_para_conferir(attachment)
            if isinstance(result, dict):
                result["conferir_o_arquivo"] = nota
            return "anexar", attachment, nota
        # Nao varremos o disco atras de arquivo recente: `arquivos_gerados`
        # e o contrato, e todo escritor do sandbox passa por `_confined_path`.
        # A varredura por mtime entregava o artefato de uma requisicao para
        # outra quando duas rodavam juntas.

    # Exportação: o arquivo vai para a pasta de entregas e volta ao modelo, que
    # confere e escreve a resposta, como o arquivo gerado por script.
    if tool in _export_binario():
        from ..artifacts.destino import caminho_livre

        source = state.resolve_source(arguments.get("source"))
        ext, mime = _export_binario()[tool]
        dados = result["png_bytes"] if tool == "generate_chart" else result
        destino = caminho_livre(f"{source or 'resultado'}.{ext}")
        destino.write_bytes(dados)
        attachment = {
            "type": "chart_json" if tool == "generate_chart" else ext,
            "filename": destino.name,
            "mime_type": mime,
            "content_base64": base64.b64encode(dados).decode("ascii"),
            "caminho": str(destino),
        }
        if tool == "generate_chart":
            attachment["chart_data"] = result["chart_data"]
        anexos_do_turno.append(attachment)
        return "anexar", attachment, _nota_para_conferir(attachment)

    # Ferramenta que encerra o turno quando da certo (declarado no tools.yaml): o que ela
    # fez ja e o fim do trabalho, e voltar ao modelo so produziria uma narracao a mais.
    if (tool in com_propriedade("encerra_o_turno") and isinstance(result, dict)
            and result.get("ok")):
        return "encerrar", None, str(result.get("resposta") or result.get("proximo_passo") or "")

    # Ferramenta cuja SAIDA e a entrega: o markdown dela vai
    # para a conversa, em vez de virar contexto para o modelo
    # redigir por cima. QUAIS sao e como cada uma se entrega
    # vem do pacote do setor: o motor so conhece a classe.
    entrega = _entregas_do_setor().get(tool)
    if entrega and isinstance(result, dict) and result.get("markdown"):
        reescrita = entrega.get("reescrita")
        from robinbandit.sentury import is_ultra_active

        if reescrita and is_ultra_active():
            # Alvo forte: o modelo reescreve a partir do
            # esqueleto, que ja tem os numeros reais. Sem alvo
            # forte nao se pede reescrita: modelo fraco
            # inventava meta onde o esqueleto nao tinha.
            state.history.append({
                "role": "system",
                "content": reescrita.replace("{markdown}", result["markdown"]),
            })
            return "seguir", None, None
        if entrega.get("arquivo"):
            attachment = {
                "type": "markdown",
                "filename": entrega["arquivo"],
                "mime_type": "text/markdown",
                "content": result["markdown"],
                "title": entrega.get("titulo") or entrega["arquivo"],
            }
            export_response = entrega.get("aviso") or (
                f"Pronto — {entrega.get('titulo') or 'o documento'} esta pronto."
            )
            return "parar", attachment, export_response
        export_response = result["markdown"]
        return "parar", attachment, export_response

    return "nada", None, None
