"""Parser e indexador de skills no filesystem do Sentury.

Responsável por escanear diretórios de skills, ler o frontmatter YAML dos SKILL.md,
aplicar pré-processamento de variáveis (template substitution) e inline shell.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .skill_schema import SkillContent, SkillEntry, SkillMetadata

logger = logging.getLogger(__name__)

# Componentes de subpastas ignorados na varredura padrão de standalone skills
EXCLUDED_SKILL_DIRS = {
    ".git",
    ".github",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    ".pytest_cache",
    ".archive",
    # Versões anteriores das skills escritas pelo agente (skills/escrita.py).
    ".historico",
}
SKILL_SUPPORT_DIRS = {"references", "templates", "assets", "scripts"}

# Padrões regex para substituição e comandos shell
TEMPLATE_VAR_RE = re.compile(r"\$\{(SENTURY_SKILLS_DIR|SENTURY_SESSION_ID)\}")
INLINE_SHELL_RE = re.compile(r"!`([^`\n]+)`")
MAX_SHELL_OUTPUT_CHARS = 4000


def _metadado(frontmatter: Dict[str, Any], campo: str, padrao: Any = None) -> Any:
    if campo in frontmatter:
        return frontmatter[campo]
    metadata = frontmatter.get("metadata")
    if isinstance(metadata, dict):
        if campo in metadata:
            return metadata[campo]
        for bloco in metadata.values():
            if isinstance(bloco, dict) and campo in bloco:
                return bloco[campo]
    return padrao


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Parseia o frontmatter YAML de um texto markdown.

    Retorna um dicionário com os metadados e o corpo restante do markdown.
    Garante resiliência: se o YAML for malformado, faz um split key-value básico.
    """
    frontmatter: Dict[str, Any] = {}
    body = content

    if not content.startswith("---"):
        return frontmatter, body

    # Acha o encerramento do frontmatter
    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return frontmatter, body

    yaml_content = content[3 : end_match.start() + 3]
    body = content[end_match.end() + 3 :]

    try:
        import yaml
        loader = getattr(yaml, "CSafeLoader", None) or yaml.SafeLoader
        parsed = yaml.load(yaml_content, Loader=loader)
        if isinstance(parsed, dict):
            frontmatter = parsed
    except Exception as exc:
        logger.debug("Falha ao usar PyYAML no frontmatter, utilizando fallback simples: %s", exc)
        # Fallback simples key-value
        for line in yaml_content.strip().split("\n"):
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            frontmatter[k.strip()] = v.strip()

    return frontmatter, body


