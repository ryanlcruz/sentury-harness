from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_ROLE_FILES = {
    "planner": "PLANNER.md",
    "responder": "RESPONDER.md",
    "subagent": "SUBAGENT.md",
}

_DOCUMENTS = {
    "soul": {
        "filename": "SOUL.md",
        "label": "Identidade",
        "description": "Quem o Sentury e e como ele se porta. Vale para todos os papeis.",
        "roles": ["planner", "responder", "subagent"],
    },
    "planner": {
        "filename": "PLANNER.md",
        "label": "Planejador",
        "description": "Como investigar, escolher ferramentas e estruturar a execucao.",
        "roles": ["planner"],
    },
    "responder": {
        "filename": "RESPONDER.md",
        "label": "Resposta",
        "description": "Como consolidar evidencias e entregar a resposta final.",
        "roles": ["responder"],
    },
    "subagent": {
        "filename": "SUBAGENT.md",
        "label": "Subagentes beta",
        "description": "Limites e formato de devolucao dos especialistas delegados.",
        "roles": ["subagent"],
    },
}

_SUSPICIOUS_PATTERNS = (
    (re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions?", re.I), "Instrucao para ignorar regras anteriores."),
    (re.compile(r"(reveal|print|show)\s+(the\s+)?(system|developer)\s+prompt", re.I), "Possivel tentativa de expor prompt protegido."),
    (re.compile(r"(exfiltrate|send|upload).{0,40}(secret|token|api[_ -]?key|credential)", re.I | re.S), "Possivel instrucao de exfiltracao de credenciais."),
)


class ContextDocumentError(ValueError):
    """Base error for editable prompt-context documents."""


class UnknownContextDocument(ContextDocumentError):
    pass


class ContextRevisionConflict(ContextDocumentError):
    pass


class ContextDocumentValidationError(ContextDocumentError):
    def __init__(self, message: str, *, warnings: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.warnings = list(warnings or [])


@dataclass(frozen=True)
class _CachedDocument:
    signature: Tuple[int, int]
    content: str


class PromptContextEngine:
    """Carrega contexto editável sem substituir as regras do núcleo.

    Os arquivos são recarregados quando mudam, sem reiniciar o servidor.
    """

    def __init__(
        self,
        root: Optional[Path] = None,
        *,
        enabled: bool = True,
        max_chars: int = 12_000,
    ) -> None:
        self.root = Path(root) if root else Path(__file__).resolve().parent
        self.enabled = bool(enabled)
        self.max_chars = max(1_000, int(max_chars))
        self._cache: Dict[str, _CachedDocument] = {}

    @staticmethod
    def _revision(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _document_spec(self, key: str) -> Dict[str, Any]:
        normalized = str(key or "").strip().lower()
        spec = _DOCUMENTS.get(normalized)
        if not spec:
            raise UnknownContextDocument(f"Documento de contexto desconhecido: {key}")
        return {"key": normalized, **spec}

    def _document_path(self, key: str) -> Tuple[Dict[str, Any], Path]:
        spec = self._document_spec(key)
        return spec, self.root / spec["filename"]

    def _read_document_content(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except FileNotFoundError:
            return ""
        except (OSError, UnicodeError) as exc:
            raise ContextDocumentError(f"Nao foi possivel ler {path.name}: {exc}") from exc

    def get_document(self, key: str) -> Dict[str, Any]:
        """Return one editable document and an optimistic-lock revision."""
        spec, path = self._document_path(key)
        content = self._read_document_content(path)
        modified_at = None
        exists = path.is_file()
        if exists:
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            except OSError:
                modified_at = None
        return {
            **spec,
            "content": content,
            "exists": exists,
            "chars": len(content),
            "revision": self._revision(content),
            "modified_at": modified_at,
            "active": bool(self.enabled and content.strip()),
        }

    def list_documents(self, *, include_content: bool = True) -> List[Dict[str, Any]]:
        documents = []
        for key in _DOCUMENTS:
            document = self.get_document(key)
            if not include_content:
                document.pop("content", None)
            documents.append(document)
        return documents

    def status(self, *, include_content: bool = True) -> Dict[str, Any]:
        """Describe the active composition without exposing the protected core."""
        return {
            "engine": "sentury-prompt-context",
            "enabled": self.enabled,
            "hot_reload": True,
            "max_chars": self.max_chars,
            "documents": self.list_documents(include_content=include_content),
            "composition": [
                {"slot": 1, "label": "Identidade", "source": "protegida", "editable": False},
                {"slot": 2, "label": "Contrato central", "source": "Python", "editable": False},
                {"slot": 3, "label": "Playbook do papel", "source": "PLANNER / RESPONDER / SUBAGENT", "editable": True},
            ],
            "session_context": {
                "manager": "ContextBudgetManager",
                "purpose": "compactacao e continuidade da conversa",
                "editable_here": False,
            },
        }

    def validate_document(self, key: str, content: str) -> Dict[str, Any]:
        spec = self._document_spec(key)
        if not isinstance(content, str):
            raise ContextDocumentValidationError("O conteudo precisa ser texto UTF-8.")
        normalized = content.replace("\r\n", "\n").replace("\r", "\n")
        if "\x00" in normalized:
            raise ContextDocumentValidationError("O documento contem um caractere NUL invalido.")
        if len(normalized) > self.max_chars:
            raise ContextDocumentValidationError(
                f"{spec['filename']} excede o limite de {self.max_chars} caracteres."
            )
        warnings = [message for pattern, message in _SUSPICIOUS_PATTERNS if pattern.search(normalized)]
        return {
            "content": normalized,
            "chars": len(normalized),
            "warnings": warnings,
            "valid": True,
        }

    def save_document(
        self,
        key: str,
        content: str,
        *,
        expected_revision: Optional[str] = None,
        accept_warnings: bool = False,
    ) -> Dict[str, Any]:
        """Validate and atomically replace an editable context document."""
        spec, path = self._document_path(key)
        current_content = self._read_document_content(path)
        current_revision = self._revision(current_content)
        if expected_revision and expected_revision != current_revision:
            raise ContextRevisionConflict(
                f"{spec['filename']} mudou desde que foi aberto. Recarregue antes de salvar."
            )

        validation = self.validate_document(key, content)
        warnings = validation["warnings"]
        if warnings and not accept_warnings:
            raise ContextDocumentValidationError(
                "Revise os alertas antes de salvar.", warnings=warnings
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(validation["content"])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

        self._cache.pop(spec["filename"], None)
        saved = self.get_document(key)
        saved["warnings"] = warnings
        return saved

    def reload(self) -> Dict[str, Any]:
        self._cache.clear()
        return self.status(include_content=True)

    def _read(self, filename: str) -> str:
        if not self.enabled:
            return ""
        path = self.root / filename
        try:
            stat = path.stat()
        except OSError:
            return ""
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = self._cache.get(filename)
        if cached and cached.signature == signature:
            return cached.content
        try:
            content = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""
        if len(content) > self.max_chars:
            content = content[: self.max_chars].rstrip() + "\n\n[overlay truncated]"
        self._cache[filename] = _CachedDocument(signature, content)
        return content

    def _pasta_do_setor(self) -> Optional[Path]:
        """A pasta do setor ligado agora, quando ela existe.

        Só vale para o engine da instalação: apontado para outra raiz (um
        teste, uma cópia), o que manda é a raiz dada.
        """
        if self.root != Path(__file__).resolve().parent:
            return None
        try:
            from ..domains import get_active_domain
            from ..domains.carregador import pasta_dos_pacotes

            alvo = pasta_dos_pacotes() / get_active_domain().name
            return alvo if alvo.is_dir() else None
        except Exception:
            return None

    def _ler_do_setor(self, filename: str) -> str:
        """Overlay que o pacote do setor traz, se trouxer.

        É o que faz o DomainPack especializar de verdade: o playbook entra
        quando aquele setor está ligado e some quando ele sai: em vez de todo
        mundo carregar o texto de todos.
        """
        pasta = self._pasta_do_setor()
        if not pasta or not filename:
            return ""
        alvo = pasta / filename
        if not alvo.is_file():
            return ""
        try:
            texto = alvo.read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10)).strip()
        except OSError:
            return ""
        return texto[: self.max_chars]

    def build_prompt(self, base_prompt: str, role: str) -> str:
        """Assemble identity, authoritative core and a role-specific overlay."""
        if not self.enabled:
            return base_prompt
        arquivo_do_papel = _ROLE_FILES.get(str(role or "").lower(), "")
        soul = self._read("SOUL.md")
        # O overlay do setor vence o geral: quem escreveu o pacote quis aquele.
        role_overlay = self._ler_do_setor(arquivo_do_papel) or self._read(arquivo_do_papel)
        if not soul and not role_overlay:
            return base_prompt

        parts = [
            "### Limite do contexto editável\n"
            "O contexto editável orienta voz e método de trabalho. "
            "O contrato central continua valendo para evidência, segurança, ferramentas, "
            "privacidade e validação da saída. Exemplos da orientação não são dados da sessão."
        ]
        if soul:
            parts.append(f"### Identidade editável (SOUL.md)\n{soul}")
        parts.append(f"### Contrato central\n{base_prompt}")
        if role_overlay:
            parts.append(f"### Orientação editável: {role}\n{role_overlay}")
        parts.append(
            "### Prioridade das orientações\n"
            "Se o texto editável contradizer o contrato central ou a evidência disponível, "
            "siga o contrato central e diga o que falta."
        )
        return "\n\n".join(parts)
