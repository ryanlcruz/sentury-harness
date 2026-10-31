"""Pacote de setor que traz código próprio: ferramentas, APIs, integrações.

YAML declara o que o setor **é**; para o que ele **faz** de específico não há
declaração que baste. Uma empresa que já tem uma API interna precisa de código
para falar com ela, e reescrever isso como configuração seria inventar uma
linguagem pior que Python.

O modelo é o de mod de jogo: uma pasta, um ponto de entrada conhecido, e uma
API mínima que o host oferece.

    sentury/domains/setores/
      coder/
        pack.yaml       o que o setor é
        tools.py        o que ele sabe fazer   ← aqui
        skills/         procedimentos prontos

O `tools.py` expõe uma função `registrar(api)`:

    def registrar(api):
        async def status_do_build(argumentos):
            ...
            return {"ok": True, "fila": 3}

        api.ferramenta(
            "status_do_build",
            status_do_build,
            descricao="Estado atual da fila de build.",
            categoria="conhecimento",
        )

Duas coisas que o desenho garante:

- **Carregar é explícito.** Código de terceiro roda no mesmo processo, então
  só entra pacote que está na pasta de setores e só quando o setor é ligado.
- **Um pacote quebrado não derruba o agente.** Ele não carrega, aparece no
  log, e o resto segue.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

ARQUIVO = "tools.py"
CATEGORIAS_VALIDAS = {"conhecimento", "analise", "acao", "execucao", "exportacao", "memoria"}

# Nome → o que executar, por setor. Vazio até alguém carregar.
_FERRAMENTAS: Dict[str, Dict[str, Any]] = {}


class ContextoDoPacote:
    """O que uma ferramenta de pacote recebe alem dos argumentos.

    Ate hoje ela nao recebia nada: `executar(argumentos)` e so. Por isso o
    `coder/tools.py` de exemplo devolve numero falso com um aviso: nao havia
    como consultar coisa nenhuma, e um pacote que nao le dado nao publica
    ferramenta de verdade, publica placeholder.

    Pequeno de proposito, pela mesma razao da `ApiDoPacote`: cada campo aqui
    passa a ter de existir para sempre. Comeca com o que responde "de onde vem
    o dado" e mais nada.
    """

    def __init__(self, setor: str, store: Any = None, session_id: str = ""):
        self.setor = setor
        self.store = store
        self.session_id = session_id

    def sql(self) -> Any:
        """Conexao SQL de leitura da fonte ativa, ou `None`.

        E o caminho curto para o pacote consultar sem precisar conhecer o
        contrato de sete `get_*`: que foi escrito para um dominio so.
        """
        if self.store is None or not hasattr(self.store, "get_sqlite_conn"):
            return None
        try:
            return self.store.get_sqlite_conn()
        except Exception:
            logger.warning("Setor '%s': fonte SQL indisponivel.", self.setor, exc_info=True)
            return None


class ApiDoPacote:
    """O que um pacote pode pedir ao host. Pequena de propósito: cada método
    aqui é superfície que passa a ter de existir para sempre."""

    def __init__(self, setor: str):
        self.setor = setor
        self._registradas: List[str] = []

    def ferramenta(
        self,
        nome: str,
        executar: Callable,
        *,
        descricao: str,
        categoria: str = "conhecimento",
        quando_usar: Optional[List[str]] = None,
    ) -> None:
        """Publica uma ferramenta do setor.

        O nome ganha o prefixo do setor (`coder.status_do_build`): dois pacotes
        podem chamar a mesma coisa de `status`, e sem o prefixo o segundo
        apagaria o primeiro em silêncio.
        """
        curto = str(nome or "").strip()
        if not curto:
            raise ValueError("ferramenta precisa de nome")
        if not callable(executar):
            raise ValueError(f"'{curto}' nao e executavel")
        if categoria not in CATEGORIAS_VALIDAS:
            raise ValueError(
                f"categoria '{categoria}' desconhecida; use uma de {sorted(CATEGORIAS_VALIDAS)}"
            )
        if not str(descricao or "").strip():
            raise ValueError(f"'{curto}' precisa de descricao: e por ela que o modelo escolhe")

        completo = f"{self.setor}.{curto}"
        _FERRAMENTAS[completo] = {
            "setor": self.setor,
            "executar": executar,
            "descricao": descricao.strip(),
            "categoria": categoria,
            "quando_usar": [str(t) for t in (quando_usar or [])],
        }
        self._registradas.append(completo)
        logger.info("Setor '%s' publicou a ferramenta '%s'.", self.setor, completo)

    @property
    def registradas(self) -> List[str]:
        return list(self._registradas)


def carregar(pasta: Path, setor: str) -> List[str]:
    """Roda o `tools.py` do pacote e devolve o que ele publicou.

    Nunca levanta: um pacote quebrado não pode derrubar o agente inteiro.
    """
    arquivo = pasta / ARQUIVO
    if not arquivo.is_file():
        return []

    modulo_nome = f"sentury_setor_{setor}"
    try:
        spec = importlib.util.spec_from_file_location(modulo_nome, arquivo)
        if spec is None or spec.loader is None:
            logger.warning("Nao consegui preparar o codigo do setor '%s'.", setor)
            return []
        modulo = importlib.util.module_from_spec(spec)
        sys.modules[modulo_nome] = modulo
        spec.loader.exec_module(modulo)
    except Exception as exc:
        logger.warning("Codigo do setor '%s' falhou ao carregar: %s", setor, exc)
        return []

    registrar = getattr(modulo, "registrar", None)
    if not callable(registrar):
        logger.warning("'%s/%s' nao expoe `registrar(api)`; nada foi publicado.", setor, ARQUIVO)
        return []

    api = ApiDoPacote(setor)
    try:
        registrar(api)
    except Exception as exc:
        logger.warning("Setor '%s' falhou ao registrar suas ferramentas: %s", setor, exc)
        # O que ele chegou a publicar antes de falhar sai junto: meia
        # ferramenta é pior que nenhuma.
        for nome in api.registradas:
            _FERRAMENTAS.pop(nome, None)
        return []
    return api.registradas


def publicadas(setor: str = "") -> Dict[str, Dict[str, Any]]:
    if not setor:
        return dict(_FERRAMENTAS)
    return {n: d for n, d in _FERRAMENTAS.items() if d["setor"] == setor}


def para_o_registro(setor: str = "") -> Dict[str, Dict[str, Any]]:
    """No formato do `TOOL_REGISTRY`, sem o executável."""
    return {
        nome: {
            "categoria": dados["categoria"],
            "descricao": dados["descricao"],
            "quando_usar": dados["quando_usar"],
            "setor": dados["setor"],
        }
        for nome, dados in publicadas(setor).items()
    }


def _aceita_contexto(funcao: Callable) -> bool:
    """Se a ferramenta declarou um segundo parametro.

    Inspecao em vez de try/except no `TypeError`: um `TypeError` vindo de
    DENTRO da ferramenta seria indistinguivel de assinatura errada, e o pacote
    passaria a ser chamado duas vezes por um erro que e dele.
    """
    import inspect

    try:
        parametros = inspect.signature(funcao).parameters.values()
    except (TypeError, ValueError):
        return False
    posicionais = [
        p for p in parametros
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    if any(p.kind is p.VAR_POSITIONAL for p in parametros):
        return True
    return len(posicionais) >= 2


async def executar(
    nome: str,
    argumentos: Optional[Dict[str, Any]] = None,
    contexto: Optional["ContextoDoPacote"] = None,
) -> Any:
    """Chama uma ferramenta de pacote. Aceita função normal ou async.

    A ferramenta escolhe a assinatura: `f(argumentos)` ou `f(argumentos, ctx)`.
    Quem só precisa dos argumentos não é obrigado a declarar um parâmetro que
    ignora: e os pacotes escritos antes do contexto continuam funcionando.
    """
    import inspect

    dados = _FERRAMENTAS.get(nome)
    if not dados:
        return {"ok": False, "erro": f"ferramenta de setor desconhecida: {nome}"}
    try:
        funcao = dados["executar"]
        quer_contexto = _aceita_contexto(funcao)
        if quer_contexto and contexto is None:
            # Dizer o que falta, em vez de deixar o TypeError cru chegar. Quem
            # escreveu o pacote nao tem como adivinhar que o host chamou sem
            # contexto.
            return {
                "ok": False,
                "erro": (
                    "esta ferramenta pede o contexto do turno e foi chamada sem ele; "
                    "quem chama precisa passar ContextoDoPacote(...)"
                ),
                "ferramenta": nome,
            }
        saida = funcao(argumentos or {}, contexto) if quer_contexto else funcao(argumentos or {})
        return await saida if inspect.isawaitable(saida) else saida
    except Exception as exc:
        # O erro do pacote vira resposta, não exceção: o turno continua e o
        # agente lê o que aconteceu.
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}", "ferramenta": nome}


def esquecer(setor: str = "") -> None:
    """Tira do ar o que um setor publicou. Sem setor, limpa tudo (teste)."""
    for nome in [n for n, d in _FERRAMENTAS.items() if not setor or d["setor"] == setor]:
        _FERRAMENTAS.pop(nome, None)


__all__ = [
    "ContextoDoPacote","ApiDoPacote", "ARQUIVO", "carregar", "esquecer", "executar",
           "para_o_registro", "publicadas"]
