"""Clientes de serviços externos usados pelos renderers: hoje só o
QuickChart.io (gráfico-como-serviço). Segue a mesma filosofia do resto do
projeto: quem chama decide o fallback, este módulo só levanta exceção."""
from . import quickchart

__all__ = ["quickchart"]
