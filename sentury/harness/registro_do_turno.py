"""Registra o andamento do turno em disco, separado do histórico da sessão.

Cada passo concluído é um checkpoint atômico. Após reinício do servidor, um
turno interrompido oferece continuação ao usuário; a corrotina não é retomada
automaticamente. Pausas de aprovação e pergunta mantêm sua pendência própria.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Motivos de término. `rodando` não é motivo: é o status de quem não terminou.
CONCLUIDO = "concluido"
PARADO = "parado_pela_pessoa"
CONEXAO_CAIU = "conexao_caiu"
FALHA = "falha"
ESPERANDO_APROVACAO = "esperando_aprovacao"
ESPERANDO_RESPOSTA = "esperando_resposta"
REINICIO = "reinicio"

_DO_LACO = {"budget_exhausted": "orcamento", "tool_failure": "falha_de_ferramenta",
            "repetition_detected": "repeticao", "insufficient_data": "dados_insuficientes"}
TETO_DE_ARGUMENTO = 80
TETO_DE_PASSOS = 200

_trava = threading.Lock()
_abertos: Dict[str, Dict[str, Any]] = {}


def pasta() -> Path:
    from ..config import settings
    from ..memory.local_session_store import default_sentury_home

    return default_sentury_home(str(getattr(settings, "SENTURY_HOME", "") or "")) / "state" / "turnos"


def _arquivo(sessao: str) -> Path:
    seguro = re.sub(r"[^A-Za-z0-9_.-]", "_", str(sessao))[:120] or "_"
    return pasta() / f"{seguro}.json"


def _gravar(registro: Dict[str, Any]) -> None:
    registro["atualizado_em"] = time.time()
    destino = _arquivo(registro["sessao"])
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(f".{os.getpid()}.tmp")
        temporario.write_text(json.dumps(registro, ensure_ascii=False), encoding="utf-8")
        os.replace(temporario, destino)
    except OSError:
        logger.warning("Registro do turno de %s não foi gravado.", registro["sessao"], exc_info=True)


def ler(sessao: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_arquivo(sessao).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _resumir(argumentos: Any) -> Dict[str, str]:
    """Os argumentos curtos: o bastante para saber o que o passo fez, sem
    copiar conteúdo de arquivo ou código para o registro."""
    if not isinstance(argumentos, dict):
        return {}
    resumo = {}
    for chave, valor in list(argumentos.items())[:8]:
        texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False, default=str)
        resumo[str(chave)] = texto if len(texto) <= TETO_DE_ARGUMENTO else texto[:TETO_DE_ARGUMENTO] + "…"
    return resumo


def abrir(state: Any, pedido: str) -> Dict[str, Any]:
    """Começo do turno. Se a pessoa pediu Continuar depois de um reinício, a
    nota com o que já foi feito entra no histórico agora."""
    sessao = str(getattr(state, "session_id", "") or "")
    anterior = ler(sessao)
    if anterior and anterior.get("status") == "retomado" and anterior.get("nota"):
        state.history.append({"role": "system", "content": anterior["nota"], "priority": "CRITICAL"})
    registro = {"id": uuid.uuid4().hex[:12], "sessao": sessao, "status": "rodando", "iniciado_em": time.time(),
                "pedido": str(pedido or "")[:2000],
                "funcoes": list(getattr(state, "funcoes_ativas", None) or []),
                "passos": [], "motivo_de_termino": None}
    with _trava:
        _abertos[sessao] = registro
    _gravar(registro)
    return registro


def passo_comecou(sessao: str, ferramenta: str, argumentos: Any, efeito_colateral: bool) -> None:
    with _trava:
        registro = _abertos.get(str(sessao))
        if registro is None or len(registro["passos"]) >= TETO_DE_PASSOS:
            return
        registro["passos"].append({"ferramenta": ferramenta, "argumentos": _resumir(argumentos),
                                   "efeito_colateral": bool(efeito_colateral), "status": "rodando",
                                   "comecou_em": time.time()})
        # Passo com efeito é gravado já ao começar: se o servidor cair no
        # meio dele, o reinício precisa saber que ele pode ter acontecido.
        copia = json.loads(json.dumps(registro)) if efeito_colateral else None
    if copia is not None:
        _gravar(copia)


def passo_acabou(sessao: str, status: str) -> None:
    """Ponto seguro: grava o registro."""
    with _trava:
        registro = _abertos.get(str(sessao))
        if registro is None:
            return
        rodando = [p for p in registro["passos"] if p["status"] == "rodando"]
        if rodando:
            rodando[-1]["status"] = status
            rodando[-1]["acabou_em"] = time.time()
        copia = json.loads(json.dumps(registro))
    _gravar(copia)


def status_do_resultado(resultado: Any) -> str:
    if isinstance(resultado, dict):
        if resultado.get("precisa_permissao"):
            return "pediu_permissao"
        if str(resultado.get("status") or "").lower() in ("error", "erro", "falha") or resultado.get("erro"):
            return "erro"
    return "ok"


def motivo_do_resultado(resultado: Any) -> str:
    """O motivo de término a partir do que o turno devolveu."""
    if not isinstance(resultado, dict):
        return FALHA
    if resultado.get("permissao"):
        return ESPERANDO_APROVACAO
    if resultado.get("clarification"):
        return ESPERANDO_RESPOSTA
    parada = str((resultado.get("deliberation") or {}).get("stop_reason") or "")
    return _DO_LACO.get(parada, CONCLUIDO)


def em_curso_fora_de(sessao: str) -> List[Dict[str, Any]]:
    """Os turnos rodando agora nas outras conversas, com pedido e passos.
    Cópias: quem lê não segura a trava nem mexe no registro vivo."""
    with _trava:
        return [json.loads(json.dumps(r)) for s, r in _abertos.items() if s != str(sessao)]


def fechar(sessao: str, motivo: str) -> Optional[Dict[str, Any]]:
    with _trava:
        registro = _abertos.pop(str(sessao), None)
    if registro is None:
        return None
    for passo in registro["passos"]:
        if passo["status"] == "rodando":
            passo["status"] = "cortado"
    registro["status"] = "terminado"
    registro["motivo_de_termino"] = motivo
    _gravar(registro)
    return registro


def recuperar_no_inicio() -> List[str]:
    """Na subida do servidor: turno que ficou `rodando` não vai terminar
    mais. Vira `reinicio`, e a conversa oferece Continuar."""
    recuperadas = []
    try:
        arquivos = list(pasta().glob("*.json"))
    except OSError:
        return []
    for arquivo in arquivos:
        try:
            registro = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if registro.get("status") != "rodando" or registro.get("sessao") in _abertos:
            continue
        registro["status"] = REINICIO
        registro["motivo_de_termino"] = REINICIO
        for passo in registro.get("passos", []):
            if passo.get("status") == "rodando":
                passo["status"] = "incerto"
        _gravar(registro)
        recuperadas.append(str(registro.get("sessao")))
    if recuperadas:
        logger.info("Turnos interrompidos pelo reinício: %s", ", ".join(recuperadas))
    return recuperadas


def _linha(passo: Dict[str, Any]) -> str:
    argumentos = ", ".join(f"{k}={v}" for k, v in (passo.get("argumentos") or {}).items())
    return f"- {passo.get('ferramenta')}({argumentos}): {passo.get('status')}"


def nota_de_retomada(registro: Dict[str, Any]) -> str:
    passos = registro.get("passos") or []
    feitos = [p for p in passos if p.get("status") in ("ok", "erro", "pediu_permissao")]
    com_efeito = [p for p in passos if p.get("efeito_colateral") and p.get("status") in ("ok", "incerto")]
    partes = [
        "[INSTRUÇÃO DO SISTEMA: O servidor reiniciou no meio do turno anterior desta conversa e a pessoa "
        f"pediu para continuar. O pedido era: {registro.get('pedido', '')}",
        "O que já tinha rodado:\n" + ("\n".join(_linha(p) for p in feitos) if feitos else "- nada"),
    ]
    if com_efeito:
        partes.append(
            "Estes passos ALTERARAM algo (ou podem ter alterado, se `incerto`). Não repita sem conferir antes "
            "se o efeito já está lá:\n" + "\n".join(_linha(p) for p in com_efeito))
    partes.append("Continue a partir daí.]")
    return "\n\n".join(partes)


def continuar(sessao: str) -> Optional[Dict[str, Any]]:
    """A pessoa apertou Continuar: grava a nota que o próximo turno lê."""
    registro = ler(sessao)
    if not registro or registro.get("status") != REINICIO:
        return None
    registro["status"] = "retomado"
    registro["nota"] = nota_de_retomada(registro)
    _gravar(registro)
    return registro


def _parado_na_pessoa(registro: Dict[str, Any]) -> bool:
    return registro.get("status") == REINICIO or (
        registro.get("status") == "terminado"
        and registro.get("motivo_de_termino") in (ESPERANDO_APROVACAO, ESPERANDO_RESPOSTA))


def dispensar(sessao: str) -> bool:
    """A pessoa fechou o cartão sem responder: o turno deixa de esperar por
    ela, e a conversa sai do "precisa de você" na lista."""
    with _trava:
        if str(sessao) in _abertos:
            return False
    registro = ler(sessao)
    if not registro or not _parado_na_pessoa(registro):
        return False
    registro["status"] = "dispensado"
    _gravar(registro)
    return True


_NA_LISTA = {ESPERANDO_APROVACAO: "aguardando_aprovacao", ESPERANDO_RESPOSTA: "aguardando_resposta",
             FALHA: "falhou"}


def estado_na_lista(sessao: str) -> Optional[str]:
    """Como a lista de conversas mostra o último turno, para o que precisa da
    pessoa aparecer sem ela abrir cada conversa: `trabalhando`,
    `aguardando_aprovacao`, `aguardando_resposta`, `interrompido`, `falhou`;
    None quando terminou e não espera nada."""
    with _trava:
        if str(sessao) in _abertos:
            return "trabalhando"
    registro = ler(sessao)
    if not registro:
        return None
    if registro.get("status") == REINICIO:
        return "interrompido"
    if registro.get("status") != "terminado":
        return None
    return _NA_LISTA.get(str(registro.get("motivo_de_termino") or ""))


def apagar(sessao: str) -> None:
    """Conversa apagada: o registro vai junto."""
    try:
        _arquivo(sessao).unlink(missing_ok=True)
    except OSError:
        pass


def _limpar_para_testes() -> None:
    with _trava:
        _abertos.clear()


__all__ = ["CONCLUIDO", "CONEXAO_CAIU", "ESPERANDO_APROVACAO", "ESPERANDO_RESPOSTA", "FALHA", "PARADO", "REINICIO",
           "abrir", "apagar", "continuar", "dispensar", "estado_na_lista", "fechar", "ler", "motivo_do_resultado",
           "nota_de_retomada", "passo_acabou", "passo_comecou", "recuperar_no_inicio", "status_do_resultado"]
