"""A fonte de dados que o motor enxerga.

O motor não tem tabela própria. Quem traz tabela é o pacote de setor (o de CX
tem a base em memória dele em `domains/setores/cx/dados/`), ou um backend
registrado com `register_data_backend`. Sem nenhum dos dois, a fonte é
`SemDados`, que responde vazio em vez de fingir.

O contrato oferece leitura SQL e a fila de tarefas. Consultas específicas de
um setor ficam no pacote dele, para não obrigar outras fontes a imitá-lo.
"""

import logging
from typing import Any, Dict, List, Optional, Protocol, Sequence, Union, runtime_checkable

import pandas as pd


logger = logging.getLogger(__name__)

FilterValue = Optional[Union[str, Sequence[str]]]


@runtime_checkable
class DataSource(Protocol):
    """O que uma fonte precisa ter para o motor usar. Consulta de setor é extra."""

    def get_sqlite_conn(self) -> Any: ...

    async def criar_acao(self, dados: Dict[str, Any]) -> Dict[str, Any]: ...

    async def listar_acoes(self, status: FilterValue = None, **filtros: Any) -> List[Dict[str, Any]]: ...

    async def atualizar_acao(self, acao_id: str, campos: Dict[str, Any]) -> Optional[Dict[str, Any]]: ...


# O registro permite usar a fonte da instalação sem impor um backend ao núcleo.
DATA_BACKENDS: Dict[str, Any] = {}


def register_data_backend(nome: str, fabrica) -> None:
    """Registra um adapter de dados. `fabrica(settings) -> DataSource`."""
    DATA_BACKENDS[nome.strip().lower()] = fabrica


def get_store(settings) -> DataSource:
    escolhido = (getattr(settings, "SENTURY_DATA_BACKEND", "") or "").strip().lower()
    if escolhido:
        fabrica = DATA_BACKENDS.get(escolhido)
        if fabrica is None:
            raise ValueError(
                f"SENTURY_DATA_BACKEND='{escolhido}' desconhecido. "
                f"Opções registradas: {', '.join(sorted(DATA_BACKENDS)) or 'nenhuma'}. "
                "Registre a sua com register_data_backend()."
            )
        logger.info("Sentury Data Store: backend '%s' (escolha explícita).", escolhido)
        return fabrica(settings)

    # Sem escolha explícita, não inicia conexão com um serviço externo.
    logger.info(
        "Sentury Data Store: sem backend escolhido — dataset em memoria (seed=%s). "
        "Escolha um em SENTURY_DATA_BACKEND: %s.",
        settings.SENTURY_MOCK_SEED,
        ", ".join(sorted(DATA_BACKENDS)) or "nenhum registrado",
    )
    return _base_do_setor(settings)


# O registro de adapters continua; o que saiu foram os dois que vinham de
# fabrica e nao serviam. Quem precisar de um backend registra o seu aqui.
#
# A base em memoria tambem deixou de morar no motor: ela serve as tabelas do
# SETOR, e o motor nao tem tabela propria. Sem pacote nao ha o que servir, e a
# excecao e a resposta honesta: melhor que um store vazio fingindo ter dado.
class SemDados:
    """A fonte de um agente que nao tem fonte declarada.

    Nao e placeholder: e a resposta honesta. O pacote e quem traz tabela, e um
    generalista sem pacote nao tem nenhuma. Antes disto o motor carregava a
    base de CX para todo mundo, entao "sem dados" nem existia como estado:
    havia sempre feedbacks e tickets de mentira a responder.

    Tudo devolve vazio em vez de levantar: o turno segue e o agente diz que
    nao tem o dado, que e melhor que um erro de infraestrutura na cara de quem
    perguntou.
    """

    # A fila da tela Tasks nao e de setor: e onde o "enviar pro Tasks" do
    # card de plano grava. Ela morava no store de CX, entao virar o padrao para
    # generalista deixou a tela sempre vazia e o botao dando 500. Aqui ela
    # continua em memoria, como sempre foi, e sem campo de setor obrigatorio.
    def __init__(self):
        self._acoes: List[Dict[str, Any]] = []

    async def criar_acao(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        from datetime import datetime, timezone

        registro = {k: v for k, v in (dados or {}).items() if v is not None}
        registro["id"] = registro.get("id") or f"AC-{len(self._acoes) + 1:03d}"
        registro.setdefault("criado_em", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        registro.setdefault("status", "Aberta")
        registro.setdefault("prioridade", "Média")
        self._acoes.append(registro)
        return dict(registro)

    async def listar_acoes(self, status: FilterValue = None, **filtros: Any) -> List[Dict[str, Any]]:
        saida = list(self._acoes)
        for campo, valor in {"status": status, **filtros}.items():
            if valor is None:
                continue
            aceitos = {valor} if isinstance(valor, str) else set(valor)
            saida = [a for a in saida if a.get(campo) in aceitos]
        return [dict(a) for a in saida]

    async def atualizar_acao(self, acao_id: str, campos: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for acao in self._acoes:
            if str(acao.get("id")) == str(acao_id):
                acao.update({k: v for k, v in (campos or {}).items() if v is not None})
                return dict(acao)
        return None

    def __getattr__(self, nome: str):
        if not nome.startswith("get_"):
            raise AttributeError(nome)

        async def vazio(*_a, **_k):
            return pd.DataFrame()

        return vazio

    def get_sqlite_conn(self) -> Any:
        import sqlite3

        return sqlite3.connect(":memory:")


def _base_do_setor(st):
    """A base em memoria do pacote ativo, ou `SemDados` quando nao ha."""
    import importlib

    from ..domains import get_active_domain

    setor = (get_active_domain().name or "").strip()
    try:
        modulo = importlib.import_module(f"sentury.domains.setores.{setor}.dados.store")
    except ModuleNotFoundError:
        logger.info("Setor '%s' nao traz base de dados; seguindo sem fonte.", setor or "(nenhum)")
        return SemDados()
    # Quanto dado gerar e do pacote: o motor so entrega a configuracao.
    abrir = getattr(modulo, "abrir", None)
    return abrir(st) if callable(abrir) else modulo.InMemoryDataStore()


register_data_backend("memory", _base_do_setor)


