"""Valida decisões da pessoa sem misturar respostas de perguntas diferentes."""
import json
from ..tools.registry import TOOL_REGISTRY


def limites() -> tuple[int, int]:
    propriedades = TOOL_REGISTRY["perguntar_usuario"]["parametros"]["properties"]
    perguntas = propriedades["questions"]
    return perguntas["maxItems"], perguntas["items"]["properties"]["options"]["maxItems"]


def extrair(plano: list[dict], atualizar_periodo=None) -> dict | None:
    passo = next((p for p in plano if isinstance(p, dict) and p.get("tool") == "perguntar_usuario"), None)
    args = passo.get("arguments") if passo else None
    if not isinstance(args, dict) or not isinstance(args.get("questions"), list):
        return None
    teto, teto_opcoes = limites()
    perguntas = []
    for item in args["questions"][:teto]:
        if not isinstance(item, dict):
            continue
        texto = str(item.get("question") or "").strip()[:200]
        opcoes_brutas = item.get("options")
        if not texto or not isinstance(opcoes_brutas, list):
            continue
        opcoes = []
        for opcao in opcoes_brutas:
            if isinstance(opcao, str):
                rotulo, descricao = opcao.strip(), ""
            elif isinstance(opcao, dict):
                rotulo = str(opcao.get("label") or "").strip()
                descricao = str(opcao.get("description") or "").strip()
            else:
                continue
            rotulo = rotulo[:80]
            if rotulo and rotulo not in [o["label"] for o in opcoes]:
                opcoes.append({"label": rotulo, "description": descricao[:160]})
            if len(opcoes) >= teto_opcoes:
                break
        if len(opcoes) < 2:
            continue
        if atualizar_periodo is not None and "período" in texto.lower():
            opcoes = atualizar_periodo(opcoes)
        perguntas.append({"header": str(item.get("header") or "").strip()[:24] or "Escolha",
                          "question": texto, "multiSelect": item.get("multiSelect") is True,
                          "options": opcoes})
    if not perguntas:
        return None
    intro = str(args.get("intro") or "").strip()[:300] or "Antes de continuar, preciso confirmar alguns pontos."
    return {"intro": intro, "questions": perguntas}


def resposta(perguntas: list[dict], respostas: list[dict]) -> dict:
    if len(perguntas) != len(respostas) or not 1 <= len(perguntas) <= limites()[0]:
        raise ValueError("Responda todas as perguntas deste pedido.")
    saida = []
    for pergunta, item in zip(perguntas, respostas):
        if not isinstance(item, dict):
            raise ValueError("A resposta precisa de opções ou texto livre.")
        if item.get("pergunta", pergunta["question"]) != pergunta["question"]:
            raise ValueError("A pergunta mudou; responda ao pedido atual.")
        selecionadas = item.get("selecionadas", [])
        outro = item.get("outro", "")
        if not isinstance(selecionadas, list) or not all(isinstance(s, str) for s in selecionadas):
            raise ValueError("As opções precisam ser uma lista de textos.")
        if not isinstance(outro, str) or len(outro) > 500:
            raise ValueError("A resposta livre aceita até 500 caracteres.")
        selecionadas = list(dict.fromkeys(selecionadas))
        validas = {o["label"] for o in pergunta["options"]}
        if any(s not in validas for s in selecionadas) or (not pergunta["multiSelect"] and len(selecionadas) > 1):
            raise ValueError("A seleção não corresponde às opções da pergunta.")
        if not selecionadas and not outro.strip():
            raise ValueError("Falta uma resposta.")
        saida.append({"pergunta": pergunta["question"], "selecionadas": selecionadas,
                      "outro": outro.strip()})
    return {"respostas": saida}


def validar_retomada(state, texto: str) -> str:
    try:
        dado = json.loads(texto)
    except (ValueError, TypeError):
        return texto
    if not isinstance(dado, dict) or "respostas" not in dado:
        return texto
    pendente = next((m.get("clarification") for m in reversed(state.history)
                     if m.get("role") == "system" and isinstance(m.get("clarification"), dict)), None)
    if not pendente:
        return texto
    if not isinstance(dado["respostas"], list):
        raise ValueError("As respostas precisam ser uma lista.")
    return json.dumps(resposta(pendente["questions"], dado["respostas"]), ensure_ascii=False)
