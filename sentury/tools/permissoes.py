"""Permissão para o que muda alguma coisa.

Leitura sempre pôde. O resto (escrever arquivo, instalar pacote, mexer no
git) passa por uma decisão de quem é dono da máquina, e a decisão fica
registrada para não ser perguntada de novo à toa.

Quatro respostas, que é o vocabulário que já existe em ferramentas do gênero:

- **sessão**: vale até a conversa acabar. O padrão para "sim, agora".
- **sempre**: grava no disco; aquele comando não pergunta mais.
- **uma vez**: roda e volta a perguntar na próxima.
- **negar**: não roda AGORA. Nada é gravado: dizer "não" a um comando neste
  momento não é a mesma coisa que bani-lo, e transformar um clique em bloqueio
  permanente faz a pessoa hesitar justamente na opção mais segura.
- **negar sempre**: aí sim entra na lista de bloqueados, e sai de lá pela tela
  de permissões.

Existe também o modo "permitir tudo", para quem não quer ser interrompido.
Ele é explícito e aparece nas configurações: uma permissão que se liga sem
querer não é permissão.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

# Vale enquanto o processo vive. Sessão é memória, não arquivo.
_DA_SESSAO: Dict[str, Dict[str, float]] = {}
# "Só desta vez" precisa valer uma vez: sem este credito ele nao gravava nada,
# a proxima avaliacao perguntava de novo e a autorizacao virava um laco.
_CREDITO_UNICO: Dict[str, Dict[str, float]] = {}

RESPOSTAS = ("uma_vez", "sessao", "sempre", "negar", "negar_sempre")


def caminho_do_registro() -> Path:
    home = os.environ.get("SENTURY_HOME") or str(Path.home() / ".sentury")
    return Path(home) / "permissoes.json"


def _carregar() -> Dict[str, Any]:
    caminho = caminho_do_registro()
    if not caminho.exists():
        return {"sempre": [], "negados": [], "permitir_tudo": False}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {"sempre": [], "negados": [], "permitir_tudo": False}
    return {
        "sempre": [str(item) for item in (dados.get("sempre") or [])],
        "negados": [str(item) for item in (dados.get("negados") or [])],
        "permitir_tudo": bool(dados.get("permitir_tudo")),
    }


def _gravar(dados: Dict[str, Any]) -> None:
    caminho = caminho_do_registro()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(caminho)


def _com_subcomando() -> set:
    """Programas cujo primeiro argumento e um verbo. Vem da politica de shell,
    para nao existir a mesma lista escrita em dois lugares."""
    try:
        from .shell import politica

        return {str(item) for item in (politica().get("com_subcomando") or [])}
    except Exception:
        return set()


def _de_execucao() -> set:
    """Programas cuja permissao e por conteudo, nao por verbo."""
    try:
        from .shell import comandos_de_execucao

        return {str(item) for item in comandos_de_execucao()}
    except Exception:
        return set()


def _impressao_do_script(partes: List[str]) -> str:
    """Identifica o script pelo CONTEUDO, nao pelo caminho.

    Interpretador nao tem verbo: `python a.py` e `python b.py` sao decisoes
    diferentes, e `python a.py` depois de reescrever o `a.py` tambem e. Aprovar
    o caminho deixaria o arquivo ser trocado por baixo da autorizacao, que e o
    furo que a assinatura por programa ja tinha.
    """
    alvo = next((item for item in partes[1:] if not item.startswith("-")), "")
    if not alvo:
        # Sem script nomeado (ex.: `python -c ...`): a linha inteira e o conteudo.
        corpo = " ".join(partes[1:]).encode("utf-8", "replace")
        return hashlib.sha256(corpo).hexdigest()[:12]
    try:
        bruto = Path(alvo).expanduser().resolve().read_bytes()
    except OSError:
        # Script ilegivel ainda precisa de uma chave estavel para a pergunta.
        return "ausente"
    # Normaliza fim de linha para o mesmo script nao virar duas decisoes so
    # por ter passado por um editor do Windows.
    return hashlib.sha256(bruto.replace(b"\r\n", b"\n")).hexdigest()[:12]


def _assinatura_comum(comando: str) -> str:
    """O que a permissão cobre: programa e subcomando, não a linha inteira.

    Autorizar `git commit -m "a"` e ter que autorizar de novo por causa da
    mensagem transformaria a permissão em ruído, e ruído se aprova no
    automático. Autorizar `git` inteiro seria largo demais.
    """
    from .shell import partes_do_comando

    try:
        partes = partes_do_comando(str(comando or ""))
    except ValueError:
        partes = str(comando or "").split()
    if not partes:
        return ""
    programa = Path(partes[0]).name.lower()
    programa = programa[:-4] if programa.endswith(".exe") else programa
    # Só onde o primeiro argumento é um VERBO ele entra na assinatura:
    # `git commit` e `git push` são decisões diferentes, enquanto `mkdir a` e
    # `mkdir b` são a mesma ("deixar criar pasta").
    if programa in _de_execucao():
        alvo = next((item for item in partes[1:] if not item.startswith("-")), "")
        nome = Path(alvo).name if alvo else "-c"
        return f"{programa} {nome}#{_impressao_do_script(partes)}"
    if programa not in _com_subcomando():
        return programa
    from .shell import partes_do_comando, verbo

    return f"{programa} {verbo(partes_do_comando(comando))}".strip()


def _partes(comando: str) -> List[str]:
    from .shell import partes_do_comando

    try:
        return partes_do_comando(str(comando or ""))
    except ValueError:
        return str(comando or "").split()


def _e_script(comando: str) -> bool:
    partes = _partes(comando)
    if not partes:
        return False
    programa = Path(partes[0]).name.lower()
    return (programa[:-4] if programa.endswith(".exe") else programa) in _de_execucao()


def _chave_de_scripts() -> str:
    """Os scripts desta conversa na pasta de trabalho de agora: trocar de pasta
    no meio da conversa volta a perguntar."""
    from .arquivos import raiz_de_trabalho

    return f"scripts@{raiz_de_trabalho()}"


def _apaga(comando: str) -> bool:
    """O script apaga alguma coisa? Esse continua perguntando um a um, porque
    apagar não se desfaz pela versão do arquivo."""
    import re

    from ..exec.criticas import _conteudo
    from .shell import politica

    tabela = politica()
    corpo = _conteudo(_partes(comando), tabela) or ""
    padroes = tabela.get("script_que_apaga") or []
    return any(re.search(str(p), corpo, re.IGNORECASE) for p in padroes)


def assinatura(comando: str) -> str:
    from ..exec.criticas import identidade, motivo

    comum = _assinatura_comum(comando)
    # A aprovação de um alvo crítico não libera outro argumento do mesmo verbo.
    return f"{comum}#{identidade(comando)}" if motivo(comando) else comum


def estado() -> Dict[str, Any]:
    """O que está autorizado hoje, para a tela de configurações."""
    dados = _carregar()
    with _LOCK:
        sessao = sorted({chave for sessoes in _DA_SESSAO.values() for chave in sessoes})
    return {
        "permitir_tudo": dados["permitir_tudo"],
        "sempre": sorted(dados["sempre"]),
        "negados": sorted(dados["negados"]),
        "sessao": sessao,
        "registro": str(caminho_do_registro()),
    }


def definir_permitir_tudo(ligado: bool) -> Dict[str, Any]:
    with _LOCK:
        dados = _carregar()
        dados["permitir_tudo"] = bool(ligado)
        _gravar(dados)
    return estado()


def esquecer(chave: str) -> Dict[str, Any]:
    """Tira uma autorização de 'sempre' ou uma negativa."""
    alvo = str(chave or "").strip()
    with _LOCK:
        dados = _carregar()
        dados["sempre"] = [item for item in dados["sempre"] if item != alvo]
        dados["negados"] = [item for item in dados["negados"] if item != alvo]
        _gravar(dados)
        for sessoes in _DA_SESSAO.values():
            sessoes.pop(alvo, None)
    return estado()


def responder(comando: str, resposta: str, session_id: str = "") -> Dict[str, Any]:
    """Registra a decisão de quem foi perguntado."""
    chave = assinatura(comando)
    escolha = str(resposta or "").strip().lower()
    if not chave:
        raise ValueError("comando vazio")
    if escolha not in RESPOSTAS:
        raise ValueError(f"resposta deve ser uma de {', '.join(RESPOSTAS)}")

    with _LOCK:
        dados = _carregar()
        if escolha == "sempre":
            if chave not in dados["sempre"]:
                dados["sempre"].append(chave)
            dados["negados"] = [item for item in dados["negados"] if item != chave]
            _gravar(dados)
        elif escolha == "negar_sempre":
            if chave not in dados["negados"]:
                dados["negados"].append(chave)
            dados["sempre"] = [item for item in dados["sempre"] if item != chave]
            _gravar(dados)
        # "acessar_pasta X" nao e um comando: a resposta libera a pasta de
        # verdade, senao o proximo passo bate na mesma parede.
        if escolha in ("sempre", "sessao", "uma_vez") and comando.startswith("acessar_pasta "):
            from .arquivos import liberar_pasta

            liberar_pasta(comando[len("acessar_pasta "):].strip())

        if escolha == "uma_vez":
            _CREDITO_UNICO.setdefault(session_id or "global", {})[chave] = time.time()
        elif escolha == "negar":
            # Recusa pontual: não grava nada. O comando não roda neste turno e
            # na próxima vez a pergunta volta a ser feita.
            pass
        elif escolha == "sessao":
            da_sessao = _DA_SESSAO.setdefault(session_id or "global", {})
            da_sessao[chave] = time.time()
            # Cada script tem conteúdo novo e seria uma pergunta nova; quem está
            # criando código aprova os scripts da conversa de uma vez.
            if _e_script(comando):
                da_sessao[_chave_de_scripts()] = time.time()
    return {"chave": chave, "resposta": escolha, "estado": estado()}


def avaliar(
    comando: str, session_id: str = "", *, consumir: bool = True, na_hora: bool = False,
) -> Dict[str, Any]:
    """Se este comando pode rodar agora, e por quê.

    `precisa_perguntar` é o caso em que a interface levanta a pergunta; o
    agente não decide sozinho o que fazer com ele. `consumir=False` é para
    quem só consulta antes de executar: gastar o crédito de "só desta vez"
    ali fazia a execução perguntar de novo.

    `na_hora=True` é a ação que se confirma sempre na hora (candidatura,
    envio de dado): só o crédito de "só desta vez" libera. "Permitir tudo",
    "sempre" e "nesta conversa" não valem para ela.
    """
    from ..exec.criticas import motivo as motivo_critico

    critico = motivo_critico(comando)
    na_hora = na_hora or bool(critico)
    chave = assinatura(comando)
    dados = _carregar()
    extra = {"so_desta_vez": True} if na_hora else {}

    if chave in dados["negados"] or _assinatura_comum(comando) in dados["negados"]:
        return {"permitido": False, "precisa_perguntar": False, "chave": chave,
                "motivo": f"'{chave}' foi negado por você antes", **extra}
    if dados["permitir_tudo"] and not na_hora:
        return {"permitido": True, "precisa_perguntar": False, "chave": chave,
                "motivo": "modo 'permitir tudo' está ligado"}
    if chave in dados["sempre"] and not na_hora:
        return {"permitido": True, "precisa_perguntar": False, "chave": chave,
                "motivo": f"'{chave}' está autorizado sempre"}
    with _LOCK:
        da_sessao = _DA_SESSAO.get(session_id or "global", {})
        if chave in da_sessao and not na_hora:
            return {"permitido": True, "precisa_perguntar": False, "chave": chave,
                    "motivo": f"'{chave}' foi autorizado nesta conversa"}
        if (not na_hora and _e_script(comando) and _chave_de_scripts() in da_sessao
                and not _apaga(comando)):
            return {"permitido": True, "precisa_perguntar": False, "chave": chave,
                    "motivo": "os scripts desta pasta foram autorizados nesta conversa"}
        # O credito de "só desta vez" vale uma vez e some ao ser usado.
        creditos = _CREDITO_UNICO.get(session_id or "global", {})
        if chave in creditos:
            if consumir:
                creditos.pop(chave, None)
            return {"permitido": True, "precisa_perguntar": False, "chave": chave,
                    "motivo": f"'{chave}' foi autorizado para esta vez", **extra}
    # O cartão diz o que "nesta conversa" cobre quando é script.
    if _e_script(comando) and not na_hora and not _apaga(comando):
        extra = {**extra, "nesta_conversa": "scripts"}
    return {"permitido": False, "precisa_perguntar": True, "chave": chave,
            "motivo": critico or f"'{chave}' altera alguma coisa e ainda não foi autorizado", **extra}


def limpar_sessao(session_id: str) -> None:
    with _LOCK:
        _DA_SESSAO.pop(session_id or "global", None)
        _CREDITO_UNICO.pop(session_id or "global", None)
