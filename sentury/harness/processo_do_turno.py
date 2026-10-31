"""O registro do que aconteceu no turno, montado a partir dos eventos.

A tela mostra ao vivo e esquece; isto fica. Quando a resposta chega, os passos
somem do lugar onde estavam acontecendo e continuam no Processo Analítico, que
é onde alguém vai conferir depois: inclusive dias depois, quando ninguém
lembra do que foi executado.

Morava dentro do método do turno, e o método tem teto de tamanho por um bom
motivo: cada coisa que "é só um `if` a mais" ali custa a legibilidade do laço
inteiro.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

# O resumo do resultado cabe numa olhada. O documento inteiro não mora aqui:
# quem quer o dado completo tem o anexo e a resposta.
TETO_DO_RESUMO = 240


def criar_registrador(processo: List[Dict[str, Any]], state: Any = None) -> Callable[[Dict[str, Any]], None]:
    """Devolve a função que transforma evento em passo registrado.

    Com `state`, os eventos do navegador montam `state.navegador_do_turno`,
    o cartão que o `main` guarda na mensagem (`cartao_do_navegador.py`).
    """
    if state is not None:
        state.navegador_do_turno = None
        state.computador_do_turno = None

    def registrar(event: Dict[str, Any]) -> None:
        tipo = event.get("type")
        if tipo == "navegador" and state is not None:
            from .cartao_do_navegador import aplicar

            state.navegador_do_turno = aplicar(state.navegador_do_turno, event)
            return
        if tipo == "computador" and state is not None:
            from .cartao_do_computador import aplicar

            state.computador_do_turno = aplicar(state.computador_do_turno, event)
            return
        if tipo in ("diff", "saida"):
            # O diff do arquivo e a saida do comando ficam no passo que os
            # produziu: o ultimo daquela ferramenta que ainda esta rodando (o
            # tool_complete vem depois). A saida parcial nao fica: a final
            # tem tudo.
            for passo in reversed(processo):
                if passo.get("ferramenta") == event.get("ferramenta") and passo.get("status") == "running":
                    passo[tipo] = {k: v for k, v in event.items() if k not in ("type", "ferramenta")}
                    break
            return
        if tipo == "saida_parcial":
            return
        if tipo == "tool_start":
            processo.append({
                "id": event.get("id"),
                "titulo": event.get("title"),
                "ferramenta": event.get("tool"),
                "kind": event.get("kind"),
                "comando": event.get("command"),
                "fala": event.get("fala"),
                "status": "running",
            })
            if state is not None and event.get("fala"):
                # A moldura do computer use mostra as tres ultimas falas; sem
                # moldura aberta nesta sessao, nao faz nada.
                from ..tools.computador import ouvir_fala

                ouvir_fala(state, event)
            return
        if tipo != "tool_complete":
            return
        for passo in processo:
            if passo.get("id") != event.get("id"):
                continue
            passo["status"] = event.get("status") or "ok"
            passo["duracao_ms"] = event.get("duration_ms")
            resumo = str(event.get("resumo") or "").strip()
            if resumo:
                # Guardado menor do que foi mostrado ao vivo: na hora, o
                # tamanho ajuda a acompanhar; depois, vira parede de texto
                # dentro de um painel que já tem quatro passos.
                passo["resumo"] = (
                    resumo if len(resumo) <= TETO_DO_RESUMO
                    else resumo[:TETO_DO_RESUMO].rstrip() + "…"
                )
            return

    return registrar
