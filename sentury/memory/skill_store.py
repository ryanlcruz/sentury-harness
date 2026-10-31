"""Guarda receitas de ferramentas bem-sucedidas como skills reutilizáveis.

As chamadas e argumentos vêm dos resultados da sessão e ficam num espaço
próprio do usuário no armazenamento local.
"""
import time
from typing import Any, Dict, List, Optional

_SKILL_TTL = 60 * 60 * 24 * 180  # 180 dias
_MAX_SKILLS = 30


class SkillStore:
    def __init__(self, backend: Any):
        self._backend = backend

    def _key(self, user_id: str) -> str:
        return f"uskill:{user_id}"

    async def all(self, user_id: str) -> List[Dict[str, Any]]:
        data = await self._backend.get(self._key(user_id))
        if isinstance(data, dict):
            return data.get("skills", [])
        return []

    async def save(self, user_id: str, nome: str, passos: List[Dict[str, Any]]) -> None:
        nome = nome.strip()
        skills = [s for s in await self.all(user_id) if s["nome"].lower() != nome.lower()]
        skills.append({"nome": nome, "passos": passos, "criado_em": time.time()})
        skills = skills[-_MAX_SKILLS:]
        await self._backend.set(self._key(user_id), {"skills": skills}, _SKILL_TTL)

    async def get(self, user_id: str, nome: str) -> Optional[List[Dict[str, Any]]]:
        nome_l = nome.strip().lower()
        for s in await self.all(user_id):
            if s["nome"].lower() == nome_l:
                return s["passos"]
        return None

    async def delete(self, user_id: str, nome: str) -> int:
        nome_l = nome.strip().lower()
        skills = await self.all(user_id)
        restantes = [s for s in skills if s["nome"].lower() != nome_l]
        removidos = len(skills) - len(restantes)
        if removidos:
            await self._backend.set(self._key(user_id), {"skills": restantes}, _SKILL_TTL)
        return removidos


def build_skills_context(skills: List[Dict[str, Any]]) -> Optional[str]:
    """Injeta no contexto do agente as skills/ferramentas que ele JÁ aprendeu
    com este usuário, para ele reconhecer ("já tenho algo pronto pra isso") e
    reaproveitar (executar_skill) em vez de refazer do zero: inclusive código
    de sandbox (executar_python) que foi salvo como skill."""
    if not skills:
        return None
    linhas = []
    for s in skills[-10:]:
        ferramentas = ", ".join(dict.fromkeys(p.get("tool", "") for p in s.get("passos", [])))
        linhas.append(f'- "{s["nome"]}" (usa: {ferramentas})')
    return (
        "SKILLS/FERRAMENTAS QUE VOCÊ JÁ APRENDEU com este usuário — se o pedido casar com "
        "uma delas, REUTILIZE com executar_skill (mais rápido e consistente que refazer) e "
        "diga que já tem isso pronto:\n" + "\n".join(linhas)
    )


def get_skill_store(session_store: Any) -> SkillStore:
    return SkillStore(session_store)
