"""Reaproveita o resultado de uma chamada repetida e avisa o modelo.

Devolver a observação com um lembrete evita outra execução sem deixar o modelo
sem resposta. `perguntar_usuario` fica fora porque cada pergunta é única.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

# Quanto mais o modelo insiste, mais direto fica o lembrete. Escalar importa: um
# texto igual nas cinco vezes vira ruído que ele aprende a ignorar.
_ESCALADA = {
    1: "Você já chamou esta ferramenta com estes mesmos argumentos neste turno. "
       "O resultado é o mesmo e está aí em cima: leia antes de decidir o próximo "
       "passo. Se ele não tem o que você procura, mude a abordagem — outro "
       "caminho, outros argumentos, outra ferramenta — ou responda com o que já "
       "sabe.",
    2: "Esta é a terceira vez com os mesmos argumentos. Repetir não vai trazer "
       "nada novo. Escolha: um caminho diferente, ou responder agora dizendo o "
       "que encontrou e o que faltou.",
}
_INSISTENTE = (
    "Você continua repetindo a mesma chamada. Pare de tentar por aqui: responda "
    "ao usuário com o que já tem e diga com franqueza o que não foi possível "
    "obter. Não afirme ter feito o que não fez."
)


def assinatura(tool: str, arguments: Any) -> Tuple[str, str]:
    """Identidade de uma chamada: ferramenta mais argumentos, de forma estável."""
    try:
        return (tool, json.dumps(arguments, sort_keys=True, default=str, ensure_ascii=False))
    except Exception:
        # Argumento que não serializa ainda precisa de uma identidade; `repr` é
        # pior como chave, mas some é pior ainda.
        return (tool, repr(arguments))


def conta_para_o_guarda(tool: str) -> bool:
    """Ferramenta que lê o mundo (`determinista: false` no registro) roda de
    novo: o mesmo `ver` depois de um clique vê outra tela."""
    from ..tools.registry import com_propriedade

    return tool != "perguntar_usuario" and tool not in com_propriedade("determinista", False)


def lembrete(tool: str, resultado_anterior: Any, vezes: int) -> str:
    """O texto que volta ao modelo no lugar da execução repetida.

    Carrega o resultado ANTERIOR: é ele que o modelo não estava recebendo, e sem
    ele o lembrete seria só uma reclamação.
    """
    from ..llm.prompts import build_tool_result_instruction

    observacao = build_tool_result_instruction(tool, resultado_anterior)
    aviso = _ESCALADA.get(vezes, _INSISTENTE)
    return f"{observacao}\n\n[CHAMADA REPETIDA] {aviso}"


class Repetidas:
    """O que já rodou neste turno, com o resultado e quantas vezes foi pedido."""

    def __init__(self) -> None:
        self._vistas: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def registrar(self, tool: str, arguments: Any, resultado: Any) -> None:
        self._vistas[assinatura(tool, arguments)] = {"resultado": resultado, "vezes": 0}

    def repetida(self, tool: str, arguments: Any) -> Optional[Dict[str, Any]]:
        """`None` na primeira vez. Repetindo, devolve `{resultado, vezes}`."""
        if not conta_para_o_guarda(tool):
            return None
        registro = self._vistas.get(assinatura(tool, arguments))
        if registro is None:
            return None
        registro["vezes"] += 1
        return registro

    def __contains__(self, chave: Tuple[str, str]) -> bool:
        return chave in self._vistas

    def __len__(self) -> int:
        return len(self._vistas)


_MARCA_DA_SKILL = "[INSTRUÇÃO PROCEDURAL DE SKILL CARREGADA]"


def skill_ja_carregada(historico: Any, nome: str) -> bool:
    """A skill está no histórico, com o texto inteiro, desde um carregamento anterior."""
    alvo = f"=== SKILL: {str(nome or '').strip().lower()} ==="
    return bool(nome) and any(
        m.get("role") == "system" and _MARCA_DA_SKILL in str(m.get("content") or "")
        and alvo in str(m.get("content") or "")
        for m in historico or [] if isinstance(m, dict)
    )


def aviso_de_skill_carregada(nome: str) -> str:
    """Carregar de novo não acrescenta nada: o texto já está no contexto, e repetir
    o mesmo texto só empurra o resto para fora. O aviso não leva a marca nem o
    título da skill, para não passar por ela quando o texto real sair do histórico."""
    return (f"[SKILL JÁ CARREGADA] A skill `{nome}` já está no seu contexto, numa mensagem de "
            "sistema anterior com o procedimento inteiro. Siga o próximo passo dela com as "
            "ferramentas; carregar de novo traria o mesmo texto.")
