"""Guarda orientações recebidas enquanto um turno está em andamento.

Uma orientação passa por recebida, aplicada e vista. Só entra no histórico em
um ponto seguro; se chegar após o início da resposta final, vira o próximo
turno. O armazenamento vale apenas durante o processo atual.
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from . import turno_em_curso
from .emissor import emitir

MARCA = "orientacao"
TETO_DE_TEXTO = 4000
EVENTO = "mensagem_no_turno"


@dataclass
class Orientacao:
    seq: int
    texto: str
    id_cliente: str
    recebida_em: float
    aplicada_em: Optional[float] = None
    vista_em: Optional[float] = None

    def como_dict(self) -> Dict[str, Any]:
        return asdict(self)


_trava = threading.Lock()
_caixas: Dict[str, List[Orientacao]] = {}
_seq = itertools.count(1)


def _sessao(state: Any) -> str:
    return str(getattr(state, "session_id", "") or "")


def _avisar(o: Orientacao, fase: str) -> None:
    emitir({"type": EVENTO, "seq": o.seq, "id_cliente": o.id_cliente, "fase": fase})


def receber(sessao: str, texto: str, id_cliente: str = "") -> Optional[Orientacao]:
    """Guarda a orientação para o turno em curso. Sem turno, `None`: quem
    chamou manda como mensagem normal, que abre um turno."""
    texto = (texto or "").strip()
    if len(texto) > TETO_DE_TEXTO:
        texto = texto[:TETO_DE_TEXTO] + f"\n[a mensagem passou de {TETO_DE_TEXTO} caracteres e foi cortada aqui]"
    if not texto or not turno_em_curso.em_curso(sessao):
        return None
    with _trava:
        o = Orientacao(seq=next(_seq), texto=texto, id_cliente=str(id_cliente or "")[:80], recebida_em=time.time())
        _caixas.setdefault(str(sessao), []).append(o)
    return o


def pendentes(sessao: str) -> List[Orientacao]:
    with _trava:
        return [o for o in _caixas.get(str(sessao), []) if o.aplicada_em is None]


def mensagem(texto: str) -> str:
    return (
        "[INSTRUÇÃO DO SISTEMA: A pessoa mandou esta mensagem enquanto você trabalhava no pedido dela. "
        "Ela veio DEPOIS da Solicitação e a corrige ou completa: onde as duas discordarem, vale esta. "
        "Leve em conta já no próximo passo. Se for só uma pergunta (por exemplo, o que você está "
        "fazendo), responda-a na resposta final e siga o trabalho.\n\n"
        f"Mensagem da pessoa: {texto}\n]"
    )


def aplicar(state: Any) -> List[Orientacao]:
    """Ponto seguro: põe no histórico o que chegou desde o último. Devolve o
    que entrou; vazio quando não chegou nada (o caso de quase sempre)."""
    sessao = _sessao(state)
    agora = time.time()
    with _trava:
        novas = [o for o in _caixas.get(sessao, []) if o.aplicada_em is None]
        for o in novas:
            o.aplicada_em = agora
    for o in novas:
        state.history.append({"role": "system", "content": mensagem(o.texto), "priority": "CRITICAL",
                              MARCA: o.texto, "seq": o.seq})
        _avisar(o, "aplicada")
    return novas


def marcar_vistas(state: Any, mensagens: Any) -> List[Orientacao]:
    """Depois de uma chamada ao modelo que voltou: as orientações cujo texto
    estava nas mensagens enviadas foram vistas. Confere o texto de verdade:
    uma orientação cortada pela compactação não conta como vista."""
    sessao = _sessao(state)
    with _trava:
        candidatas = [o for o in _caixas.get(sessao, []) if o.aplicada_em is not None and o.vista_em is None]
    if not candidatas:
        return []
    enviado = "\n".join(str(m.get("content") if isinstance(m, dict) else m) for m in (mensagens or []))
    agora = time.time()
    vistas = [o for o in candidatas if o.texto in enviado]
    with _trava:
        for o in vistas:
            o.vista_em = agora
    for o in vistas:
        _avisar(o, "vista")
    return vistas


def encerrar(sessao: str) -> List[Orientacao]:
    """Fim do turno: esvazia a caixa e devolve o que chegou tarde demais para
    este turno: vira o próximo."""
    with _trava:
        caixa = _caixas.pop(str(sessao), [])
    return [o for o in caixa if o.aplicada_em is None]


def _limpar_para_testes() -> None:
    with _trava:
        _caixas.clear()


__all__ = ["EVENTO", "MARCA", "Orientacao", "aplicar", "encerrar", "marcar_vistas", "mensagem", "pendentes", "receber"]
