"""Grava o turno para replay sem interferir na resposta.

O invólucro externo registra também os turnos curtos, que podem sair antes das
fases internas de observabilidade. Falha na gravação não deve derrubar o turno.
"""
from __future__ import annotations

import builtins
import contextvars
import copy
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Ligado pelo `repetir()`: sem isto, cada rodada de mutação grava cópias de si
# mesma e o corpus vira eco.
EM_REPLAY: contextvars.ContextVar = contextvars.ContextVar("sentury_em_replay", default=False)
# A chamada de ferramenta pode ser capturada pelo orquestrador e virar texto.
# Guarde a tentativa aqui para o replay falhar mesmo nesse caso.
REPLAY_BLOQUEIOS: contextvars.ContextVar = contextvars.ContextVar("sentury_replay_bloqueios", default=None)

# Resultados de acoes e leituras dependentes do ambiente. O replay os serve
# sem executar contra o mundo atual.
RESULTADOS_DO_TURNO: contextvars.ContextVar = contextvars.ContextVar("sentury_resultados_do_turno", default=None)
REPLAY_FERRAMENTAS: contextvars.ContextVar = contextvars.ContextVar("sentury_replay_ferramentas", default=None)

# 2 = `resultado_observado.ferramentas` diz o que rodou de verdade.
FORMATO_DO_OBSERVADO = 2

# Texto acima disso no resultado de ferramenta e imagem em base64 ou pagina
# inteira: o replay nao precisa do conteudo, porque a resposta do modelo ja
# esta gravada, e o traco ficaria com megabytes.
_TEXTO_MAXIMO_NO_TRACO = 20_000

class ExecutadasNoTurno(list):
    """Os resultados de ferramenta do turno, com o nome de cada uma anotado ao lado.

    `harness.events` não diz o que rodou. Sem
    esta lista a comparação do replay não vê ferramenta nenhuma, e uma mudança
    que fizesse o agente parar de chamar `listar_arquivos` passaria como igual
    se a frase final saísse igual.

    So o nome vai para o `harness`, e nao o resultado: a saida de permissao
    espalha o `decision_log` inteiro na resposta, e resultado de ferramenta ali
    seria dado pesado (e as vezes nao serializavel) indo para a tela.
    """

    def __init__(self, nomes: list):
        super().__init__()
        self._nomes = nomes

    def append(self, item: Any) -> None:
        super().append(item)
        nome = item.get("tool") if isinstance(item, dict) else None
        if nome:
            self._nomes.append(str(nome))


def _nao_deterministas() -> frozenset:
    """O que não pode rodar de novo no replay: a leitura que muda a cada vez e
    tudo que age no mundo. Esta segunda parte só repete servindo o resultado
    gravado (ver `sem_resultado_gravado`)."""
    from ..tools.registry import TOOL_REGISTRY

    return frozenset(
        nome for nome, meta in TOOL_REGISTRY.items()
        if meta.get("determinista") is False or meta.get("replay_leitura") is not True
    )


def precisa_gravar(tool: str) -> bool:
    """Somente a leitura autorizada no registro roda de novo; as demais
    ferramentas precisam do resultado gravado, inclusive as que so leem."""
    from ..tools.registry import TOOL_REGISTRY

    return TOOL_REGISTRY.get(tool, {}).get("replay_leitura") is not True


def _leve(valor: Any) -> Any:
    """O resultado em JSON puro, sem texto gigante: objeto que nao serializa
    vira texto e string enorme vira um marcador com o tamanho."""
    import json

    def podar(item: Any) -> Any:
        if isinstance(item, str) and len(item) > _TEXTO_MAXIMO_NO_TRACO:
            return f"[omitido no traço: {len(item)} caracteres]"
        if isinstance(item, dict):
            return {str(k): podar(v) for k, v in item.items()}
        if isinstance(item, list):
            return [podar(v) for v in item]
        return item

    try:
        from ..exec.segredos import sanitizar_dados

        return podar(sanitizar_dados(json.loads(json.dumps(valor, ensure_ascii=False, default=str))))
    except Exception:
        from ..exec.segredos import redigir_segredos

        return redigir_segredos(str(valor))[:_TEXTO_MAXIMO_NO_TRACO]


def anotar_resultado(
    tool: str, argumentos: Dict[str, Any], resultado: Any = None, erro: str = "", tipo_erro: str = "",
) -> None:
    """Guarda o que a ferramenta devolveu, quando o turno esta sendo gravado."""
    lista = RESULTADOS_DO_TURNO.get()
    if lista is None or not precisa_gravar(tool):
        return
    registro: Dict[str, Any] = {"tool": tool, "argumentos": _leve(argumentos or {})}
    if erro:
        registro["erro"] = _leve(erro)
        if tipo_erro:
            registro["tipo_erro"] = tipo_erro
    else:
        registro["resultado"] = _leve(resultado)
    lista.append(registro)


