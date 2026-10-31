"""O manual do Sentury: como usar cada ferramenta e cada skill.

Uma entrada por ferramenta na mesa do setor (descricao, orientacao, quando
usar, parametros) e uma por skill (descricao e procedimento). Cada entrada
aponta as relacionadas: a skill que usa a ferramenta e a ferramenta que a
skill usa, pelo `tools_used` do cabecalho ou pelo nome citado no procedimento.

Busca lexica em memoria, sem chamada de modelo: nome de ferramenta e de skill
e termo exato.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CORPO_DA_SKILL = 900


def _parametros(meta: Dict[str, Any]) -> str:
    props = ((meta.get("parametros") or {}).get("properties") or {})
    partes = []
    for nome, esquema in props.items():
        esquema = esquema or {}
        enum = esquema.get("enum")
        tipo = f"um de {', '.join(map(str, enum))}" if enum else str(esquema.get("type") or "")
        partes.append(f"{nome} ({tipo})" if tipo else nome)
    return ", ".join(partes)


def _skills(skill_discovery: Any) -> List[Any]:
    if skill_discovery is None:
        try:
            from ..skills.skill_discovery import SkillDiscoveryEngine
            from ..skills.skill_loader import SkillLoader

            from ..skills.escrita import pasta_do_usuario

            base = Path(__file__).resolve().parents[1] / "skills"
            skill_discovery = SkillDiscoveryEngine(SkillLoader(base, pasta_do_usuario(), com_setor=True))
        except Exception:
            logger.debug("Skills fora do manual", exc_info=True)
            return []
    try:
        return list(skill_discovery.get_available_skills())
    except Exception:
        logger.debug("Skills fora do manual", exc_info=True)
        return []


def _corpo(skill: Any) -> str:
    caminho = getattr(skill, "path", None)
    # O `path` do SkillEntry e a pasta da skill, nao o arquivo.
    if caminho and Path(caminho).is_dir():
        caminho = Path(caminho) / "SKILL.md"
    try:
        texto = Path(caminho).read_text(encoding="utf-8") if caminho else ""
    except OSError:
        return ""
    if texto.startswith("---"):
        fim = texto.find("\n---", 3)
        texto = texto[fim + 4:] if fim > 0 else texto
    return " ".join(texto.split())[:_CORPO_DA_SKILL]


def entradas(skill_discovery: Any = None) -> List[Dict[str, Any]]:
    """Uma entrada por ferramenta na mesa do setor e uma por skill."""
    from ..tools.registry import ferramentas_do_setor_ativo

    skills = _skills(skill_discovery)
    na_mesa = ferramentas_do_setor_ativo()
    corpos = {s.name: _corpo(s) for s in skills}
    # Aresta declarada no cabecalho, ou a ferramenta citada pelo nome no
    # procedimento: poucas skills declaram `tools_used`.
    usa: Dict[str, List[str]] = {
        s.name: sorted(set(map(str, getattr(s, "tools_used", None) or []))
                       | {n for n in na_mesa if f"`{n}`" in corpos[s.name] or f"{n}(" in corpos[s.name]})
        for s in skills
    }
    usada_por: Dict[str, List[str]] = {}
    for skill, ferramentas in usa.items():
        for ferramenta in ferramentas:
            usada_por.setdefault(ferramenta, []).append(skill)

    saida: List[Dict[str, Any]] = []
    for nome, meta in sorted(na_mesa.items()):
        linhas = [str(meta.get("descricao") or "").strip(), str(meta.get("orientacao") or "").strip(),
                  str(meta.get("manual") or "").strip()]
        quando = meta.get("quando_usar") or []
        if quando:
            linhas.append("Quando usar: " + "; ".join(str(q).strip() for q in quando))
        parametros = _parametros(meta)
        if parametros:
            linhas.append(f"Parametros: {parametros}")
        relacionados = [f"skill:{s}" for s in usada_por.get(nome, [])]
        saida.append({
            "id": f"ferramenta:{nome}",
            "titulo": f"Ferramenta {nome}",
            "texto": "\n".join(l for l in linhas if l),
            "fonte": "manual",
            "relacionados": relacionados,
        })
    for s in skills:
        relacionados = ([f"ferramenta:{t}" for t in usa[s.name]]
                        + [f"skill:{r}" for r in (getattr(s, "related_skills", None) or [])])
        saida.append({
            "id": f"skill:{s.name}",
            "titulo": f"Skill {s.name}",
            "texto": f"{s.description}\n{corpos[s.name]}".strip(),
            "fonte": "manual",
            "relacionados": relacionados,
        })
    return saida


class Manual:
    """Busca no manual, montado na primeira consulta."""

    def __init__(self, skill_discovery: Any = None):
        self._skill_discovery = skill_discovery
        self._busca: Optional[Any] = None

    def _backend(self):
        if self._busca is None:
            from .retriever import _LexicalBackend

            self._originais = {e["id"]: e for e in entradas(self._skill_discovery)}
            # O mesmo radical da busca de ferramentas: "diagrama" acha "diagrams".
            self._busca = _LexicalBackend([
                {"id": e["id"], "titulo": _radicais(e["titulo"]), "texto": _radicais(e["texto"])}
                for e in self._originais.values()
            ])
        return self._busca

    def buscar(self, consulta: str, k: int = 3) -> List[Dict[str, Any]]:
        if not str(consulta or "").strip():
            return []
        achados = self._backend().search(_radicais(consulta), k)
        return [{**self._originais[a["id"]], "score": a["score"]} for a in achados]


def _radicais(texto: str) -> str:
    from ..tools.capability_catalog import _tokens

    return " ".join(_tokens(texto))


_MANUAL: Optional[Manual] = None


def manual() -> Manual:
    global _MANUAL
    if _MANUAL is None:
        _MANUAL = Manual()
    return _MANUAL


def esquecer() -> None:
    """Remonta o manual na próxima consulta: uma skill nova ou corrigida entra nele."""
    global _MANUAL
    _MANUAL = None
