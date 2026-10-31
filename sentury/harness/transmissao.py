"""A transmissão do turno: os eventos numerados, para a tela poder voltar.

O turno não vive dentro da conexão HTTP do /chat/stream: publica cada
pedaço SSE aqui, com um número (`id:` do SSE), e a resposta HTTP só assiste.
Caiu a conexão:

- o turno segue rodando por `TOLERANCIA` segundos, esperando alguém voltar;
- a tela reconecta em `GET /chat/stream/{sessao}/retomar?desde=N` e recebe
  do N+1 em diante, sem perder nem repetir evento;
- ninguém voltou no prazo: o turno para como antes, pelo Parar cooperativo
  (escrita em curso termina): ver harness/turno_em_curso.py.

A transmissão que terminou fica guardada por `RETENCAO` segundos, para quem
reconecta depois do `done` ainda recebê-lo. Só vale dentro de um processo.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import AsyncIterator, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

TOLERANCIA = 45.0  # cobre as 5 tentativas da tela (1+2+4+8+16 s) com folga
RETENCAO = 120.0


class Transmissao:
    def __init__(self, sessao: str, ao_abandonar: Optional[Callable[[], None]] = None,
                 tolerancia: Optional[float] = None) -> None:
        self.sessao = sessao
        self.id = uuid.uuid4().hex[:12]
        self.produtor: Optional[asyncio.Task] = None
        self.pedacos: List[str] = []
        self.terminada = False
        self.terminada_em: Optional[float] = None
        self.assistindo = 0
        self._novidade = asyncio.Event()
        self._ao_abandonar = ao_abandonar
        self._tolerancia = TOLERANCIA if tolerancia is None else tolerancia
        self._prazo: Optional[asyncio.TimerHandle] = None

    def publicar(self, pedaco: str) -> None:
        self.pedacos.append(pedaco)
        self._acordar()

    def encerrar(self) -> None:
        self.terminada = True
        self.terminada_em = time.time()
        self._cancelar_prazo()
        self._acordar()

    def _acordar(self) -> None:
        self._novidade.set()
        self._novidade = asyncio.Event()

    def _cancelar_prazo(self) -> None:
        if self._prazo is not None:
            self._prazo.cancel()
            self._prazo = None

    def _saiu(self) -> None:
        self.assistindo -= 1
        if self.assistindo > 0 or self.terminada:
            return
        self._cancelar_prazo()
        self._prazo = asyncio.get_running_loop().call_later(self._tolerancia, self._abandonada)

    def _abandonada(self) -> None:
        self._prazo = None
        if self.assistindo == 0 and not self.terminada and self._ao_abandonar is not None:
            logger.info("Ninguém voltou para o turno de %s: parando.", self.sessao)
            self._ao_abandonar()

    async def assistir(self, desde: int = 0) -> AsyncIterator[str]:
        """Os pedaços depois do `desde` (o último `id` que a tela recebeu), cada
        um com o seu `id:`. Termina quando a transmissão termina."""
        self.assistindo += 1
        self._cancelar_prazo()
        proximo = max(0, int(desde))
        try:
            while True:
                while proximo < len(self.pedacos):
                    proximo += 1
                    yield f"id: {proximo}\n{self.pedacos[proximo - 1]}"
                if self.terminada:
                    return
                await self._novidade.wait()
        finally:
            self._saiu()


_transmissoes: Dict[str, Transmissao] = {}


def _limpar_velhas() -> None:
    agora = time.time()
    for sessao, t in list(_transmissoes.items()):
        if t.terminada and t.terminada_em and agora - t.terminada_em > RETENCAO:
            _transmissoes.pop(sessao, None)


def abrir(sessao: str, ao_abandonar: Optional[Callable[[], None]] = None) -> Transmissao:
    _limpar_velhas()
    t = Transmissao(str(sessao), ao_abandonar)
    _transmissoes[str(sessao)] = t
    return t


def da(sessao: str, id_: str = "") -> Optional[Transmissao]:
    """A transmissão da conversa; com `id_`, só se ainda for aquela: um
    turno novo da mesma conversa não é o que a tela estava assistindo."""
    _limpar_velhas()
    t = _transmissoes.get(str(sessao))
    if t is not None and id_ and t.id != id_:
        return None
    return t


def _limpar_para_testes() -> None:
    _transmissoes.clear()


__all__ = ["RETENCAO", "TOLERANCIA", "Transmissao", "abrir", "da"]
