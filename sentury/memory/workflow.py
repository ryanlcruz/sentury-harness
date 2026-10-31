"""O trabalho persistente de varias etapas.

O plano (`memory/plano.py`) é **uma** execução: você pede, ele monta, você
aprova, ele fecha. O workflow é a **receita persistente**: pode ser iniciado
manualmente, por evento ou por relógio ("toda segunda às 8"). Cron é opcional.

A diferença é o ciclo de vida, não a presença obrigatória de cron:

    plano     nasce quando você pede   · roda uma vez · fecha
    workflow  nasce quando você define · atravessa turnos · pode acumular
              execuções; só agenda quando a ocasião pede

O workflow **contém** um plano (o modelo), e isso não é duplicação: ele soma
as duas coisas que o plano não tem e não deve ter. Um agendamento que guarda o
script não vira o script.

Isso corrige um erro anterior: a linha `_Agenda: 0 8 * * 1_` foi enfiada dentro
de uma tarefa do plano. Era o workflow tentando nascer lá dentro: o sintoma de
que o plano estava virando "plano 2.0" em vez de existirem dois.

O formato segue o do plano, pelo mesmo motivo:

    .sentury/workflows/<nome>/
        workflow.md    para que serve, passos e, quando houver, gatilho

E as execuções fora do repositório, em `~/.sentury/workflows/<nome>.json`:
quando disparou, que plano criou, e como terminou. Um `git status` sujo a cada
disparo tornaria o workflow um estorvo.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

# `- [ ] 1. Passo` no corpo do arquivo: o modelo de plano que cada disparo
# instancia. Mesma marca do checklist, de propósito: é o mesmo formato, lido
# pelo mesmo módulo quando vira plano.
# `[-]` e em andamento, como no plano: sem ele, o passo sumia da receita.
_PASSO = re.compile(r"^\s*- \[[ xX-]\][*!]?\s*(.+?)\s*$", re.MULTILINE)
_GATILHO = re.compile(r"^\s*_[Gg]atilho:\s*(.+?)_\s*$", re.MULTILINE)
_PORQUE = re.compile(r"^\s*_[Pp]or ?qu[êe]:\s*(.+?)_\s*$", re.MULTILINE)

# Execução que ninguém olha há muito tempo não é rotina, é entulho: o número
# existe para a listagem dizer isso em voz alta, não para apagar nada.
EXECUCOES_NO_RESUMO = 10


def raiz_dos_workflows(trabalho: Optional[Path] = None) -> Path:
    """Onde a receita legível mora: junto do trabalho, versionável."""
    from ..tools.arquivos import raiz_de_trabalho

    return (trabalho or raiz_de_trabalho()) / ".sentury" / "workflows"


def _casa() -> Path:
    from .plano import _casa as casa_do_plano

    return casa_do_plano()


def _arquivo_de_execucoes(nome: str) -> Path:
    alvo = _casa() / "workflows"
    alvo.mkdir(parents=True, exist_ok=True)
    return alvo / f"{_limpar(nome)}.json"


def _limpar(nome: str) -> str:
    from .plano import _limpar as limpar_do_plano

    return limpar_do_plano(nome)


def criar(
    nome: str,
    porque: str,
    gatilho: str,
    passos: List[str],
    trabalho: Optional[Path] = None,
) -> Dict[str, Any]:
    """Escreve a receita. Não dispara nada: definir e rodar são momentos
    diferentes, e confundir os dois é o que faz rotina rodar sem revisão."""
    nome_limpo = _limpar(nome)
    if not nome_limpo:
        return {"ok": False, "erro": "diga o nome do workflow"}
    if not passos:
        return {"ok": False, "erro": "um workflow sem passos não roda nada"}

    pasta = raiz_dos_workflows(trabalho) / nome_limpo
    linhas = [f"# {nome_limpo}", ""]
    if str(porque or "").strip():
        linhas += [f"_Porquê: {str(porque).strip()}_", ""]
    if str(gatilho or "").strip():
        linhas += [f"_Gatilho: {str(gatilho).strip()}_", ""]
    linhas += ["## Modelo de plano", ""]
    linhas += [f"- [ ] {i}. {str(p).strip()}" for i, p in enumerate(passos, 1)]
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "workflow.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "erro": f"nao consegui gravar o workflow: {exc}"}
    return {"ok": True, "workflow": nome_limpo, "gatilho": str(gatilho).strip(),
            "passos": len(passos), "caminho": str(pasta)}


def ler(nome: str, trabalho: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """A receita, como está escrita em disco."""
    alvo = raiz_dos_workflows(trabalho) / _limpar(nome) / "workflow.md"
    try:
        texto = alvo.read_text(encoding="utf-8")
    except OSError:
        return None
    gatilho = _GATILHO.search(texto)
    porque = _PORQUE.search(texto)
    return {
        "workflow": _limpar(nome),
        "gatilho": gatilho.group(1).strip() if gatilho else "",
        "porque": porque.group(1).strip() if porque else "",
        "passos": [m.strip() for m in _PASSO.findall(texto)],
    }


def _ler_execucoes(nome: str) -> List[Dict[str, Any]]:
    try:
        return json.loads(_arquivo_de_execucoes(nome).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def registrar_execucao(
    nome: str,
    plano: str,
    *,
    estado: str = "rodando",
    nota: str = "",
) -> Dict[str, Any]:
    """Guarda uma execução do workflow e qual plano nasceu dali.

    É append-only pelo mesmo motivo do histórico de tarefa: a execução que
    falhou é evidência de que a rotina não está funcionando, e é exatamente
    ela que alguém precisa ver.
    """
    with _LOCK:
        execucoes = _ler_execucoes(nome)
        execucoes.append({
            "plano": str(plano or ""), "estado": str(estado or "rodando"),
            "em": time.time(), "nota": str(nota or "")[:300],
        })
        alvo = _arquivo_de_execucoes(nome)
        try:
            tmp = alvo.with_suffix(".tmp")
            tmp.write_text(json.dumps(execucoes, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(alvo)
        except OSError as exc:
            logger.warning("Nao consegui gravar a execucao de %s: %s", nome, exc)
            return {"ok": False, "erro": str(exc)}
        return {"ok": True, "workflow": _limpar(nome), "execucoes": len(execucoes)}


def resumo(nome: str, trabalho: Optional[Path] = None) -> Dict[str, Any]:
    """A receita mais as últimas execuções: o que decide se ela está viva."""
    receita = ler(nome, trabalho)
    if receita is None:
        return {"ok": False, "erro": f"workflow '{nome}' nao existe"}
    execucoes = _ler_execucoes(nome)
    falhas = sum(1 for e in execucoes if e.get("estado") == "falhou")
    return {
        "ok": True,
        **receita,
        "execucoes": execucoes[-EXECUCOES_NO_RESUMO:],
        "total_de_execucoes": len(execucoes),
        # Rotina que falha sempre é pior que rotina que não existe: quem confia
        # nela para de conferir, e o erro passa despercebido.
        "falhas": falhas,
        "ultima": execucoes[-1] if execucoes else None,
    }


def listar(trabalho: Optional[Path] = None) -> List[Dict[str, Any]]:
    """As receitas deste trabalho, com quando cada uma rodou por último."""
    raiz = raiz_dos_workflows(trabalho)
    if not raiz.is_dir():
        return []
    saida = []
    for pasta in sorted(raiz.iterdir()):
        if not (pasta / "workflow.md").is_file():
            continue
        receita = ler(pasta.name, trabalho) or {}
        execucoes = _ler_execucoes(pasta.name)
        saida.append({
            "workflow": pasta.name,
            "gatilho": receita.get("gatilho", ""),
            "passos": len(receita.get("passos") or []),
            "execucoes": len(execucoes),
            "ultima": execucoes[-1] if execucoes else None,
        })
    return saida