class SkillLoader:
    """Carrega, pré-processa e gerencia o cache de skills do filesystem."""

    def __init__(
        self,
        built_in_dir: Path,
        user_dir: Optional[Path] = None,
        *,
        com_setor: bool = False,
    ):
        self.built_in_dir = Path(built_in_dir).resolve()
        self.user_dir = Path(user_dir).resolve() if user_dir else None
        # Explicito de proposito: um loader apontado para uma pasta qualquer
        # nao pode puxar as skills do setor ativo da maquina junto. Quem quer
        # o setor pede: o resto fica isolado.
        self.com_setor = bool(com_setor)
        
        self._skills_cache: Dict[str, SkillContent] = {}
        self._index_cache: List[SkillEntry] = []
        self._index_roots: Tuple[Path, ...] = ()
        self._last_scan_time: float = 0.0

    def _get_skill_roots(self) -> List[Path]:
        """Do usuario, do setor ativo, e embutidas, nesta ordem.

        O primeiro nome achado vence: a copia que o agente corrigiu na pasta
        do usuario vale sobre a embutida, sem mexer no repositorio. A do setor
        liga e desliga com ele, para as skills de CX nao ficarem na mesa de
        quem escolheu o generalista.
        """
        roots = [self.user_dir] if self.user_dir else []
        do_setor = self._raiz_do_setor() if self.com_setor else None
        if do_setor:
            roots.append(do_setor)
        roots.append(self.built_in_dir)
        return [r for r in roots if r.exists()]

    @staticmethod
    def _raiz_do_setor() -> Optional[Path]:
        """Pasta de skills do pacote do setor ativo, quando ele traz as proprias."""
        try:
            from ..domains.carregador import skills_do_pacote
            from ..domains.escolha import GENERALISTA
            from ..domains.registry import get_active_domain

            nome = str(getattr(get_active_domain(), "name", "") or "")
            if not nome or nome == GENERALISTA:
                return None
            return skills_do_pacote(nome)
        except Exception:
            logger.debug("Skills do setor nao foram lidas", exc_info=True)
            return None

    def is_support_path(self, path: Path) -> bool:
        """Determina se o arquivo está contido em uma subpasta de suporte (ex: references/)."""
        parts = path.parts
        for idx, part in enumerate(parts[:-1]):
            if part in SKILL_SUPPORT_DIRS and idx > 0:
                skill_root = Path(*parts[:idx])
                if (skill_root / "SKILL.md").exists():
                    return True
        return False

    def scan_skills(self, force: bool = False) -> List[SkillEntry]:
        """Varre os diretórios de busca e monta um índice Nível 0 compacto de metadados.

        Utiliza checagem mtime rápida para evitar re-leitura de arquivos estáveis.
        """
        roots = self._get_skill_roots()
        if not roots:
            self._index_cache = []
            self._index_roots = ()
            return []

        # Checa mtime máximo das pastas raiz
        current_mtimes = []
        for r in roots:
            try:
                current_mtimes.append(r.stat().st_mtime)
            except OSError:
                pass
        max_mtime = max(current_mtimes) if current_mtimes else 0.0

        # O mtime máximo pode ser o mesmo ao ligar/desligar um DomainPack.
        # Reusar o índice de outras raízes esconde a skill nova ou vaza a antiga.
        if (not force and self._index_cache and tuple(roots) == self._index_roots
                and max_mtime <= self._last_scan_time):
            return self._index_cache

        entries: List[SkillEntry] = []
        seen_names = set()

        for root in roots:
            for path in root.rglob("SKILL.md"):
                # Ignora pastas de cache/dependências ou subpastas de suporte
                if any(p in EXCLUDED_SKILL_DIRS for p in path.parts) or self.is_support_path(path):
                    continue

                try:
                    content = path.read_text(encoding="utf-8")
                    fm, _ = parse_frontmatter(content)
                    
                    name = str(fm.get("name") or path.parent.name).strip().lower()
                    if not name or name in seen_names:
                        continue

                    # Lê metadados também do formato aninhado de skills importadas.
                    tags = list(_metadado(fm, "tags", []) or [])
                    
                    category = _metadado(fm, "category", "general")
                    category = str(category).strip()

                    family = _metadado(fm, "family", "operations")
                    family = str(family).strip()

                    priority_raw = _metadado(fm, "priority", 50)
                    try:
                        priority = int(priority_raw)
                    except (TypeError, ValueError):
                        priority = 50

                    entry = SkillEntry(
                        name=name,
                        description=str(fm.get("description") or "Sem descrição.").strip(),
                        category=category,
                        family=family,
                        priority=priority,
                        tags=tags,
                        path=path.parent.resolve(),
                        tools_used=list(fm.get("tools_used") or []),
                        platforms=list(fm.get("platforms") or []),
                        environments=list(fm.get("environments") or []),
                        license=str(fm.get("license") or "MIT").strip(),
                        dependencies=list(fm.get("dependencies") or []),
                        gatilhos=[
                            str(g) for g in (
                                fm.get("gatilhos")
                                or fm.get("metadata", {}).get("gatilhos")
                                or []
                            ) if str(g).strip()
                        ],
                        vitrine=(
                            str((fm.get("vitrine") or {}).get("grupo") or ""),
                            str((fm.get("vitrine") or {}).get("rotulo") or ""),
                        )
                    )
                    entries.append(entry)
                    seen_names.add(name)
                except Exception as exc:
                    logger.warning("Falha ao escanear skill em %s: %s", path, exc)

        self._index_cache = entries
        self._index_roots = tuple(roots)
        self._last_scan_time = max_mtime
        return self._index_cache

    def load_skill(self, name: str, session_id: Optional[str] = None) -> Optional[SkillContent]:
        """Carrega e preprocessa o conteúdo Nível 1 (completo) de uma skill.

        Retorna o SkillContent contendo metadados e o corpo markdown processado.
        """
        name = name.strip().lower()
        
        # Garante que o índice esteja populado para busca confiável pelo nome no frontmatter
        self.scan_skills()
        
        skill_md_path: Optional[Path] = None
        for entry in self._index_cache:
            if entry.name == name:
                skill_md_path = entry.path / "SKILL.md"
                break
        
        # Fallback de busca direta por pasta se não localizado no índice
        if not skill_md_path:
            for root in self._get_skill_roots():
                candidate = root / name / "SKILL.md"
                if candidate.is_file():
                    skill_md_path = candidate
                    break
                # Busca recursiva no caso de subcategorias (ex: cx/root-cause-analysis)
                for path in root.rglob("SKILL.md"):
                    if path.parent.name == name and not self.is_support_path(path):
                        skill_md_path = path
                        break
                if skill_md_path:
                    break

        if not skill_md_path:
            logger.warning("Skill '%s' não localizada nos repositórios.", name)
            return None

        try:
            content = skill_md_path.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(content)
            
            # Mapeia arquivos auxiliares disponíveis
            refs = []
            skill_dir = skill_md_path.parent
            for folder in SKILL_SUPPORT_DIRS:
                subfolder = skill_dir / folder
                if subfolder.is_dir():
                    for file in subfolder.rglob("*"):
                        if file.is_file():
                            refs.append(str(file.relative_to(skill_dir).as_posix()))

            # Lê metadados também do formato aninhado de skills importadas.
            tags = list(_metadado(fm, "tags", []) or [])
            
            related = list(_metadado(fm, "related_skills", []) or [])

            category = _metadado(fm, "category", "general")
            category = str(category).strip()

            family = _metadado(fm, "family", "operations")
            family = str(family).strip()

            priority_raw = _metadado(fm, "priority", 50)
            try:
                priority = int(priority_raw)
            except (TypeError, ValueError):
                priority = 50

            metadata = SkillMetadata(
                name=name,
                description=str(fm.get("description") or "").strip(),
                version=str(fm.get("version") or "1.0.0").strip(),
                category=category,
                family=family,
                priority=priority,
                tags=tags,
                related_skills=related,
                tools_used=list(fm.get("tools_used") or []),
                author=str(fm.get("author") or "Sentury").strip(),
                platforms=list(fm.get("platforms") or []),
                environments=list(fm.get("environments") or []),
                license=str(fm.get("license") or "MIT").strip(),
                dependencies=list(fm.get("dependencies") or []),
                origem=str(fm.get("origem") or "").strip(),
            )

            # Pré-processamento
            processed_body = self._preprocess(body, skill_dir, session_id, de_fora=bool(metadata.origem))

            return SkillContent(
                metadata=metadata,
                body=processed_body,
                available_references=refs,
                path=skill_dir.resolve()
            )
        except Exception as exc:
            logger.error("Falha ao carregar skill %s: %s", name, exc, exc_info=True)
            return None

    def load_reference(self, name: str, relative_path: str) -> Optional[str]:
        """Carrega e retorna o conteúdo textual Nível 2 de uma referência de suporte."""
        name = name.strip().lower()
        cleaned_path = relative_path.replace("\\", "/").strip().lstrip("/")
        
        # Proteção contra Directory Traversal
        if ".." in cleaned_path:
            logger.warning("Tentativa de Directory Traversal detectada: %s", relative_path)
            return None

        # Resolve o diretório raiz da skill
        skill_dir: Optional[Path] = None
        for root in self._get_skill_roots():
            candidate = root / name
            if (candidate / "SKILL.md").is_file():
                skill_dir = candidate
                break
            for path in root.rglob("SKILL.md"):
                if path.parent.name == name and not self.is_support_path(path):
                    skill_dir = path.parent
                    break
            if skill_dir:
                break

        if not skill_dir:
            return None

        target_file = (skill_dir / cleaned_path).resolve()
        # Garante que o arquivo de destino está contido na pasta da skill e existe
        if not target_file.is_file() or not target_file.is_relative_to(skill_dir):
            logger.warning("Arquivo de referência não localizado ou fora do limite da skill: %s", target_file)
            return None

        try:
            return target_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("Falha ao ler referência %s da skill %s: %s", relative_path, name, exc)
            return None

    def _preprocess(self, body: str, skill_dir: Path, session_id: Optional[str], de_fora: bool = False) -> str:
        """Aplica substituições de variáveis e expansões inline-shell configuradas.

        Skill instalada de fora nunca expande shell: o comando rodaria só por ela
        ser carregada, sem passar pela aprovação de script.
        """
        if not body:
            return body

        # 1. Substituição de variáveis
        def _replace_var(match: re.Match) -> str:
            token = match.group(1)
            if token == "SENTURY_SKILLS_DIR":
                return str(skill_dir.resolve())
            if token == "SENTURY_SESSION_ID" and session_id:
                return str(session_id)
            return match.group(0)

        body = TEMPLATE_VAR_RE.sub(_replace_var, body)

        # 2. Execução inline-shell (apenas se explicitamente habilitado via ambiente)
        if not de_fora and os.getenv("SENTURY_ENABLE_SKILLS_INLINE_SHELL") == "1" and "!`" in body:
            def _replace_shell(match: re.Match) -> str:
                cmd = match.group(1).strip()
                if not cmd:
                    return ""
                return self._run_shell_cmd(cmd, skill_dir)
            body = INLINE_SHELL_RE.sub(_replace_shell, body)

        return body

    def _run_shell_cmd(self, command: str, cwd: Path) -> str:
        """Executa um comando de forma protegida."""
        # Se for no windows, oculta a janela cmd.exe
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        try:
            res = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=10,
                startupinfo=startupinfo
            )
            # `stdout`/`stderr` podem vir vazios quando o shell nem chega a abrir.
            output = ((res.stdout if res.returncode == 0 else res.stderr) or "").strip()
            if len(output) > MAX_SHELL_OUTPUT_CHARS:
                output = output[:MAX_SHELL_OUTPUT_CHARS] + "... [truncado]"
            return output
        except subprocess.TimeoutExpired:
            return f"[erro: comando excedeu limite de 10s: {command}]"
        except Exception as exc:
            return f"[erro shell: {exc}]"

def vitrine_das_skills() -> Dict[str, Tuple[str, str]]:
    """Como cada skill se apresenta, lido do proprio SKILL.md.

    Mora no SKILL.md para o rotulo sair junto com a skill: desligar um setor
    tira as skills dele e os rotulos delas de uma vez.
    """
    try:
        raiz = Path(__file__).resolve().parent
        return {
            e.name: e.vitrine
            for e in SkillLoader(raiz, com_setor=True).scan_skills()
            if getattr(e, "vitrine", ("", ""))[0]
        }
    except Exception:
        logger.debug("Vitrine das skills nao foi lida", exc_info=True)
        return {}
