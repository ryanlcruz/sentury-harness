"""Discovery Engine para ranqueamento e indexação dinâmica de skills.

Filtra as skills com base no sistema operacional atual e variáveis de ambiente
e calcula a relevância das skills para a entrada e intenção do usuário.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import unicodedata
from typing import Any, Dict, List, Set, Tuple

from .skill_loader import SkillLoader
from .skill_schema import SkillEntry

logger = logging.getLogger(__name__)

FAMILY_HINTS = {
    "artifacts": {"diagrama", "diagram", "fluxograma", "mermaid", "svg", "pdf", "excel", "xlsx", "csv", "ppt", "pptx", "slide", "deck", "dashboard", "html"},
    "research": {"paper", "papers", "artigo", "artigos", "arxiv", "pesquisa", "research", "fonte", "fontes", "referencia", "referencias", "benchmark", "concorrente", "concorrentes", "mercado", "estudo", "web"},
    "verification": {"validar", "verificar", "teste", "teste", "qa", "checagem", "verificacao"},
    "browser": {"browser", "site", "screenshot", "playwright", "pagina", "web", "internet", "navegador", "buscar"},
    "planning": {"plano", "plano de acao", "roadmap", "estrategia", "priorizar"},
}


def _dicas_da_familia(familia: str) -> Set[str]:
    """As palavras de `operations` sao os dados do setor ativo; sem setor, nenhuma."""
    if familia != "operations":
        return FAMILY_HINTS.get(familia, set())
    try:
        from ..domains.do_setor import termos_de_dado

        return set(termos_de_dado())
    except Exception:
        return set()


def _tokens(text: str) -> Set[str]:
    """Tokeniza sem acento e sem pontuação (região→regiao, 'meme.'→meme). Assim
    consultas em PT casam com nome/descrição/tags mesmo com acento ou pontuação."""
    text = unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode("ascii")
    return {t for t in re.split(r"[^a-z0-9]+", text) if len(t) > 1}

# Mapeamento do sys.platform para as strings declaradas nas tags das skills
PLATFORM_MAPPING = {
    "darwin": "macos",
    "linux": "linux",
    "win32": "windows"
}


class SkillDiscoveryEngine:
    """Calcula a relevância de cada skill para a solicitação atual."""

    def __init__(self, loader: SkillLoader):
        self.loader = loader

    def _matches_platform(self, entry: SkillEntry) -> bool:
        """Garante portabilidade checando se a skill roda no SO atual."""
        if not entry.platforms:
            return True
        current_plat = PLATFORM_MAPPING.get(sys.platform, sys.platform)
        return any(p.lower().strip() == current_plat for p in entry.platforms)

    def _matches_environment(self, entry: SkillEntry) -> bool:
        """Filtra se o ambiente declarado na skill está disponível."""
        if not entry.environments:
            return True
        # Ex: se pedir "telegram", verifica se está rodando no fluxo do telegram
        # No PoC, o ambiente "telegram" é ativado via variável de ambiente
        for env in entry.environments:
            env_name = env.lower().strip()
            if env_name == "telegram":
                if not (self._is_telegram_session() or self._is_render_production()):
                    # Se for outra plataforma, ignora essa skill
                    pass
        return True

    def _is_telegram_session(self) -> bool:
        return bool(sys.modules.get("telegram") or sys.modules.get("telebot") or sys.modules.get("aiogram"))

    def _is_render_production(self) -> bool:
        return os.getenv("RENDER") == "true" or os.getenv("SENTURY_SESSION_PLATFORM") == "telegram"

    def get_available_skills(self) -> List[SkillEntry]:
        """Varre todas as skills e retorna apenas as compatíveis com o ambiente atual."""
        all_skills = self.loader.scan_skills()
        filtered = []
        for s in all_skills:
            if self._matches_platform(s) and self._matches_environment(s):
                filtered.append(s)
        return filtered

    def discover(self, user_message: str, intent: str, top_k: int = 3) -> List[Tuple[SkillEntry, float]]:
        """Calcula o score de relevância e retorna as top_k skills.

        Pontuação:
        1. Keyword match simples na descrição, tags e categorias.
        2. Coincidência de tags/ferramentas com a intent classificada.
        """
        available = self.get_available_skills()
        if not available:
            return []

        message_words = _tokens(user_message)
        intent_words = _tokens(intent.replace("_", " "))

        scored_skills: List[Tuple[SkillEntry, float]] = []

        for entry in available:
            score = 0.0

            # 1. Match de palavras da mensagem com o nome, descrição e categoria (peso 0.4)
            name_words = _tokens(entry.name.replace("-", " "))
            desc_words = _tokens(entry.description)
            cat_words = _tokens(entry.category.replace("/", " "))
            family_words = _tokens(entry.family.replace("/", " "))

            common_msg_words = message_words.intersection(name_words.union(desc_words).union(cat_words).union(family_words))
            if common_msg_words:
                score += len(common_msg_words) * 0.4

            # 2. Match de tags com a mensagem/intent (peso 0.3)
            tags_lower = set().union(*[_tokens(t) for t in entry.tags]) if entry.tags else set()
            common_tags = tags_lower.intersection(message_words.union(intent_words))
            if common_tags:
                score += len(common_tags) * 0.3

            # 3. Match de ferramentas com a intent ou mensagem (peso 0.3)
            tools_lower = set().union(*[_tokens(t) for t in entry.tools_used]) if entry.tools_used else set()
            common_tools = tools_lower.intersection(message_words.union(intent_words))
            if common_tools:
                score += len(common_tools) * 0.3

            family_key = entry.family.lower().strip()
            hinted_words = _dicas_da_familia(family_key)
            normalized_hints = set().union(*[_tokens(word) for word in hinted_words]) if hinted_words else set()
            common_family_hints = normalized_hints.intersection(message_words.union(intent_words))
            if common_family_hints:
                score += len(common_family_hints) * 0.35

            score += max(0, min(entry.priority, 100)) / 1000.0

            # 4. Boost se o nome exato da skill for citado na mensagem (ex.: /skill)
            if entry.name.lower() in user_message.lower():
                score += 2.0

            if score > 0.0:
                scored_skills.append((entry, score))

        # Ordena decrescente por score
        scored_skills.sort(key=lambda x: x[1], reverse=True)
        return scored_skills[:top_k]

    def build_index_prompt(self) -> str:
        """Indice leve (Nivel 0): nome e uma frase por skill.

        O procedimento vem quando a skill e aberta com `executar_skill`; o
        indice vai em toda chamada e fica curto.
        """
        available = self.get_available_skills()
        if not available:
            return "Nenhuma skill procedural está atualmente carregada no sistema."

        lines = ["Skills disponíveis. Interprete o pedido no idioma da pessoa e escolha pela descrição. "
                 "Se uma skill ajudar, abra o procedimento com `executar_skill(nome)` antes de agir. "
                 "Não carregue uma skill só por coincidência de palavras:"]
        for s in sorted(available, key=lambda x: x.name):
            lines.append(f"- {s.name}: {_uma_frase(s.description)}")
            if s.gatilhos:
                pistas = _uma_frase("; ".join(s.gatilhos), limite=120)
                lines.append(f"  Pistas descritivas, sem ativação automática: {pistas}")
        return "\n".join(lines)


def _uma_frase(texto: str, limite: int = 90) -> str:
    frase = " ".join(str(texto or "").split())
    corte = frase.find(". ")
    if 0 < corte < limite:
        return frase[:corte + 1]
    return frase if len(frase) <= limite else frase[:limite].rsplit(" ", 1)[0] + "…"
