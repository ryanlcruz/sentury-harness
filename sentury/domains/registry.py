"""Registra setores opcionais e seleciona o pacote ativo.

O motor continua generalista sem pacote; cada especialidade é carregada da
sua própria pasta.
"""
import logging
from typing import Dict

from .pack import DomainPack

logger = logging.getLogger(__name__)

# O registro nasce vazio para não incluir especialidades no motor generalista.
DOMAIN_REGISTRY: Dict[str, DomainPack] = {}


def _carregar_pacotes_da_pasta() -> None:
    """Setores declarados em `sentury/dominios/*/pack.yaml`.

    O que vem da pasta SOBREPÕE o embutido de mesmo nome: quem editou o YAML
    quis aquilo, e ser ignorado em silêncio seria pior do que um erro.
    """
    try:
        from .carregador import descobrir

        for pack in descobrir():
            DOMAIN_REGISTRY[pack.name] = pack
            logger.info("Setor '%s' carregado da pasta.", pack.name)
    except Exception as exc:
        logger.warning("Nao consegui ler os setores da pasta: %s", exc)


def _carregar_codigo_do_ativo() -> None:
    """Ferramentas próprias do setor em uso. Só do ativo: código de pacote roda
    no mesmo processo, e carregar o de todos daria superfície que ninguém pediu."""
    try:
        from ..config import settings
        from .carregador import carregar_codigo_do_setor

        nome = getattr(settings, "SENTURY_DOMAIN", "cx") or "cx"
        publicadas = carregar_codigo_do_setor(nome)
        if publicadas:
            logger.info("Setor '%s' publicou %d ferramenta(s).", nome, len(publicadas))
    except Exception as exc:
        logger.warning("Nao consegui carregar o codigo do setor ativo: %s", exc)


_carregar_pacotes_da_pasta()
_carregar_codigo_do_ativo()


def register_domain(pack: DomainPack) -> None:
    """Pluga um DomainPack no registro."""
    DOMAIN_REGISTRY[pack.name] = pack


def get_active_domain() -> DomainPack:
    """Setor ativo. A escolha da interface manda; sem ela, vale o `.env`.

    Import tardio de config evita ciclo.
    """
    from ..config import settings
    from .escolha import GENERALISTA, PACK_GENERALISTA, ler
    from .escopo import setor_do_contexto

    # Um teste/job pode precisar de um setor deterministico sem alterar a
    # escolha persistente da instalacao. ContextVar tambem impede que dois
    # tasks concorrentes troquem o setor um do outro.
    escolhido = setor_do_contexto()
    if escolhido is None:
        escolhido = ler()
    # A queda e o GENERALISTA, nao um setor. Cair em "cx" fazia uma instalacao
    # de vendas se apresentar como analista de experiencia do cliente: e,
    # quando o pacote do cx nao existisse, estourar `KeyError` e derrubar o
    # Sentury inteiro por causa de uma pasta renomeada.
    nome = escolhido if escolhido is not None else (
        getattr(settings, "SENTURY_DOMAIN", "") or "")

    if nome in ("", GENERALISTA):
        return PACK_GENERALISTA
    pack = DOMAIN_REGISTRY.get(nome)
    if pack is None:
        logger.warning(
            "Setor %r nao registrado (ha %s); seguindo como generalista.",
            nome, sorted(DOMAIN_REGISTRY) or "nenhum",
        )
        return PACK_GENERALISTA
    return pack
