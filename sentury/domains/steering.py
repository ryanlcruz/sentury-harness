"""Injeta playbooks do setor conforme regras de inclusão.

Ao contrário de uma skill buscada por relevância, o playbook pode valer sempre,
para determinados arquivos ou apenas por pedido. Os limites por playbook e no
conjunto impedem que o contexto obrigatório ocupe todo o prompt.
"""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PASTA = "steering"

# Um playbook que não cabe em duas telas não é playbook, é documentação: e
# documentação o agente busca, não carrega.
MAX_CARACTERES = 4000

# O conjunto do que entra em TODO turno. Estourar isto é o pacote comendo a
# janela de contexto de quem o instalou.
MAX_NO_CONJUNTO = 12000

QUANDO_VALIDO = ("sempre", "arquivos", "manual")


class Playbook:
    """Um arquivo de `steering/`, com a regra que decide se ele entra."""

    def __init__(self, nome: str, titulo: str, quando: str,
                 arquivos: List[str], corpo: str, caminho: Path):
        self.nome = nome
        self.titulo = titulo
        self.quando = quando
        self.arquivos = arquivos
        self.corpo = corpo
        self.caminho = caminho

    def casa_com(self, tocados: List[str]) -> bool:
        """Se algum arquivo do turno bate com os padrões declarados."""
        if not self.arquivos:
            return False
        for alvo in tocados:
            nome = Path(str(alvo)).as_posix()
            for padrao in self.arquivos:
                if fnmatch.fnmatch(nome, padrao) or fnmatch.fnmatch(Path(nome).name, padrao):
                    return True
        return False

    def como_dict(self) -> Dict[str, Any]:
        return {
            "nome": self.nome, "titulo": self.titulo, "quando": self.quando,
            "arquivos": list(self.arquivos), "caracteres": len(self.corpo),
        }


def _um(caminho: Path) -> Optional[Playbook]:
    from ..skills.skill_loader import parse_frontmatter

    try:
        bruto = caminho.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Steering '%s' nao foi lido: %s", caminho, exc)
        return None

    cabecalho, corpo = parse_frontmatter(bruto)
    corpo = (corpo or "").strip()
    if not corpo:
        return None

    quando = str(cabecalho.get("quando") or "manual").strip().lower()
    if quando not in QUANDO_VALIDO:
        # Regra que ninguém entende vira a mais cara por engano. `manual` é o
        # padrão seguro: não entra sozinho.
        logger.warning(
            "Steering '%s': quando='%s' nao e um dos %s; tratando como manual.",
            caminho.name, quando, ", ".join(QUANDO_VALIDO),
        )
        quando = "manual"

    arquivos = cabecalho.get("arquivos") or cabecalho.get("fileMatch") or []
    if isinstance(arquivos, str):
        arquivos = [arquivos]
    arquivos = [str(x).strip() for x in arquivos if str(x).strip()]
    if quando == "arquivos" and not arquivos:
        logger.warning(
            "Steering '%s': quando='arquivos' sem padrao declarado; nunca vai entrar.",
            caminho.name,
        )

    if len(corpo) > MAX_CARACTERES:
        corpo = corpo[:MAX_CARACTERES].rstrip() + "\n\n[...cortado: playbook longo demais]"

    return Playbook(
        nome=caminho.stem,
        titulo=str(cabecalho.get("titulo") or cabecalho.get("title") or caminho.stem),
        quando=quando,
        arquivos=arquivos,
        corpo=corpo,
        caminho=caminho,
    )


def ler(pasta_do_setor: Path) -> List[Playbook]:
    """Todos os playbooks de um pacote, em ordem estável.

    Ordem alfabética de propósito: o pacote decide a ordem pelo nome do
    arquivo, e não pela ordem que o sistema de arquivos devolver: que muda
    entre máquinas e faria o mesmo pacote gerar prompts diferentes.
    """
    alvo = Path(pasta_do_setor) / PASTA
    if not alvo.is_dir():
        return []
    achados = []
    for arquivo in sorted(alvo.glob("*.md")):
        play = _um(arquivo)
        if play is not None:
            achados.append(play)
    return achados


def do_setor(nome: str, pasta: Optional[str] = None) -> List[Playbook]:
    """Os playbooks do setor ativo."""
    from .carregador import pasta_dos_pacotes

    base = Path(pasta).expanduser() if pasta else pasta_dos_pacotes()
    return ler(base / nome)


