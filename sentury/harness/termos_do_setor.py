"""O que a conversa oferece e reconhece, vindo do setor ativo.

O motor não sabe o que é NPS, chamado ou filial: isso é do pacote do setor
(`domains/setores/<setor>/pack.yaml`). Sem setor (generalista), as opções são
neutras (arquivo, dado colado, web) e os termos, só os genéricos.
"""
from __future__ import annotations

from typing import Dict, List

from ..domains.do_setor import fontes_de_dados, publicos

FONTES_NEUTRAS = (
    {"label": "Um arquivo ou pasta", "description": "Planilha, CSV, documento ou código que você indicar"},
    {"label": "Dados que vou colar", "description": "Texto ou tabela direto na conversa"},
    {"label": "Pesquisa na web", "description": "Fontes públicas, com o link de cada uma"},
)
PUBLICOS_NEUTROS = (
    {"label": "Liderança", "description": "Leitura executiva e decisão rápida"},
    {"label": "Quem executa", "description": "Acompanhamento e próximas ações"},
    {"label": "Especialistas", "description": "Detalhe e método"},
)
EXEMPLOS_NEUTROS = "um arquivo, uma planilha ou dados que você colar"

def opcoes_de_fonte() -> List[Dict[str, str]]:
    """As fontes para a pergunta "quais dados este material deve mostrar?"."""
    do_setor = [{"label": f["rotulo"], "description": f.get("descricao", "")} for f in fontes_de_dados()]
    return do_setor or [dict(o) for o in FONTES_NEUTRAS]


def opcoes_de_publico() -> List[Dict[str, str]]:
    do_setor = [{"label": p["rotulo"], "description": p.get("descricao", "")} for p in publicos()]
    return do_setor or [dict(o) for o in PUBLICOS_NEUTROS]


def exemplos_de_fonte() -> str:
    """Exemplos para "me diz de que dado": os do setor, ou os neutros."""
    rotulos = [f["rotulo"] for f in fontes_de_dados() if f.get("ferramenta")]
    return ", ".join(rotulos) if rotulos else EXEMPLOS_NEUTROS


__all__ = ["exemplos_de_fonte", "opcoes_de_fonte", "opcoes_de_publico"]
