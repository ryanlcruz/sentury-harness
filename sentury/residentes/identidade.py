"""A identidade do residente no turno: quem ele é, como fala, a memória e as skills
que entram no histórico como instrução de sistema, e a mesma montagem para a aba
Contexto da tela."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .escopo import nome_visivel, tarefa_do_turno
from .manifesto import Manifesto

MARCA = "identidade_do_agente"
logger = logging.getLogger(__name__)


def identidade(agente: Manifesto, memoria: str = "", colegas: Any = (), na_mesa: bool = False) -> str:
    Nome = nome_visivel(agente)
    partes = [
        "## Papel",
        f"Você é {Nome}, {agente.papel}. Você é um agente residente: foi criado pelo "
        "Sentury, a pedido da pessoa, e continua existindo entre uma tarefa e outra.",
        f"Neste turno quem fala é você. Onde as regras gerais dizem \"Você é o Sentury\", "
        f"leia {Nome}: ao se apresentar, diga o seu nome. O Sentury é quem te criou.",
    ]
    if agente.personalidade:
        partes += ["", "## Como você fala", agente.personalidade]
    partes += [
        "",
        "## Objetivo",
        agente.objetivo,
        "",
        "## Contexto",
        ("Agora você está numa conversa da Mesa, com colegas e às vezes com a pessoa. Aqui a sua "
         "resposta é a sua fala: ela entra na conversa do jeito que você escrever. Fale com quem "
         "está na mesa, na primeira pessoa e no seu jeito, sem relatar o que fez nem falar da vez."
         if na_mesa else
         "As tarefas chegam por uma fila: do Sentury, de outro residente ou de um canal como o "
         "Telegram. Cada uma termina com a sua resposta, que volta a quem pediu; ninguém acompanha "
         "o turno ao vivo. Por isso a resposta final diz o que foi feito, o que foi encontrado e o "
         "que ficou pendente."),
        f"Suas ferramentas são estas: {', '.join(agente.ferramentas)}. Quando o trabalho pede uma "
        "que você não tem, `pedir_ferramenta` pergunta à pessoa; negada, siga sem ela.",
        "Parte do trabalho que é a especialidade de outro residente vai para ele com "
        "`pedir_ao_agente`. Depois de pedir, termine o turno dizendo o que pediu: a tarefa espera "
        "a resposta dele e volta para você com ela. Quando a pessoa cita um colega com @nome no "
        "pedido, ela quer que ele participe: considere pedir a parte dele assim.",
        "Ação que sai da sua caixa (mexer em outra máquina, enviar, publicar) passa pela aprovação "
        "da pessoa; a tarefa espera até ela responder.",
    ]
    if agente.skills:
        partes.append(f"Suas skills já vêm carregadas abaixo: {', '.join(agente.skills)}. Siga o "
                      "procedimento delas quando a tarefa for desse tipo.")
    outros = [c for c in colegas if c.nome != agente.nome]
    if outros:
        partes += ["", "## Colegas na HQ"]
        partes += [f"- {c.nome}: {c.papel}" for c in outros]
    if agente.instrucoes:
        partes += ["", "## Instruções da pessoa", agente.instrucoes]
    if memoria.strip():
        partes += ["", "## O que você anotou em tarefas anteriores", memoria.strip()]
    return "\n".join(partes)


def contexto(nome: str) -> Optional[List[Dict[str, str]]]:
    """O que o turno do residente recebe além das regras gerais do Sentury, na ordem
    em que entra. As skills citadas no pedido e as decisões parecidas com ele só
    aparecem no turno, porque dependem do pedido."""
    from . import memoria, registro
    from . import skills as _skills
    from ..memory.decisoes import para_o_turno

    agente = registro.carregar(nome)
    if agente is None:
        return None
    blocos = [{"titulo": "Identidade", "texto": identidade(agente, memoria.para_o_turno(agente.nome), registro.listar())}]
    try:
        blocos += [{"titulo": "Skill", "texto": bloco} for bloco in _skills.blocos(agente)]
    except Exception:
        logger.warning("Não consegui carregar as skills de %s.", agente.nome, exc_info=True)
    decisoes = para_o_turno("", agente=agente.nome)
    if decisoes:
        blocos.append({"titulo": "Decisões em que participou", "texto": decisoes})
    return blocos


def vestir(state: Any, agente: Manifesto, memoria: str = "", mensagem: str = "") -> None:
    """Põe a identidade e as skills no histórico, trocando as anteriores: manifesto,
    memória ou skill que mudaram valem a partir deste turno."""
    from . import registro
    from . import skills as _skills

    historico = [m for m in (getattr(state, "history", None) or [])
                 if not (isinstance(m, dict) and (m.get(MARCA) or m.get(_skills.MARCA)))]
    try:
        blocos = _skills.blocos(agente, mensagem, getattr(state, "session_id", None))
    except Exception:
        logger.warning("Não consegui carregar as skills de %s.", agente.nome, exc_info=True)
        blocos = []
    historico[0:0] = [
        {"role": "system", "content": identidade(agente, memoria, registro.listar(),
                                                 na_mesa=str(getattr(tarefa_do_turno(), "origem", "") or "").startswith("mesa:")),
         "priority": "CRITICAL", MARCA: agente.nome},
        *({"role": "system", "content": bloco, "priority": "HIGH", _skills.MARCA: agente.nome}
          for bloco in blocos),
    ]
    state.history = historico
