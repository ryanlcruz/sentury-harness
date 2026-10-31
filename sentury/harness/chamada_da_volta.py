"""A chamada da volta: o que o modelo lê, a chamada e a leitura do que ele devolveu.

Um modelo, um laço. A chamada nativa e o plano em texto diferem só no contrato
do prompt e na leitura da resposta; o resto é o mesmo nos dois caminhos.

O prompt tem duas partes. A estável não muda entre pedidos e vai no sistema,
porque o provedor só desconta o prefixo idêntico caractere a caractere. O que
muda por turno ou por volta vai no fim da conversa.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from ..config import settings
from ..context.base import _texto_base
from ..llm.action_parser import extract_plain_text
from . import passo_unico
from .fatias import medir as medir_fatias
from .resposta_direta import desembrulhar, sem_chamada_vazada
from .state import is_transient_failure_message

logger = logging.getLogger(__name__)

_MODOS = {
    "lightweight": "PLANNER_MODE_LIGHTWEIGHT_PROMPT",
    "deliberate": "PLANNER_MODE_DELIBERATE_PROMPT",
    "action_plan": "PLANNER_MODE_ACTION_PLAN_PROMPT",
}
_LIDO = {"ok", "repaired"}


def _limpar_turno(turno: Any) -> None:
    turno.resposta_direta = None
    turno.narracao = None
    turno.resposta_bruta = None
    turno.dados_do_plano = None
    turno.contrato = None
    turno.capacidades_achadas = []
    turno.capacidades = set()


def _skill_pedida(orq: Any, state: Any, user_message: str) -> Optional[List[Dict[str, Any]]]:
    """A skill citada pelo nome ou pela tag da interface vira o primeiro passo,
    antes de o modelo planejar o resto com ela carregada."""
    from .funcoes import aplicar_no_turno
    from .plano_aberto import aplicar_no_turno as retomar_plano

    aplicar_no_turno(state, orq.skill_loader)  # a função ligada expõe instrução, não executa skill
    retomar_plano(state, user_message)  # só quando a mensagem puxa o plano
    pedida, origem = orq._requested_skill_name(user_message, getattr(state, "funcoes_ativas", None))
    if not pedida or origem == "funcao" or pedida == "llm-council" or pedida not in orq.procedural_skills:
        return None
    if any(m.get("role") == "system" and f"=== SKILL: {pedida} ===" in str(m.get("content") or "")
           for m in state.history):
        return None
    logger.info("Carregando skill procedural '%s' por gatilho %s.", pedida, origem)
    return [{"tool": "executar_skill", "arguments": {"nome": pedida}}]


def prompt_estavel(orq: Any, nativo: bool, manifesto: Optional[str]) -> str:
    """O que não muda entre pedidos: regras, contrato de artefato e catálogos."""
    from ..artifacts import build_artifact_prompt
    from ..llm.prompts import GROUNDING_GUIDANCE, TERMINAR_O_TRABALHO
    from .orchestrator import _prompt_do_planejador

    # No passo único o texto sem chamada já é a resposta; o prompt segue o do
    # planejador, sem o contrato de JSON.
    partes = [
        _prompt_do_planejador(com_ferramentas=not nativo),
        GROUNDING_GUIDANCE,  # contexto faltante pede ferramenta ou pergunta, não resposta inventada
        TERMINAR_O_TRABALHO,
        build_artifact_prompt(),
        # Muda só quando uma skill é criada ou apagada.
        f"### Catálogo de Skills Procedurais:\n{orq.skill_discovery.build_index_prompt()}",
    ]
    if manifesto is not None:
        partes.append(manifesto)
    return "\n\n".join(partes)


def contexto_do_turno(orq: Any, state: Any, user_message: str, *, nativo: bool, modo: str,
                      descoberta: Optional[str], contexto_adicional: Optional[str],
                      rag_context: str, is_replanning: bool) -> str:
    """O que muda por turno ou por volta: modo, data, estado da conversa, skills
    carregadas, memória e observações anteriores."""
    partes = [_texto_base(_MODOS.get(modo, _MODOS["lightweight"]))]
    texto = ""
    if not nativo:
        from ..llm.secoes import ferramentas_alem_do_nucleo

        texto = ferramentas_alem_do_nucleo(orq.turno.capacidades)
    # O índice é refeito do registro vivo a cada volta e só traz candidatas: o
    # modelo decide, o harness autoriza.
    if descoberta is not None:
        partes.append("### Descoberta Progressiva de Capacidades:\n" + descoberta)
    partes.append(_texto_base("DATA_DE_REFERENCIA").format(hoje=date.today().isoformat()).strip())
    estado_atual = orq._describe_current_state(state)
    if estado_atual:
        partes.append(f"### O que já existe nesta conversa:\n{estado_atual}")
    carregadas = [m.get("content") for m in state.history
                  if m.get("role") == "system" and "[INSTRUÇÃO PROCEDURAL DE SKILL CARREGADA]" in m.get("content", "")]
    if carregadas:
        partes.append(_texto_base("SKILLS_ATIVAS").strip() + "\n\n" + "\n\n".join(carregadas))
    if contexto_adicional:
        partes.append(f"Contexto de memória e preferências:\n{contexto_adicional}")
    if rag_context:
        partes.append(f"Conhecimento conceitual relevante:\n{rag_context}")
    continua, anteriores = orq._detect_follow_up_and_extract_context(user_message, state)
    if continua and anteriores:
        partes.append("Observações anteriores disponíveis. A relação com este pedido não foi determinada; "
                      "considere apenas as que ajudarem, ou consulte uma fonte nova.\n"
                      + orq._format_tool_results_for_context(anteriores))
    # Só com skill carregada de fato: sem ela, o aviso diria que havia skill ativa em toda volta.
    if is_replanning and carregadas:
        partes.append(_texto_base("SKILL_NA_VOLTA_SEGUINTE").strip())
    return (partes[0] + texto + "\n\n" + "\n\n".join(partes[1:])).strip()


def _mensagens(orq: Any, state: Any, user_message: str, sistema: str, contexto: str,
               nativo: bool) -> List[Dict[str, Any]]:
    """A cada tentativa, porque depois de compactar o histórico é outro."""
    from .conversa import historico_para_o_modelo, montar, preparar_legado
    from .print_da_tela import anexar_print

    historico = historico_para_o_modelo(state.history, user_message)
    filtros = (f"Filtros usados nas análises anteriores (valem se o pedido seguir no mesmo recorte): "
               f"{state.filtros}")
    if nativo:
        contexto = "\n\n".join(p for p in [contexto, filtros if state.filtros else ""] if p)
        return anexar_print(state, montar(sistema, historico, user_message, contexto, nativo=True))
    pedido = f"{contexto}\n\n{filtros}\nSolicitação: {user_message}"
    return anexar_print(state, preparar_legado(sistema, historico, pedido))


def _ler_chamadas_nativas(orq: Any, raw: Any, chamadas: Any) -> Tuple[Dict[str, Any], str]:
    from ..llm.tool_schemas import parse_native_tool_calls

    plano = [{"tool": c["tool"], "arguments": c["arguments"], "id": c.get("id", "")}
             for c in parse_native_tool_calls(chamadas)]
    # O texto que veio junto das chamadas é o "vou fazer X" que aparece na tela.
    orq.turno.narracao = extract_plain_text(raw).strip()
    return {"plan": plano}, "ok"


def _ler_texto_no_passo_unico(orq: Any, raw: Any) -> Tuple[Dict[str, Any], str]:
    """Texto sem chamada é a resposta, menos quando o texto é um plano: um plano
    escrito no texto ainda roda, em vez de ir para a tela como resposta."""
    dados, contrato = ler_payload(raw)
    limpo, orq.turno.chamada_em_texto = sem_chamada_vazada(raw)
    if contrato in _LIDO and dados.get("plan"):
        orq.turno.chamada_em_texto = False
        return dados, contrato
    # O envelope `action: respond` se desembrulha; o texto cru pode ter <think> e
    # não vira resposta quando o modelo pediu um plano explicitamente vazio.
    direta = desembrulhar(dados)
    vazio_de_proposito = contrato in _LIDO and isinstance(dados.get("plan"), list) and not dados["plan"]
    if direta is not None:
        orq.turno.resposta_direta = extract_plain_text(direta).strip()
    elif not vazio_de_proposito:
        orq.turno.resposta_direta = extract_plain_text(limpo).strip()
    return {"plan": []}, "ok"


def _descobrir(orq: Any, state: Any, mensagem: str) -> Tuple[Optional[str], Optional[str]]:
    """Quais ferramentas vão na chamada. Devolve o mapa e os achados da busca,
    que só existem sob demanda; com o catálogo inteiro os dois ficam vazios.

    O catálogo inteiro só vale no tool calling nativo, onde os esquemas viajam
    num campo próprio. No caminho de texto a orientação de cada ferramenta entra
    no prompt e disputa espaço com o histórico, então ali segue sob demanda."""
    turno = orq.turno
    if not getattr(settings, "SENTURY_PROGRESSIVE_CAPABILITIES", True):
        return None, None
    try:
        from . import descoberta as _descoberta

        if turno.passo_unico and not _descoberta.sob_demanda(state):
            turno.capacidades_achadas, turno.capacidades = [], _descoberta.inteiro(state)
            return None, None
        turno.capacidades_achadas, turno.capacidades, manifesto, achados = _descoberta.preparar(
            state, mensagem, orq.skill_discovery.get_available_skills())
        return manifesto, achados
    except Exception as exc:
        logger.debug("Descoberta de capacidades falhou (ignorando): %s", exc)
        return None, None


async def chamar(orq: Any, user_message: str, state: Any, contexto_adicional: Optional[str],
                 rag_context: str, complexity: Optional[str] = None, is_replanning: bool = False,
                 planner_mode: Optional[str] = None) -> List[Dict[str, Any]]:
    """Monta, chama e lê. Devolve o plano da volta; texto sem chamada fica em
    `turno.resposta_direta` e o plano volta vazio."""
    from .configuracao_do_turno import modo_nativo
    from .pedido_grande import chamar_cabendo
    from .print_da_tela import chamar_com_print

    from . import descoberta as _descoberta

    turno = orq.turno
    _limpar_turno(turno)
    # A descoberta vem antes do atalho de skill: a trajetória fica observável
    # mesmo quando o primeiro passo só carrega uma skill.
    turno.passo_unico = nativo = passo_unico.ativo(orq.planner)
    manifesto, descoberta = _descobrir(orq, state, user_message)
    if not is_replanning:
        skill = _skill_pedida(orq, state, user_message)
        if skill:
            return skill

    if nativo or not planner_mode:
        planner_mode = modo_nativo(state)

    def _prompt():
        sistema = orq.prompt_context_engine.build_prompt(prompt_estavel(orq, nativo, manifesto), "planner")
        turno.prompt_do_passo = sistema
        return sistema, contexto_do_turno(orq, state, user_message, nativo=nativo, modo=planner_mode,
                                          descoberta=descoberta, contexto_adicional=contexto_adicional,
                                          rag_context=rag_context, is_replanning=is_replanning)

    sistema, contexto = _prompt()
    forcada = _descoberta.forcada()

    def montar():
        # O catálogo inteiro não coube e o turno passou a sob demanda: a nova
        # tentativa leva o mapa e o núcleo, não a lista que estourou.
        nonlocal sistema, contexto, manifesto, descoberta, forcada
        if _descoberta.forcada() != forcada:
            forcada = _descoberta.forcada()
            manifesto, descoberta = _descobrir(orq, state, user_message)
            sistema, contexto = _prompt()
        return _mensagens(orq, state, user_message, sistema, contexto, nativo)

    try:
        raw, mensagens = await chamar_cabendo(
            state, orq.context_budget_manager,
            montar,
            lambda msgs: chamar_com_print(state, msgs, lambda m: completar(orq, m, complexity)),
        )
        nativas = getattr(orq.planner, "last_tool_calls", None) if settings.SENTURY_NATIVE_TOOLS else None
        if nativas:
            dados, contrato = _ler_chamadas_nativas(orq, raw, nativas)
        elif nativo and str(raw or "").strip():
            dados, contrato = _ler_texto_no_passo_unico(orq, raw)
        else:
            dados, contrato = ler_payload(raw)
        # Formato errado no plano em texto ganha uma tentativa de reparo; o passo
        # único não tem contrato de JSON para reparar.
        if contrato != "ok" and not nativo:
            from .contrato_json import reparar

            raw, dados, contrato = await reparar(orq, contract=contrato, messages=mensagens, complexity=complexity)
        if contrato not in _LIDO:
            dados = {}
        turno.resposta_bruta = str(raw or "").strip()
        turno.dados_do_plano = dados
        turno.contrato = contrato
        direta = desembrulhar(dados)
        if direta is None and dados.get("plan") == [] and isinstance(dados.get("message"), str):
            direta = dados["message"]
        # Texto sem chamada é a resposta, nos dois caminhos.
        if direta is not None and str(direta).strip():
            turno.resposta_direta = extract_plain_text(direta).strip()
            return []
        return payload_para_plano(dados)
    except Exception as exc:
        logger.warning("Falha ao gerar plano com o Planner (%s). Executando sem ferramentas.", exc)
        return []


async def completar(
    orq,
    messages: List[Dict[str, str]],
    complexity: Optional[str],
) -> str:
    """Chama o modelo da volta. Com tool calling nativo passa `tools=`; provedor
    ou dublê de teste que não aceita um argumento recebe a chamada sem ele, e a
    resposta segue pelo leitor de texto."""
    if settings.SENTURY_NATIVE_TOOLS:
        from ..llm.tool_schemas import build_tool_schemas

        from .descoberta import nomes_da_chamada

        # O mapa continua visível mesmo sem match lexical. O modelo pode
        # carregar pelo nome, e a próxima volta inclui esse schema.
        candidatas = nomes_da_chamada(orq.turno.capacidades) \
            if settings.SENTURY_PROGRESSIVE_CAPABILITIES else None
        ferramentas = build_tool_schemas(candidatas, com_orientacao=orq.turno.passo_unico)
        medir_fatias(messages, ferramentas)
        try:
            return await orq.planner.complete(
                messages, temperature=0.1, complexity=complexity, tools=ferramentas)
        except TypeError:
            pass
    else:
        medir_fatias(messages)
    try:
        return await orq.planner.complete(messages, temperature=0.1, complexity=complexity)
    except TypeError:
        try:
            return await orq.planner.complete(messages, temperature=0.1)
        except TypeError:
            return await orq.planner.complete(messages)


def ler_payload(raw: str) -> Tuple[Dict[str, Any], str]:
    from ..llm.action_parser import _first_json_object, _repair_json, _strip_reasoning

    cleaned = _strip_reasoning(str(raw or "").strip())
    candidate = _first_json_object(cleaned)
    if not candidate:
        return {}, "missing_json"
    try:
        data = json.loads(candidate)
    except Exception:
        try:
            data = json.loads(_repair_json(candidate))
        except Exception:
            return {}, "invalid_json"
    if not isinstance(data, dict):
        return {}, "invalid_payload"
    message = data.get("message")
    if (
        data.get("action") == "respond"
        and isinstance(message, str)
        and is_transient_failure_message({"role": "assistant", "content": message})
    ):
        return data, "transient_provider_response"
    return data, "ok"


def payload_para_plano(data: Any) -> List[Dict[str, Any]]:
    """O plano escrito em texto, no formato oficial ou nas variantes comuns. O
    nome da ferramenta perde o prefixo que o provedor cola (`default_api:`),
    igual ao canal nativo: sem isso o turno morre em "ferramenta desconhecida"."""
    from ..llm.tool_schemas import _nome_limpo
    from .descoberta import desembrulhar as _pela_ponte

    return [_pela_ponte({**passo, "tool": _nome_limpo(passo["tool"])}) for passo in _passos_do_payload(data)]


def _passos_do_payload(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    raw_plan = data.get("plan")
    if isinstance(raw_plan, list):
        return [step for step in raw_plan if isinstance(step, dict) and step.get("tool")]

    action = str(data.get("action") or "").strip()
    if action == "tool_call" and isinstance(data.get("tool"), str):
        arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        return [{"tool": data["tool"], "arguments": arguments}]

    if action in {"executar_skill", "execute_skill", "skill"}:
        name = str(data.get("skill") or data.get("nome") or "").strip()
        if not name:
            return []
        arguments = dict(data.get("args") or {}) if isinstance(data.get("args"), dict) else {}
        arguments["nome"] = name
        return [{"tool": "executar_skill", "arguments": arguments}]

    if not action and isinstance(data.get("tool"), str):
        arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        return [{"tool": data["tool"], "arguments": arguments}]
    return []
