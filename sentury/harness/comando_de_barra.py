"""Comandos de barra (`/skills`, `/learn`, `/curator`) e o menu de skills.

Comando de barra é ordem direta: responde sem passar pelo modelo, porque não
há nada a interpretar.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..skills.skill_loader import vitrine_das_skills

_SKILL_GROUP_ORDER = ["Diagnóstico", "Planos", "Visuais", "Relatório", "Pesquisa", "Decisão"]
# Ferramenta de quem desenvolve o Sentury, sem interesse para quem usa.
_SKILL_HIDDEN = {"github-pr-workflow", "jupyter-live-kernel"}
_OUTRAS_GRUPO = "Aprendidas e outras"


def _grupo(nome: str) -> str:
    return re.sub(r"^[^\w]+", "", str(nome or ""), flags=re.UNICODE).strip() or _OUTRAS_GRUPO


def _format_skills_pretty(skills) -> str:
    """`skills`: iterável de (nome, descrição).

    As skills da vitrine saem no grupo e com a descrição curada; qualquer outra
    (aprendida na conversa ou SKILL.md novo) aparece em "Aprendidas e outras"
    com a descrição dela.
    """
    grupos: Dict[str, List[str]] = {}
    vistos = set()
    vitrine = vitrine_das_skills()
    for item in skills:
        nome, desc = item if isinstance(item, (tuple, list)) else (item, "")
        if not nome or nome in vistos or nome in _SKILL_HIDDEN:
            continue
        vistos.add(nome)
        info = vitrine.get(nome)
        if info:
            grupo, d = _grupo(info[0]), info[1]
        else:
            grupo, d = _OUTRAS_GRUPO, (str(desc).strip() or "skill disponível")
        grupos.setdefault(grupo, []).append(f"• {nome} — {d}")
    if not grupos:
        return "Ainda não tenho skills especiais carregadas."
    partes = ["**O que sei fazer de especial:**", ""]
    extras = sorted(g for g in grupos if g not in _SKILL_GROUP_ORDER and g != _OUTRAS_GRUPO)
    for g in _SKILL_GROUP_ORDER + extras + [_OUTRAS_GRUPO]:
        if g in grupos:
            partes.append(f"**{g}**")
            partes.extend(sorted(grupos[g]))
            partes.append("")
    partes.append("É só pedir — pelo nome ou pelo que você quer que eu faça.")
    return "\n".join(partes).strip()


async def skills_disponiveis(orquestrador: Any, state: Any) -> List[Tuple[str, str]]:
    """As skills procedurais do loader mais as receitas salvas por esta pessoa."""
    todas = [(e.name, getattr(e, "description", "")) for e in orquestrador.skill_loader.scan_skills()]
    if orquestrador.skills:
        salvas = await orquestrador.skills.all(state.user_id)
        todas += [(s["nome"], s.get("descricao") or "skill salva na conversa") for s in salvas]
    return todas


def _resposta(orquestrador: Any, state: Any, user_message: str, texto: str,
              ferramenta: str, motivo: str, aprendido: Optional[str] = None) -> Dict[str, Any]:
    state.history.append(orquestrador._msg_usuario(state, user_message))
    state.history.append({"role": "assistant", "content": texto})
    return {
        "message": texto,
        "attachment": None,
        "harness": {"proposed_tool": ferramenta, "harness_allowed": True,
                    "harness_reason": motivo, "events": []},
        "state": state.to_dict(),
        "learned": aprendido,
        # O mesmo cartão "Aprendi" de um turno comum, com o desfazer.
        "aprendizados": [{"tipo": "skill", "nome": aprendido, "acao": "criada"}] if aprendido else None,
        "telemetry": {"execution_ms": 1},
        "compacted": False,
    }


_COMO_USAR_O_LEARN = (
    "Diga o nome da tarefa antes do texto: `/learn revisao-de-contrato: começar pela "
    "cláusula de multa`. O nome é o da classe de tarefa, para a skill servir da próxima "
    "vez. Se preferir, peça na conversa (\"aprenda isto: ...\") e o Sentury escolhe o nome."
)


def _aprender(argumentos: str) -> Tuple[str, Optional[str]]:
    """`/learn nome: texto` grava pelo mesmo caminho do `aprender_skill`: compara
    com as parecidas, guarda histórico e aparece no desfazer. Sem modelo no
    comando, o nome vem da pessoa."""
    from ..skills import escrita

    nome, separador, corpo = argumentos.partition(":")
    if not separador or not nome.strip() or not corpo.strip():
        return _COMO_USAR_O_LEARN, None
    resultado = escrita.criar(nome.strip(), corpo.strip().splitlines()[0], corpo.strip())
    if resultado.get("status") == "criada":
        slug = resultado["skill"]
        return f"Guardei a skill `{slug}`. Se não era isso, use o desfazer logo abaixo.", slug
    if resultado.get("parecidas"):
        nomes = ", ".join(f"`{p.get('nome') or p.get('skill')}`" for p in resultado["parecidas"])
        return (f"Já existe skill sobre quase o mesmo assunto: {nomes}. Peça na conversa para "
                "corrigir a que existe, ou use outro nome se a tarefa for de fato outra."), None
    return str(resultado.get("erro") or "Não consegui guardar a skill."), None


async def responder(orquestrador: Any, state: Any, user_message: str) -> Optional[Dict[str, Any]]:
    """A resposta do comando, ou `None` quando a mensagem não é um comando."""
    texto = user_message.strip()
    if not texto.startswith("/"):
        return None
    nome, _, argumentos = texto[1:].partition(" ")
    nome = nome.lower()

    if nome in ("skills", "list"):
        menu = _format_skills_pretty(await skills_disponiveis(orquestrador, state))
        return _resposta(orquestrador, state, user_message, menu, "listar_skills",
                         "Comando de barra executado determinísticamente")

    if nome == "learn":
        texto, slug = _aprender(argumentos)
        return _resposta(orquestrador, state, user_message, texto, "aprender_skill",
                         "Comando de barra executado determinísticamente", aprendido=slug)

    if nome == "curator":
        from ..skills.curator import SkillCurator

        curador = SkillCurator(orquestrador.user_skills_dir, orquestrador.skill_usage_tracker)
        resultado = curador.run_curator(stale_days=30, archive_days=90, dry_run=False)
        return _resposta(orquestrador, state, user_message, f"Curator executado com sucesso: {resultado}",
                         "run_curator", "Curator manual executado")

    return None
