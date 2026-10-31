"""Como este arquivo estava duas edições atrás.

O snapshot por conteúdo (`sentury/mutation/snapshot.py`) responde *"qual era
este conteúdo"*: o hash **é** a versão, e por isso mesmo não existe "mais
nova": dois arquivos idênticos são um hash só, e gravar o mesmo conteúdo duas
vezes não cria nada. Isso é exatamente o que se quer de um cofre de conteúdo, e
exatamente o que não responde a pergunta que o agente faz quando errou:

    "como este arquivo estava antes das minhas duas últimas edições?"

O Claude Code guarda `file-history/<sessão>/<hash-do-caminho>@v1,@v2,@v3`:
endereçado por **versão**, por arquivo, por sessão. As duas coisas não se
substituem, se completam: aqui mora a ordem, e o conteúdo continua morando lá.

Então este módulo não guarda bytes. Ele guarda uma linha por versão apontando
para o digest que o cofre já tem. A consequência é boa: uma edição que desfaz a
anterior volta ao mesmo hash e não ocupa nada, mas continua sendo a versão 3 na
linha do tempo: que é o que a pergunta acima precisa saber.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PASTA = "versoes"

# Acima disto não se guarda versão. O cofre não tem limite porque lá quem
# chama escolheu guardar; aqui a chamada é automática a cada escrita, e um
# dump de banco de 200 MB no meio de um turno encheria o disco sem ninguém
# pedir. O arquivo continua sendo editado: só não entra na linha do tempo.
MAX_BYTES = 4 * 1024 * 1024

# Quantas versões por arquivo por sessão. Passar disto não é histórico, é log:
# o interesse decai rápido, e as antigas continuam no cofre por hash.
MAX_VERSOES = 40


def pasta_das_versoes() -> Path:
    casa = os.environ.get("SENTURY_HOME") or str(Path.home() / ".sentury")
    return Path(casa) / PASTA


def _sessao(session_id: str = "") -> str:
    limpo = "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_")[:60]
    return limpo or "avulso"


def _indice(caminho: Path, session_id: str = "") -> Path:
    """Um arquivo de índice por arquivo por sessão.

    O nome é o hash do caminho absoluto, e não o caminho: `C:\\...` tem `:` e
    `\\`, que não sobrevivem a virar nome de arquivo. O caminho legível vai
    dentro de cada linha.
    """
    chave = hashlib.sha256(str(caminho).encode("utf-8")).hexdigest()[:16]
    return pasta_das_versoes() / _sessao(session_id) / f"{chave}.jsonl"


def _ler_indice(destino: Path) -> List[Dict[str, Any]]:
    try:
        cru = destino.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    saida = []
    for linha in cru:
        try:
            saida.append(json.loads(linha))
        except json.JSONDecodeError:
            continue
    return saida


def anotar(caminho: str | Path, *, session_id: str = "", por: str = "") -> Dict[str, Any]:
    """Registra o estado atual do arquivo como a próxima versão.

    Chamado nos dois lados de uma escrita: antes, para que a versão 1 seja o
    arquivo como o agente o encontrou, e depois, para que a 2 seja o resultado.
    Sem o "antes", a primeira versão registrada já seria a alterada: e o
    estado original, o único que ninguém pode reconstruir, seria o que se
    perde.

    Conteúdo repetido não vira versão nova: se o digest é igual ao da última,
    não houve alteração a registrar.
    """
    alvo = Path(caminho)
    if not alvo.is_file():
        return {"ok": False, "erro": f"nao e um arquivo: {alvo}"}
    try:
        tamanho = alvo.stat().st_size
    except OSError as exc:
        return {"ok": False, "erro": str(exc)}
    if tamanho > MAX_BYTES:
        return {"ok": False, "erro": f"grande demais para versionar ({tamanho} bytes)", "ignorado": True}

    # O cofre de conteúdo é um só. Escrever um segundo aqui dobraria o disco
    # para guardar os mesmos bytes, e faria "restaurar" significar duas coisas.
    from ..mutation import snapshot

    guardado = snapshot.guardar(alvo, nota=f"versao: {por}"[:200])
    if not guardado.get("ok"):
        return guardado
    digest = guardado["hash"]

    destino = _indice(alvo.resolve(), session_id)
    anteriores = _ler_indice(destino)
    if anteriores and anteriores[-1].get("hash") == digest:
        return {"ok": True, "versao": anteriores[-1].get("v"), "hash": digest, "nova": False}

    registro = {
        "v": len(anteriores) + 1,
        "hash": digest,
        "caminho": str(alvo.resolve()),
        "por": str(por or "")[:60],
        "em": time.time(),
        "bytes": tamanho,
    }
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as saida:
            saida.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Perder o histórico não pode derrubar a escrita: ele é o registro do
        # trabalho, não o trabalho.
        logger.warning("Nao consegui anotar a versao de %s: %s", alvo, exc)
        return {"ok": False, "erro": str(exc)}

    if len(anteriores) + 1 > MAX_VERSOES:
        _podar(destino)
    return {"ok": True, "versao": registro["v"], "hash": digest, "nova": True}


def _podar(destino: Path) -> None:
    """Descarta as linhas mais antigas mantendo o número da versão.

    O número não é reindexado de propósito: se a versão 3 foi citada numa
    resposta, ela não pode virar a 1 depois. Sumir é melhor que mentir.
    """
    linhas = _ler_indice(destino)[-MAX_VERSOES:]
    try:
        destino.write_text(
            "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in linhas),
            encoding="utf-8",
        )
    except OSError:
        pass


def versoes(caminho: str | Path, *, session_id: str = "") -> List[Dict[str, Any]]:
    """A linha do tempo do arquivo. Sem sessão, de todas as sessões em ordem."""
    alvo = Path(caminho).resolve()
    if session_id:
        return _ler_indice(_indice(alvo, session_id))

    raiz = pasta_das_versoes()
    if not raiz.is_dir():
        return []
    chave = hashlib.sha256(str(alvo).encode("utf-8")).hexdigest()[:16]
    juntas: List[Dict[str, Any]] = []
    for pasta in raiz.iterdir():
        if not pasta.is_dir():
            continue
        for linha in _ler_indice(pasta / f"{chave}.jsonl"):
            linha["sessao"] = pasta.name
            juntas.append(linha)
    juntas.sort(key=lambda x: x.get("em", 0))
    return juntas


def conteudo(caminho: str | Path, versao: int, *, session_id: str = "") -> Optional[bytes]:
    """O conteúdo exato de uma versão. `None` se ela não existe mais."""
    from ..mutation import snapshot

    for linha in versoes(caminho, session_id=session_id):
        if int(linha.get("v", 0)) == int(versao):
            return snapshot.ler(str(linha.get("hash", "")))
    return None


def diferenca(
    caminho: str | Path, de: int, para: int = 0, *, session_id: str = ""
) -> Dict[str, Any]:
    """O diff entre duas versões. `para=0` significa o arquivo como está agora.

    Comparar com o disco, e não só com a última versão anotada, é de propósito:
    alteração feita por fora (o usuário no editor, um `git checkout`) não
    passa por `anotar`, e é justamente ela que o agente precisa ver.
    """
    alvo = Path(caminho).resolve()
    antes = conteudo(alvo, de, session_id=session_id)
    if antes is None:
        return {"ok": False, "erro": f"versao {de} nao existe para este arquivo"}

    if para:
        depois = conteudo(alvo, para, session_id=session_id)
        rotulo = f"v{para}"
        if depois is None:
            return {"ok": False, "erro": f"versao {para} nao existe para este arquivo"}
    else:
        try:
            depois = alvo.read_bytes()
        except OSError as exc:
            return {"ok": False, "erro": str(exc)}
        rotulo = "agora"

    linhas = list(difflib.unified_diff(
        antes.decode("utf-8", errors="replace").splitlines(),
        depois.decode("utf-8", errors="replace").splitlines(),
        fromfile=f"{alvo.name}@v{de}", tofile=f"{alvo.name}@{rotulo}", lineterm="",
    ))
    return {
        "ok": True,
        "caminho": str(alvo),
        "de": f"v{de}", "para": rotulo,
        "diff": "\n".join(linhas[:600]),
        "igual": not linhas,
    }


def restaurar(
    caminho: str | Path, versao: int, *, session_id: str = ""
) -> Dict[str, Any]:
    """Escreve uma versão antiga de volta no arquivo.

    O estado atual é anotado antes, então desfazer também é desfazível: a
    restauração vira só mais uma versão na linha do tempo.
    """
    from ..mutation import snapshot

    alvo = Path(caminho).resolve()
    linha = next(
        (x for x in versoes(alvo, session_id=session_id) if int(x.get("v", 0)) == int(versao)),
        None,
    )
    if linha is None:
        return {"ok": False, "erro": f"versao {versao} nao existe para este arquivo"}

    if alvo.is_file():
        anotar(alvo, session_id=session_id, por="antes de restaurar")
    feito = snapshot.restaurar(str(linha.get("hash", "")), alvo, guardar_o_atual=False)
    if not feito.get("ok"):
        return feito
    depois = anotar(alvo, session_id=session_id, por=f"restaurado de v{versao}")
    return {
        "ok": True, "caminho": str(alvo),
        "restaurado_de": int(versao), "agora_e": depois.get("versao"),
    }


def tocados(session_id: str = "") -> List[Dict[str, Any]]:
    """Os arquivos que esta sessão alterou, e em quantas versões.

    Serve à pergunta do começo de turno ("o que eu já mexi aqui?") sem
    depender do `git status` da cópia, que não distingue o que foi o agente do
    que foi o usuário.
    """
    pasta = pasta_das_versoes() / _sessao(session_id)
    if not pasta.is_dir():
        return []
    saida = []
    for indice in sorted(pasta.glob("*.jsonl")):
        linhas = _ler_indice(indice)
        if not linhas:
            continue
        saida.append({
            "caminho": linhas[-1].get("caminho", ""),
            "versoes": len(linhas),
            "ultima": linhas[-1].get("v"),
            "em": linhas[-1].get("em", 0),
        })
    saida.sort(key=lambda x: x.get("em", 0), reverse=True)
    return saida


__all__ = [
    "anotar", "conteudo", "diferenca", "pasta_das_versoes",
    "restaurar", "tocados", "versoes",
]
