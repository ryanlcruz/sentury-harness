"""Politicas em YAML: o que muda por instalacao, sem exigir release."""
from .loader import carregar, limpar_cache, pasta_de_config

__all__ = ["carregar", "limpar_cache", "pasta_de_config"]
