"""O que o motor pergunta ao setor ativo.

Tres leituras que o laco do turno faz do pacote, juntas porque sao a mesma
coisa: o motor nao decide, ele pergunta. Sem setor as tres devolvem vazio, e
vazio e resposta valida: o generalista nao tem analise de dominio para
recuperar, nem ferramenta que mede causa, nem ferramenta que entrega
documento por conta propria.

Moravam no `orchestrator.py`. Sairam porque nao sao do laco: sao do contrato
de setor, e porque o arquivo bateu no teto de novo.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def entregas() -> dict:
    """Ferramentas cuja saida e a entrega, no setor ativo.

    Vazio e resposta valida: sem setor, nenhuma ferramenta entrega por conta
    propria e tudo passa pelo modelo, como qualquer resultado.
    """
    try:
        from .registry import get_active_domain

        return dict(getattr(get_active_domain(), "entregas", {}) or {})
    except Exception:
        logger.debug("Entregas do setor nao foram lidas", exc_info=True)
        return {}


def ferramenta_de_causa() -> str:
    """A ferramenta que mede causa no setor ativo, ou vazio."""
    try:
        from .registry import get_active_domain

        return str(getattr(get_active_domain(), "ferramenta_de_causa", "") or "")
    except Exception:
        logger.debug("Ferramenta de causa do setor nao foi lida", exc_info=True)
        return ""


def tabelas_no_sandbox() -> tuple:
    """Tabelas que o setor quer como DataFrame dentro do `executar_python`.

    Vazio no generalista, de proposito: sem pacote, a execucao de script nao
    tem por que carregar tabela nenhuma. Eram `feedbacks`, `tickets` e
    `technicians` cravados no motor: CX dentro da ferramenta mais generica
    que existe."""
    try:
        from .registry import get_active_domain

        return tuple(getattr(get_active_domain(), "tabelas_no_sandbox", ()) or ())
    except Exception:
        logger.debug("Tabelas do setor para o sandbox nao foram lidas", exc_info=True)
        return ()


def dimensoes() -> dict:
    """Recortes do setor ativo: nome -> valores aceitos.

    Vazio sem setor. O motor nao sabe que existe "regiao", e muito menos que
    ela tem cinco valores com estes nomes.
    """
    try:
        from .registry import get_active_domain

        return dict(getattr(get_active_domain(), "dimensoes", {}) or {})
    except Exception:
        logger.debug("Dimensoes do setor nao foram lidas", exc_info=True)
        return {}


def guardas() -> tuple:
    """Guardas do setor ativo: o que entra no plano mesmo sem o planejador
    ter pedido. Vazio sem setor: o motor nao inventa gatilho."""
    try:
        from .registry import get_active_domain

        return tuple(getattr(get_active_domain(), "guardas", ()) or ())
    except Exception:
        logger.debug("Guardas do setor nao foram lidas", exc_info=True)
        return ()


def dicas_de_grafico() -> tuple:
    """Que analise sustenta um grafico sobre cada assunto, no setor ativo.

    Vem do pacote, e vazio e resposta valida: sem setor nao ha analise para
    recuperar. A tabela morava no orquestrador e valia para todo mundo: o
    generalista pedia grafico de "sentimento" e o motor injetava
    `analyze_sentiment`, que nem esta na mesa dele.
    """
    try:
        from .registry import get_active_domain

        return tuple(getattr(get_active_domain(), "dicas_de_grafico", ()) or ())
    except Exception:
        logger.debug("Dicas de grafico do setor nao foram lidas", exc_info=True)
        return ()


def fontes_de_dados() -> tuple:
    """As fontes que o setor ativo oferece quando o pedido de material nao diz
    de que dado. Vazio sem setor: o motor usa as neutras."""
    try:
        from .registry import get_active_domain

        return tuple(getattr(get_active_domain(), "fontes_de_dados", ()) or ())
    except Exception:
        logger.debug("Fontes de dados do setor nao foram lidas", exc_info=True)
        return ()


def publicos() -> tuple:
    """Quem costuma usar a entrega no setor ativo. Vazio sem setor."""
    try:
        from .registry import get_active_domain

        return tuple(getattr(get_active_domain(), "publicos", ()) or ())
    except Exception:
        logger.debug("Publicos do setor nao foram lidos", exc_info=True)
        return ()


def termos_de_dado() -> frozenset:
    """Palavras que apontam um dado do setor ativo: nomes e rotulos das
    metricas e os termos das fontes. Vazio sem setor."""
    try:
        from .registry import get_active_domain

        pack = get_active_domain()
    except Exception:
        return frozenset()
    termos = set()
    for nome, meta in (getattr(pack, "metric_meta", {}) or {}).items():
        termos.add(str(nome).split("_")[0].lower())
        termos.add(str((meta or {}).get("label", "")).lower())
    for fonte in getattr(pack, "fontes_de_dados", ()) or ():
        termos.update(fonte.get("termos") or ())
    return frozenset(t for t in termos if len(t) >= 3)


def atalhos() -> tuple:
    """Comandos curtos que o setor ativo oferece nos canais. Vazio sem setor."""
    try:
        from .registry import get_active_domain

        return tuple(getattr(get_active_domain(), "atalhos", ()) or ())
    except Exception:
        logger.debug("Atalhos do setor nao foram lidos", exc_info=True)
        return ()


def cores_de_rotulo() -> dict:
    """Categorias do setor com cor fixa no grafico (positivo, neutro, negativo)."""
    try:
        from .registry import get_active_domain

        return dict(getattr(get_active_domain(), "cores_de_rotulo", {}) or {})
    except Exception:
        return {}


def titulos_de_secao() -> dict:
    """Titulo de cada secao do painel cruzado, por ferramenta. Vazio sem setor."""
    try:
        from .registry import get_active_domain

        return dict(getattr(get_active_domain(), "titulos_de_secao", {}) or {})
    except Exception:
        return {}


def titulos_de_passo() -> dict:
    """Titulo do passo na tela, por ferramenta do setor. Vazio sem setor."""
    try:
        from .registry import get_active_domain

        return dict(getattr(get_active_domain(), "titulos_de_passo", {}) or {})
    except Exception:
        return {}


def rotulos_de_coluna() -> dict:
    """Rotulo legivel de cada coluna dos resultados do setor. Vazio sem setor."""
    try:
        from .registry import get_active_domain

        return dict(getattr(get_active_domain(), "rotulos_de_coluna", {}) or {})
    except Exception:
        return {}


def exemplos_de_pedido() -> tuple:
    """Exemplos de pedido do setor ativo para a ajuda dos canais. Vazio sem setor."""
    try:
        from .registry import get_active_domain

        return tuple(getattr(get_active_domain(), "exemplos_de_pedido", ()) or ())
    except Exception:
        logger.debug("Exemplos do setor nao foram lidos", exc_info=True)
        return ()


def _modulo_de_analises():
    """O modulo de analises do pacote ativo, ou None."""
    import importlib

    try:
        from . import get_active_domain

        setor = (get_active_domain().name or "").strip()
    except Exception:
        return None
    if not setor:
        return None
    try:
        return importlib.import_module(f"sentury.domains.setores.{setor}.analises")
    except ModuleNotFoundError:
        # Pacote sem analises e caso normal: o `coder` nao tem nenhuma.
        return None
    except Exception as exc:  # pragma: no cover - pacote quebrado nao derruba o turno
        logger.warning("Pacote '%s' tem analises que nao importam: %s", setor, exc)
        return None


def colunas_de_grafico() -> dict:
    """Que par de colunas plotar para a saida de cada analise do setor ativo.

    A tabela morava em `artifacts/visualization.py` com quinze ferramentas de
    CX cravadas. Vazio e resposta valida: sem setor nao ha analise de dominio
    para plotar, e o motor cai na deteccao pelos proprios dados.
    """
    try:
        from .registry import get_active_domain

        return dict(getattr(get_active_domain(), "colunas_de_grafico", {}) or {})
    except Exception:
        logger.debug("Colunas de grafico do setor nao foram lidas", exc_info=True)
        return {}


def formas_de_grafico() -> dict:
    """A forma que o setor prefere para a saida de cada analise (linha, rosca,
    barra_horizontal). Vazio e resposta valida: sem setor, a forma sai dos
    proprios dados (eixo de tempo, porcentagens, rotulos longos)."""
    try:
        from .registry import get_active_domain

        return dict(getattr(get_active_domain(), "formas_de_grafico", {}) or {})
    except Exception:
        logger.debug("Formas de grafico do setor nao foram lidas", exc_info=True)
        return {}


def titulos_de_painel() -> dict:
    """Titulo do painel que cada analise do setor gera.

    Morava em `renderers/html_dashboard.py` com dez analises de CX cravadas.
    Vazio e resposta valida: sem setor o motor titula pelo nome da ferramenta.
    """
    try:
        from .registry import get_active_domain

        return dict(getattr(get_active_domain(), "titulos_de_painel", {}) or {})
    except Exception:
        logger.debug("Titulos de painel do setor nao foram lidos", exc_info=True)
        return {}


def gerar_dataset(**kwargs):
    """O dataset de demonstracao do setor ativo, ou None.

    Cada pacote fornece seus próprios dados; o motor não carrega dados de outro
    setor quando ele não está ativo.
    """
    import importlib

    try:
        from . import get_active_domain

        setor = (get_active_domain().name or "").strip()
    except Exception:
        return None
    if not setor:
        return None
    try:
        modulo = importlib.import_module(f"sentury.domains.setores.{setor}.dados")
    except ModuleNotFoundError:
        return None
    except Exception as exc:  # pragma: no cover
        logger.warning("Pacote '%s' tem dados que nao importam: %s", setor, exc)
        return None
    gerar = getattr(modulo, "gerar", None)
    if gerar is None:
        return None
    try:
        return gerar(**kwargs)
    except Exception as exc:
        logger.warning("Pacote '%s' falhou ao gerar o dataset: %s", setor, exc)
        return None


def analise_de_base() -> str:
    """A analise que da chao antes de opinar, no setor ativo, ou vazio.

    O conselho cravava `analyze_nps` no orquestrador: com o generalista ele
    chamava uma ferramenta que nao existe, o gate recusava e a volta ia
    embora. Vazio e resposta valida: sem base declarada, quem planeja e o
    modelo.
    """
    try:
        from .registry import get_active_domain

        return str(getattr(get_active_domain(), "analise_de_base", "") or "")
    except Exception:
        return ""


def metricas_vigiaveis() -> dict:
    """Metricas que o setor ativo sabe medir para alerta por limiar.

    Vazio e resposta valida: o generalista nao tem metrica de dominio, e
    `/alerta` diz isso em vez de oferecer tres que nao existem.
    """
    modulo = _modulo_de_alertas()
    if modulo is None:
        return {}
    try:
        return dict(getattr(modulo, "METRICAS", {}) or {})
    except Exception:
        return {}


async def medir_para_alerta(store, metric: str, rompeu) -> list:
    """Quanto deu, no recorte do setor. O motor decide o que e rompimento."""
    modulo = _modulo_de_alertas()
    if modulo is None:
        return []
    try:
        return list(await modulo.medir(store, metric, rompeu))
    except Exception as exc:
        logger.warning("Setor falhou ao medir '%s' para alerta: %s", metric, exc)
        return []


def _modulo_de_alertas():
    return _submodulo_de_analises("alertas")


def _submodulo_de_analises(nome: str):
    modulo = _modulo_de_analises()
    if modulo is None:
        return None
    try:
        import importlib

        return importlib.import_module(f"{modulo.__name__}.{nome}")
    except ModuleNotFoundError:
        return None
    except Exception:
        return None


def _modulo_do_setor(nome: str):
    """Um modulo do pacote ativo (`setores/<setor>/<nome>.py`), ou None."""
    import importlib

    try:
        from . import get_active_domain

        setor = (get_active_domain().name or "").strip()
    except Exception:
        return None
    if not setor:
        return None
    try:
        return importlib.import_module(f"sentury.domains.setores.{setor}.{nome}")
    except ModuleNotFoundError:
        return None
    except Exception as exc:  # pragma: no cover - pacote quebrado nao derruba a ligacao
        logger.warning("Pacote '%s' tem '%s' que nao importa: %s", setor, nome, exc)
        return None


def ferramentas_da_voz() -> list:
    """As consultas que o setor ativo oferece na ligacao. Vazio sem setor."""
    modulo = _modulo_do_setor("voz")
    try:
        return [dict(f) for f in getattr(modulo, "FERRAMENTAS", ()) or ()] if modulo else []
    except Exception:
        return []


async def executar_na_voz(nome: str, store, args: dict):
    """A frase falada de uma consulta do setor, ou None."""
    modulo = _modulo_do_setor("voz")
    if modulo is None:
        return None
    return await modulo.executar(nome, store, args)


async def executar_analise(store, tool: str, arguments: dict):
    """Roda uma análise do setor ativo. Quem sabe os argumentos é o pacote."""
    modulo = _submodulo_de_analises("despacho")
    if modulo is None:
        raise ValueError(f"ferramenta desconhecida: {tool}")
    return await modulo.executar(store, tool, arguments)


def insight_proativo(tool: str, result: dict):
    """Uma observacao que o setor acha notavel no resultado, ou None. Sem
    setor nao ha: o generalista nao sabe o que e notavel num NPS."""
    modulo = _submodulo_de_analises("insights")
    if modulo is None:
        return None
    try:
        return modulo.derivar(tool, result)
    except Exception as exc:
        logger.warning("Setor falhou ao derivar a observacao proativa: %s", exc)
        return None


class _AnalisesDoSetorAtivo:
    """Resolve análises do setor ativo sem criar dependência no núcleo.

    Sem pacote ou análise publicada, o acesso falha como ferramenta
    desconhecida, sem impedir a inicialização do motor.
    """

    def __getattr__(self, nome: str):
        modulo = _modulo_de_analises()
        if modulo is None:
            raise ValueError(f"ferramenta desconhecida: {nome}")
        try:
            return getattr(modulo, nome)
        except AttributeError:
            raise ValueError(f"ferramenta desconhecida: {nome}") from None


analises = _AnalisesDoSetorAtivo()


__all__ = [
    "analise_de_base", "analises", "atalhos", "colunas_de_grafico", "cores_de_rotulo", "dicas_de_grafico", "dimensoes",
    "entregas", "executar_analise", "executar_na_voz", "exemplos_de_pedido", "ferramenta_de_causa", "ferramentas_da_voz",
    "fontes_de_dados", "formas_de_grafico", "guardas", "insight_proativo",
    "medir_para_alerta", "metricas_vigiaveis", "publicos", "rotulos_de_coluna", "termos_de_dado",
    "titulos_de_painel", "titulos_de_passo", "titulos_de_secao",
]
