"""Setores (domínios plugáveis): DomainPack = setor, DomainRegistry = mecanismo."""
from .context import DomainContext, TenantBinding, default_context
from .pack import DomainPack
from .registry import DOMAIN_REGISTRY, get_active_domain, register_domain

__all__ = [
    "DomainPack", "DOMAIN_REGISTRY", "get_active_domain", "register_domain",
    "DomainContext", "TenantBinding", "default_context",
]