def _pedido(argumentos: Any) -> Any:
    """Os argumentos como o modelo pediu. Chave com `_` é anotação que a
    ferramenta põe durante a execução, e no replay o pedido chega sem ela."""
    leve = _leve(argumentos or {})
    if not isinstance(leve, dict):
        return leve
    return {k: v for k, v in leve.items() if not k.startswith("_")}


def sem_resultado_gravado(ferramentas: List[str], resultados: List[Dict[str, Any]]) -> List[str]:
    """As ferramentas do turno que agem no mundo e não têm resultado gravado
    para o replay servir no lugar de agir de novo."""
    gravadas = Counter(r.get("tool") for r in resultados or [] if isinstance(r, dict))
    faltam = []
    for nome in ferramentas or []:
        if not precisa_gravar(nome):
            continue
        if gravadas[nome] > 0:
            gravadas[nome] -= 1
        else:
            faltam.append(nome)
    return faltam


class FilaDeResultados:
    """Os resultados gravados, servidos no replay a quem pede a mesma
    ferramenta com os mesmos argumentos.

    Casa pelo pedido e não pela posição: ferramentas em paralelo terminam em
    outra ordem, e a produção gravou na ordem de término. Pedido sem par é
    divergência: servir um resultado gravado para outro pedido mediria um
    mundo que não aconteceu.
    """

    def __init__(self, registros: List[Dict[str, Any]]):
        self._pendentes = [dict(r) for r in registros or [] if isinstance(r, dict)]
        self.servidos = 0
        self.divergencias: List[str] = []

    @property
    def sobraram(self) -> int:
        return len(self._pendentes)

    def tem(self, tool: str, argumentos: Dict[str, Any]) -> bool:
        """Se há resultado gravado para este pedido, sem consumir."""
        pedido = _pedido(argumentos)
        return any(r.get("tool") == tool and _pedido(r.get("argumentos")) == pedido for r in self._pendentes)

    def servir(self, tool: str, argumentos: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        pedido = _pedido(argumentos)
        for i, registro in enumerate(self._pendentes):
            if registro.get("tool") == tool and _pedido(registro.get("argumentos")) == pedido:
                self.servidos += 1
                return self._pendentes.pop(i)
        mesma = any(r.get("tool") == tool for r in self._pendentes)
        self.divergencias.append(
            f"{tool}: {'argumentos diferentes do gravado' if mesma else 'sem resultado gravado'}"
        )
        return None


def aprovado_na_gravacao(tool: str, argumentos: Dict[str, Any]) -> bool:
    """No replay, a ação com resultado gravado rodou na produção, então teve
    aprovação lá. A aprovação não fica no traço; sem isto o replay pede o
    cartão de novo e nunca chega ao resultado gravado."""
    fila = REPLAY_FERRAMENTAS.get()
    return bool(EM_REPLAY.get() and fila is not None and fila.tem(tool, argumentos or {}))


def resultado_gravado(registro: Dict[str, Any]) -> Any:
    """Devolve o que a ferramenta devolveu na produção, ou levanta o mesmo erro.

    O tipo do erro importa: o laço trata prazo estourado diferente de falha
    comum, e o replay tem que levar o turno pelo mesmo caminho."""
    if "erro" in registro:
        classe = getattr(builtins, str(registro.get("tipo_erro") or ""), None)
        mensagem = str(registro["erro"])
        erro: Exception = RuntimeError(mensagem)
        if isinstance(classe, type) and issubclass(classe, Exception):
            try:
                erro = classe(mensagem)
            except Exception:
                pass
        raise erro
    return copy.deepcopy(registro.get("resultado"))


def ligado() -> bool:
    from ..config import settings

    if EM_REPLAY.get():
        return False
    return bool(getattr(settings, "SENTURY_GRAVAR_TRACOS", False))


def abrir(state: Any) -> Optional[Dict[str, Any]]:
    """O estado de antes do turno. Tem que ser AGORA: o histórico é mutado
    durante a execução, e gravar no fim guardaria a resposta junto da
    pergunta."""
    if not ligado():
        return None
    RESULTADOS_DO_TURNO.set([])
    try:
        from robinbandit.chain import iniciar_gravacao

        iniciar_gravacao()
    except Exception:
        logger.debug("Nao consegui iniciar a gravacao das respostas.", exc_info=True)
    try:
        return state.to_dict()
    except Exception:
        logger.debug("Nao consegui fotografar o estado de entrada.", exc_info=True)
        return None


def _ambiente(nivel: Optional[str]) -> Dict[str, Any]:
    from ..config import settings

    dados: Dict[str, Any] = {
        # Traco gravado antes deste campo tem `ferramentas: []` mesmo quando
        # rodou ferramenta (ver `ExecutadasNoTurno`). O replay usa a marca para
        # nao acusar mudanca onde so a gravacao era cega.
        "formato_do_observado": FORMATO_DO_OBSERVADO,
        "esforco": nivel,
        "dominio": getattr(settings, "SENTURY_DOMAIN", ""),
        "native_tools": bool(getattr(settings, "SENTURY_NATIVE_TOOLS", False)),
        "agent_loop": bool(getattr(settings, "SENTURY_AGENT_LOOP", False)),
    }
    try:
        from robinbandit.sentury import active_ultra_tier

        dados["modo"] = active_ultra_tier() or "router"
    except Exception:
        dados["modo"] = ""
    try:
        from ..mutation.isolamento import commit_atual

        dados["commit"] = commit_atual() or ""
    except Exception:
        dados["commit"] = ""
    # A pasta decide o que é liberado e o que pede cartão; o replay a repõe.
    try:
        from ..tools.arquivos import raiz_de_trabalho

        dados["pasta_de_trabalho"] = str(raiz_de_trabalho())
    except Exception:
        dados["pasta_de_trabalho"] = ""
    return dados


def _despacho(resultado: Dict[str, Any]) -> Dict[str, Any]:
    """Caminho do turno (nativo ou texto): o replay o repete mesmo quando a
    primeira chamada falhou e não sobrou resposta para mostrar qual era."""
    telemetria = (resultado or {}).get("telemetry") if isinstance(resultado, dict) else None
    despacho = (telemetria or {}).get("despacho")
    return {"despacho": despacho} if despacho else {}


def observar(resultado: Dict[str, Any]) -> Dict[str, Any]:
    """O que o turno produziu, na forma que a producao e o replay comparam.

    Uma funcao so para os dois lados: se a gravacao e o `repetir()` lessem o
    resultado cada um do seu jeito, a diferenca entre eles apareceria como
    mudanca de codigo.
    """
    resultado = resultado if isinstance(resultado, dict) else {}
    harness = resultado.get("harness") or {}
    return {
        "mensagem": str(resultado.get("message") or ""),
        "ferramentas": [str(n) for n in (harness.get("ferramentas") or [])],
        "anexo": (resultado.get("attachment") or {}).get("type", ""),
    }


def _repete(ferramentas: List[str], resultados: List[Dict[str, Any]]) -> bool:
    """O turno repete igual quando toda ação no mundo tem resultado gravado e
    nenhuma leitura que roda de novo muda a cada vez."""
    variaveis = set(ferramentas) & _nao_deterministas()
    lidas_de_novo = {nome for nome in variaveis if not precisa_gravar(nome)}
    return not lidas_de_novo and not sem_resultado_gravado(ferramentas, resultados)


def fechar(
    state: Any,
    user_message: str,
    resultado: Dict[str, Any],
    antes: Optional[Dict[str, Any]],
    nivel: Optional[str] = None,
) -> None:
    if antes is None or not ligado():
        return
    try:
        from robinbandit.chain import respostas_do_turno

        respostas = respostas_do_turno() or []
    except Exception:
        respostas = []

    resultados = list(RESULTADOS_DO_TURNO.get() or [])
    try:
        from ..mutation import replay

        observado = observar(resultado)
        replay.gravar(
            mensagem=user_message,
            estado_inicial=antes,
            respostas_llm=respostas,
            resultado_observado=observado,
            resultados_ferramentas=resultados,
            ambiente={**_ambiente(nivel), **_despacho(resultado)},
            origem=str(getattr(state, "session_id", "") or ""),
            determinista=_repete(observado["ferramentas"], resultados),
            # Turno de producao nasce em desenvolvimento. Cair direto em
            # `avaliacao` seria o vazamento que `separar_holdout()` existe
            # para evitar: a mutacao se ajustaria ao proprio gabarito.
            conjunto="desenvolvimento",
        )
    except Exception:
        logger.debug("Nao consegui gravar o traco do turno.", exc_info=True)
        return
    try:
        replay.podar_se_preciso()
    except Exception:
        logger.debug("Nao consegui podar os tracos.", exc_info=True)


__all__ = [
    "EM_REPLAY", "REPLAY_BLOQUEIOS", "REPLAY_FERRAMENTAS", "RESULTADOS_DO_TURNO", "ExecutadasNoTurno",
    "FORMATO_DO_OBSERVADO", "FilaDeResultados", "abrir", "anotar_resultado", "fechar", "ligado", "observar",
    "aprovado_na_gravacao", "precisa_gravar", "resultado_gravado", "sem_resultado_gravado",
]