def aplicaveis(
    playbooks: List[Playbook],
    *,
    arquivos_do_turno: Optional[List[str]] = None,
    pedidos: Optional[List[str]] = None,
) -> List[Playbook]:
    """Quais entram neste turno. `sempre` primeiro, `manual` só se pedido."""
    tocados = [str(x) for x in (arquivos_do_turno or [])]
    querem = {str(x).strip().lower() for x in (pedidos or [])}
    escolhidos = []
    for play in playbooks:
        if play.quando == "sempre":
            escolhidos.append(play)
        elif play.quando == "arquivos" and play.casa_com(tocados):
            escolhidos.append(play)
        elif play.nome.lower() in querem or play.titulo.lower() in querem:
            escolhidos.append(play)
    return escolhidos


def como_texto(playbooks: List[Playbook]) -> str:
    """O bloco para o prompt. Vazio quando não há nada a dizer.

    Corta no conjunto, não só por playbook: dez playbooks dentro do limite
    individual somam trinta mil caracteres, e o que sai da janela para caberem
    é a conversa.
    """
    if not playbooks:
        return ""
    partes, gasto = [], 0
    for play in playbooks:
        trecho = f"## {play.titulo}\n{play.corpo}"
        if gasto + len(trecho) > MAX_NO_CONJUNTO:
            logger.warning(
                "Steering: '%s' ficou de fora, o conjunto passou de %d caracteres.",
                play.nome, MAX_NO_CONJUNTO,
            )
            break
        partes.append(trecho)
        gasto += len(trecho)
    if not partes:
        return ""
    return "COMO SE TRABALHA NESTE SETOR:\n\n" + "\n\n".join(partes)


def para_o_turno(
    nome_do_setor: str,
    *,
    arquivos_do_turno: Optional[List[str]] = None,
    pedidos: Optional[List[str]] = None,
    pasta: Optional[str] = None,
) -> str:
    """Do nome do setor ao texto pronto. É o que o orquestrador chama."""
    if not nome_do_setor:
        return ""
    try:
        todos = do_setor(nome_do_setor, pasta)
    except Exception:
        # Pacote quebrado não pode derrubar o turno: o setor some do prompt e o
        # agente continua sendo o generalista.
        logger.warning("Steering do setor '%s' falhou.", nome_do_setor, exc_info=True)
        return ""
    return como_texto(aplicaveis(todos, arquivos_do_turno=arquivos_do_turno, pedidos=pedidos))


def _arquivos_que_o_turno_tocou(state: Any) -> List[str]:
    """Os caminhos que já apareceram neste turno.

    A regra `quando: arquivos` precisa saber no que se está mexendo, e o turno
    sabe disso de duas fontes: a pasta que o usuário abriu no composer e o que
    as ferramentas já leram ou escreveram. Nenhuma das duas é obrigatória: sem
    elas, só os playbooks `sempre` entram, que é o comportamento certo.
    """
    achados: List[str] = []
    pasta = getattr(state, "pasta_ativa", "") or getattr(state, "working_folder", "")
    if pasta:
        achados.append(str(pasta))
    for passo in (getattr(state, "trace", None) or [])[-40:]:
        alvo = None
        if isinstance(passo, dict):
            alvo = passo.get("caminho") or (passo.get("arguments") or {}).get("caminho")
        if alvo:
            achados.append(str(alvo))
    return achados


def do_turno(state: Any) -> Optional[str]:
    """O bloco de steering deste turno, ou `None`.

    Devolve `None` e não string vazia porque quem chama junta os pedaços de
    contexto filtrando os vazios: e uma string vazia viraria uma linha em
    branco no meio do prompt.
    """
    try:
        from .escolha import GENERALISTA
        from .registry import get_active_domain

        nome = getattr(get_active_domain(), "name", "")
        if not nome or nome == GENERALISTA:
            return None   # sem setor não há playbook de setor
        texto = para_o_turno(nome, arquivos_do_turno=_arquivos_que_o_turno_tocou(state))
        return texto or None
    except Exception:
        logger.debug("Steering do turno nao foi montado", exc_info=True)
        return None


__all__ = [
    "MAX_CARACTERES", "MAX_NO_CONJUNTO", "PASTA", "Playbook", "aplicaveis",
    "como_texto", "do_setor", "do_turno", "ler", "para_o_turno",
]
