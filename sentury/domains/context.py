"""DomainContext: o setor ativo por requisição/sessão (não estado global).

Hoje single-tenant: `default_context()` devolve o CX default. A resolução
dinâmica (request → tenant → context) e o isolamento por tenant entram em B2;
a interface já existe agora pra não mexer em assinatura no harness inteiro depois.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Optional

from .pack import DomainPack
from .registry import get_active_domain


@dataclass(frozen=True)
class TenantBinding:
    # Onde/como os dados DESTE cliente vivem (tabela/API/provider). Fica FORA do
    # DomainPack pra não duplicar o setor por cliente nem vazar credencial nele.
    tenant_id: str = "default"
    domain: str = "cx"
    source_mappings: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DomainContext:
    tenant_id: str
    domain_pack: DomainPack
    binding: TenantBinding
    permissions: Optional[FrozenSet[str]] = None


def default_context() -> DomainContext:
    """Contexto single-tenant do setor ativo (SENTURY_DOMAIN)."""
    pack = get_active_domain()
    return DomainContext(
        tenant_id="default",
        domain_pack=pack,
        binding=TenantBinding(tenant_id="default", domain=pack.name),
    )
