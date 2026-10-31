"""O que cada função nativa (`@plano`, `@workflow`, `@goal`, `@image`) liga no turno.

`@plano` e `@workflow` NÃO são o mesmo com tamanhos diferentes. Plano é UMA
execução: você pede, ele monta, fecha; workflow é um processo persistente de
várias etapas. Ele pode começar manualmente, por evento ou por relógio. Cron é
opcional e só entra quando a ocasião pede recorrência.

A função nativa é uma ATIVAÇÃO visível: o usuário liga o badge e ela vale até
ser desligada, em vez de depender de o texto conter a palavra certa toda vez.
Aqui mora só a tradução de "o que está ligado" para "o que muda neste turno":
quem executa continua sendo o orquestrador.

`@image` também põe seu schema na mesa; a autorização de gerar continua em
`policy.py`. Disponibilidade e execução são estados diferentes.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional

# A skill que ensina a conduzir trabalho de várias fases. `@workflow` a liga
# sem depender de o usuário acertar uma frase-gatilho.
SKILL_DO_WORKFLOW = "montar-workflow"

_PLANO = (
    "O usuário ligou @plano: prefere ver o caminho antes de um trabalho com várias "
    "etapas. Se o pedido pedir esse roteiro, use criar_plano com passos executáveis e "
    "aguarde a aprovação antes de executá-los. Para uma conversa simples, responda "
    "normalmente; não crie plano só porque a função está disponível."
)

_WORKFLOW = (
    "O usuário ligou @workflow: você pode criar um processo persistente de "
    "várias etapas quando o pedido realmente pedir isso. Nesse caso, defina os passos "
    "e use `criar_workflow`. Gatilho é opcional: "
    "só envie cron ou evento quando a ocasião realmente pedir recorrência; não "
    "invente horário e não chame `agenda` junto. Depois de propor, espere "
    "a aprovação ou o ajuste do usuário. Para uma execução única que fecha, use "
    "`criar_plano`; para uma conversa simples, responda sem criar workflow."
)


_GOAL = (
    "O usuário ligou @goal: sinaliza interesse num objetivo que você persiga entre "
    "turnos. Se o pedido for um objetivo persistente, chame `goal` com ação `propor`, "
    "o objetivo nas palavras dele, um `criterio` verificável e `marcos` opcionais. "
    "O usuário aprova a proposta no cartão antes de você começar. Se não couber "
    "como goal, explique por quê; não crie nem prometa um goal inexistente."
)


def precisa_propor_goal(state: Any) -> bool:
    if "goal" not in (getattr(state, "funcoes_ativas", None) or []):
        return False
    from ..memory.goals import em_aberto

    return em_aberto(str(getattr(state, "session_id", "") or "")) is None


_COMPUTADOR = (
    "O usuário ligou @computador: você pode ver a tela e usar o mouse e o "
    "teclado dele com a ferramenta `computador` se isso ajudar no pedido; ativar "
    "a função por si só não usa a tela. Ao começar a usar, e sempre que a "
    "tela mudar muito, peça `ver` com `marcar: true`: a imagem da tela chega na chamada "
    "seguinte, com um número em cada elemento, e mostra o que a lista não diz (onde o cursor "
    "já pisca, o que está carregando). Para conferir um gesto pequeno, `elementos` lista em "
    "texto os botões, campos e links, e você mira com `elemento: n` (n começa em 1; "
    "0 não é um elemento). Campo de texto: clique "
    "nele e use `digitar`, ou `definir_valor` no número dele (foco no campo e o valor digitado "
    "tecla por tecla, por cima do que havia; texto nunca é colado); `invocar` e `definir_valor` "
    "agem sem mexer no mouse "
    "dele. Depois de cada gesto a lista volta com um `veredito`: `confirmado` não se repete, "
    "e `sem_efeito_aparente` pede outro caminho, não o mesmo gesto. Sequência que você já "
    "conhece (clicar no campo, digitar, Enter) vai junta na mesma resposta, em ordem; se um "
    "gesto falhar ou não fizer efeito, os seguintes não rodam. Sem número, clique pela "
    "coordenada observada na imagem da tela, nunca por palpite. "
    "O primeiro gesto pede a aprovação dele no cartão; não peça aprovação em texto nem "
    "mande a pessoa fazer o gesto no seu lugar: chame a ação para abrir o cartão. "
    "Ele para tudo com Ctrl+Alt+Shift+S. "
    "Login e e-mail você pode preencher quando ele pediu ou deu os dados: o cartão "
    "pergunta a ele antes de digitar e-mail ou dado pessoal. Senha nunca pelo teclado, "
    "porque o que você digita passa pelo modelo: escolha a senha salva no preenchimento "
    "automático do navegador ou do gerenciador de senhas. Código que chega no celular dele, "
    "CAPTCHA ou passo que só ele pode fazer: chame `pedir_a_pessoa` com o motivo e encerre o "
    "turno; até ele devolver, o computador recusa tudo. A sessão continua ligada a esta "
    "conversa entre turnos; retome com `elementos` em vez de começar outra. Use `encerrar` "
    "somente se o usuário pedir para liberar a sessão."
)

_NAVEGADOR = (
    "O usuário ligou @navegador: você pode operar as abas autorizadas se o pedido "
    "precisar disso. Ao usar, navegue primeiro e leia as refs "
    "que a observação devolver antes de planejar um clique ou digitação; nunca "
    "invente uma ref. Continue no mesmo turno e na mesma sessão até cumprir a "
    "intenção pedida: abrir a página é observação intermediária, não conclusão, "
    "quando o usuário também pediu para clicar, preencher ou conferir o destino. "
    "Se o rótulo pedido não existir literalmente, mas houver um único alvo "
    "semanticamente equivalente, use a ref observada dele; só pare para perguntar "
    "quando houver ambiguidade real. Com as refs na mão, encadeie o fluxo num "
    "`roteiro` (digitar e enviar, esperar o resultado, abrir o item, conferir) em "
    "vez de uma ação por volta. Para apenas ler uma página pública, "
    "`ler_pagina` pode ser mais barato. Ações que comunicam ou enviam dados "
    "seguem pedindo aprovação."
    " A sessão fica ligada à conversa entre turnos. Use `encerrar` somente se "
    "o usuário pedir para liberar a sessão; concluir uma resposta não a encerra."
)


def _normalizar(funcoes: Optional[Iterable[str]]) -> List[str]:
    return [str(nome).strip().lower() for nome in (funcoes or []) if str(nome).strip()]


def instrucoes_do_turno(funcoes: Optional[Iterable[str]]) -> List[str]:
    """As instruções que entram no histórico por causa do que está ligado.

    `@workflow` implica `@plano`: cada disparo da rotina cria um plano, então
    quem liga o workflow também mostra o caminho antes. Mandar as duas
    instruções seria repetir, e instrução repetida dilui as duas.
    """
    ativas = _normalizar(funcoes)
    goal = [_GOAL] if "goal" in ativas else []
    goal += [_COMPUTADOR] if "computador" in ativas else []
    goal += [_NAVEGADOR] if "navegador" in ativas else []
    if "workflow" in ativas:
        return [_WORKFLOW] + goal
    if "plano" in ativas:
        return [_PLANO] + goal
    return goal


def ferramentas_ligadas(funcoes: Optional[Iterable[str]]) -> set:
    """Mapeia IDs de badges a schemas, sem ler o idioma da mensagem.

    Estar na mesa não é chamada de ferramenta nem aprovação para executá-la.
    """
    from ..tools.registry import TOOL_REGISTRY

    ativas = set(_normalizar(funcoes))
    return {nome for nome, meta in TOOL_REGISTRY.items()
            if ativas.intersection(meta.get("funcoes_disponiveis") or [])}


def skill_ligada(funcoes: Optional[Iterable[str]]) -> Optional[str]:
    """A skill que o badge liga diretamente, sem depender de frase-gatilho."""
    return SKILL_DO_WORKFLOW if "workflow" in _normalizar(funcoes) else None


def aplicar_no_turno(state: Any, skill_loader: Any = None) -> int:
    """Expõe as funções ligadas ao modelo sem executar uma ferramenta.

    Mora aqui, e não no orquestrador: o que a função significa e o que ela
    injeta mudam juntos, e o método do turno já tem teto de tamanho por um
    bom motivo. Devolve quantas instruções entraram.
    """
    ativas = list(getattr(state, "funcoes_ativas", None) or [])
    if "goal" in ativas and not precisa_propor_goal(state):
        # O executor automático preserva @goal para poder marcar marcos e
        # declarar conclusão; a instrução de PROPOR só vale antes de existir.
        ativas.remove("goal")
    instrucoes = instrucoes_do_turno(ativas)
    # Vale so neste turno: a do turno anterior sai. Sem isto, um `@goal` de
    # ontem continuaria mandando propor goal em toda mensagem.
    state.history = [m for m in state.history if not m.get("funcao_do_turno")]
    for texto in instrucoes:
        # O planner so enxerga mensagem de sistema com esta marca
        # (`_generate_plan`); sem ela `@plano` e `@workflow` nunca chegavam la.
        state.history.append({"role": "system", "content": f"[INSTRUÇÃO DO SISTEMA: {texto}]",
                              "priority": "HIGH", "funcao_do_turno": True})
    nome_skill = skill_ligada(ativas)
    if nome_skill and skill_loader is not None:
        skill = skill_loader.load_skill(nome_skill, session_id=state.session_id)
        if skill is not None:
            # O badge entrega conhecimento ao modelo; `executar_skill` só aparece
            # se o próprio modelo pedir. Desligar o badge remove este contexto.
            state.history.append({"role": "system", "content": skill.to_context_block(),
                                  "priority": "HIGH", "funcao_do_turno": True})
            return len(instrucoes) + 1
    return len(instrucoes)
