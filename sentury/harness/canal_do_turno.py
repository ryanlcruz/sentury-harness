"""Os eventos de um turno: o que a interface vê ao vivo e o que fica no processo.

Cada evento vai para o registro do processo (que reconstrói a trilha ao reabrir
a sessão) e, quando há quem escute, para o stream da interface.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional


class CanalDoTurno:
    def __init__(self, orquestrador: Any, state: Any, progress_cb: Optional[Callable] = None):
        # Planner e responder são compartilhados entre turnos: zerar os
        # metadados evita atribuir a este turno o modelo ou o raciocínio de
        # outra requisição, inclusive de um motor que não for chamado.
        for motor in (orquestrador.planner, orquestrador.responder):
            if motor is not None:
                motor.last_model = None
                motor.last_provider = None
                motor.last_reasoning_summary = None

        from .processo_do_turno import criar_registrador

        processo: list = []
        # O main anexa isto à mensagem do assistente antes de persistir.
        state.processo_do_turno = processo
        self._registrar = criar_registrador(processo, state)
        self._progress_cb = progress_cb
        self._limpar_raciocinio = orquestrador._clean_reasoning_for_stream
        self._ja_pensou = False
        self._raciocinio_visto: set = set()
        self.inicio_das_ferramentas: Dict[str, float] = {}

    def ligar(self) -> None:
        """O navegador avisa cada passo por este canal (ver harness/emissor.py)."""
        from .emissor import EMISSOR

        EMISSOR.set(self.emit)
        self.progress("Entendendo o pedido…")

    def emit(self, event: Dict[str, Any]) -> None:
        self._registrar(event)
        if self._progress_cb:
            try:
                self._progress_cb(event)
            except Exception:
                pass

    def progress(self, etapa: str) -> None:
        self.emit({"type": "stage", "text": etapa})

    def dur(self, tid: str) -> Optional[int]:
        """Duração da ferramenta `tid`, em ms, desde que ela foi marcada no início."""
        inicio = self.inicio_das_ferramentas.pop(tid, None)
        return None if inicio is None else max(1, int((time.time() - inicio) * 1000))

    def emit_reasoning(self, raw: Optional[str]) -> None:
        """O raciocínio tem canal próprio e nunca entra na resposta final."""
        texto = self._limpar_raciocinio(raw)
        if not texto:
            return
        if not self._ja_pensou:
            # Um único "pensando" evita rótulos simultâneos; a etapa de resposta é
            # anunciada pelo responder quando ele começa.
            self._ja_pensou = True
            self.progress("Pensando…")
        # O laço replaneja e o mesmo trecho voltaria a cada volta.
        if texto[:400] in self._raciocinio_visto:
            return
        self._raciocinio_visto.add(texto[:400])
        self.emit({"type": "reasoning", "text": texto[:1600]})
