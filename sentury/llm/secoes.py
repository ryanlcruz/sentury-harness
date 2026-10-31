"""Monta o prompt em seções ordenadas e associadas às capacidades ativas.

Orientações de ferramenta só entram quando ela está disponível. Seus esquemas
já descrevem parâmetros; repetir isso em prosa gastaria contexto e poderia
contradizer o contrato estruturado.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Union

logger = logging.getLogger(__name__)

# A ordem é explícita e esparsa, para caber coisa no meio sem renumerar tudo.
ORDENS: Dict[str, int] = {
    "IDENTIDADE": -1000,
    "PERSONA": 0,
    "POLITICA": 500,
    "COMO_AGIR": 800,
    "FERRAMENTAS": 1000,
    "SETOR": 2000,
    "EVIDENCIA": 3000,
}

TextoDaSecao = Union[str, Callable[[], str]]


@dataclass(frozen=True)
class Secao:
    """Um pedaço do prompt, com nome próprio e lugar na ordem."""

    nome: str
    ordem: int
    texto: TextoDaSecao

    def render(self) -> str:
        """Resolve o texto. Seção que falha não derruba o prompt inteiro."""
        if callable(self.texto):
            try:
                return str(self.texto() or "").strip()
            except Exception:
                logger.warning("Secao '%s' falhou ao render; seguindo sem ela.", self.nome)
                return ""
        return str(self.texto or "").strip()


def ordem_de(rotulo: str, deslocamento: int = 0) -> int:
    """A ordem de um papel conhecido, com folga para variar dentro dele."""
    return ORDENS.get(rotulo, ORDENS["FERRAMENTAS"]) + deslocamento


def secoes_das_ferramentas(nomes_na_mesa: Iterable[str]) -> List[Secao]:
    """Uma seção por ferramenta presente, e nenhuma pelas ausentes: a orientação
    viaja com a ferramenta."""
    from ..tools.registry import TOOL_REGISTRY

    achadas: List[Secao] = []
    for i, nome in enumerate(sorted(set(nomes_na_mesa))):
        entrada = TOOL_REGISTRY.get(nome) or {}
        orientacao = str(entrada.get("orientacao") or "").strip()
        if not orientacao:
            continue
        if entrada.get("mostra_shell"):
            # O plano em texto nao le a descricao do esquema nativo, onde a
            # dica do shell tambem vai.
            from ..tools.shell import dica_do_shell

            orientacao = f"{orientacao} {dica_do_shell()}".strip()
        achadas.append(Secao(
            nome=f"tool:{nome}",
            # `i` só desempata: o que importa é o bloco de ferramentas ficar
            # junto, na ordem alfabética que o `sorted` já deu.
            ordem=ordem_de("FERRAMENTAS", i),
            texto=f"- `{nome}`: {orientacao}",
        ))
    return achadas


def montar(secoes: Iterable[Secao]) -> str:
    """As seções viram um texto só, na ordem, sem as vazias.

    Nome repetido é erro de programação, não de conteúdo: duas seções com o
    mesmo nome significam que alguém registrou duas vezes, e a segunda venceria
    em silêncio.
    """
    vistas: Dict[str, Secao] = {}
    for secao in secoes:
        if secao.nome in vistas:
            raise ValueError(f"secao duplicada: '{secao.nome}'")
        vistas[secao.nome] = secao

    partes = [
        texto for texto in (
            s.render() for s in sorted(vistas.values(), key=lambda s: (s.ordem, s.nome))
        ) if texto
    ]
    return "\n\n".join(partes)


def bloco_de_ferramentas(nomes_na_mesa: Iterable[str], titulo: str = "") -> str:
    """As orientações das ferramentas presentes, prontas para entrar num prompt."""
    linhas = [s.render() for s in secoes_das_ferramentas(nomes_na_mesa)]
    linhas = [linha for linha in linhas if linha]
    if not linhas:
        return ""
    cabeca = (titulo or "QUANDO USAR CADA FERRAMENTA").strip()
    return cabeca + "\n\n" + "\n".join(linhas)

def prompt_do_planejador(base: str, com_ferramentas: bool = True) -> str:
    """O prompt base, as orientacoes das ferramentas na mesa e o que o setor soma.

    Aditivo: o que nao esta na mesa nunca entra, entao nada precisa ser removido.
    """
    try:
        from ..domains.registry import get_active_domain

        do_setor = str(getattr(get_active_domain(), "planner", "") or "").strip()
    except Exception:
        logger.debug("Planner do setor nao foi lido", exc_info=True)
        do_setor = ""

    try:
        from .tool_schemas import build_tool_schemas

        # Sem `com_ferramentas` (passo unico) a orientacao vai na descricao de
        # cada ferramenta oferecida. Com elas, so o nucleo entra aqui, que e
        # fixo; as oferecidas no turno vao em `ferramentas_alem_do_nucleo`.
        na_mesa = [e["function"]["name"] for e in build_tool_schemas(set()) if "function" in e] if com_ferramentas else []
        das_ferramentas = bloco_de_ferramentas(na_mesa)
    except Exception:
        logger.debug("Orientacoes de ferramenta nao foram montadas", exc_info=True)
        das_ferramentas = ""

    partes = [base.rstrip(), das_ferramentas, do_setor]
    return "\n\n".join(p for p in partes if p) + "\n"


def ferramentas_alem_do_nucleo(fallback: Iterable[str] = ()) -> str:
    """Orientacao das ferramentas oferecidas neste turno que nao sao do nucleo.

    Muda com o pedido, entao vai na parte variavel do prompt. As outras seguem
    no mapa de capacidades e podem ser chamadas pelo nome."""
    try:
        from ..config import settings
        from ..harness.descoberta import nomes_da_chamada
        from ..tools.registry import do_nucleo
        from .tool_schemas import build_tool_schemas

        nomes = (nomes_da_chamada(set(fallback or ()))
                 if getattr(settings, "SENTURY_PROGRESSIVE_CAPABILITIES", True) else None)
        nucleo = do_nucleo()
        extras = [e["function"]["name"] for e in build_tool_schemas(nomes)
                  if "function" in e and e["function"]["name"] not in nucleo]
        bloco = bloco_de_ferramentas(extras, titulo="FERRAMENTAS OFERECIDAS NESTE PEDIDO")
    except Exception:
        logger.debug("Orientacoes do turno nao foram montadas", exc_info=True)
        bloco = ""
    return "\n\n" + bloco if bloco else ""
