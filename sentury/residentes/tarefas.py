"""A fila: o que pediram a cada agente, e o que ele fez com isso.

Uma tarefa por arquivo, gravada a cada mudança de estado. O processo que cair
no meio de uma tarefa deixa ela `rodando` em disco; `recuperar` devolve essas
para a fila no próximo startup, com a tentativa contada.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import manifesto as _m

_LOCK = threading.RLock()

NA_FILA = "na_fila"
RODANDO = "rodando"
ESPERANDO = "esperando"  # parou pedindo aprovação ou com pergunta
FEITA = "feita"
FALHOU = "falhou"
CANCELADA = "cancelada"
ESTADOS = (NA_FILA, RODANDO, ESPERANDO, FEITA, FALHOU, CANCELADA)
ABERTAS = (NA_FILA, RODANDO, ESPERANDO)

MAX_TENTATIVAS = 3
TETO_DO_PEDIDO = 8_000
# Residente pede a residente: o pedido do Sentury é 0, o do primeiro residente 1.
MAX_PROFUNDIDADE = 2
# A resposta do colega é o trabalho dele e volta inteira; o turno de quem pediu
# aplica a régua de resultado grande (rascunho com começo e fim no contexto).
# Este teto só segura um texto descontrolado.
TETO_DA_RESPOSTA_DE_COLEGA = 60_000
# As respostas de todos os colegas de um pedido, juntas.
TETO_DO_RETORNO = 4 * TETO_DA_RESPOSTA_DE_COLEGA
# O comando do cartão quando um residente pede uma ferramenta que não tem.
PEDIDO_DE_FERRAMENTA = "ferramenta_nova "


class TarefaInvalida(ValueError):
    pass


@dataclass
class Tarefa:
    id: str
    agente: str
    pedido: str
    origem: str = ""  # "sentury", "telegram:<chat>", "conversa:...", "agente:<nome>"
    # Pedido de outro residente: a tarefa dele, que espera esta terminar.
    pai: str = ""
    profundidade: int = 0
    # O pai já recebeu esta resposta (na volta ou acompanhando).
    entregue: bool = False
    # As tarefas de colegas que esta espera para continuar.
    aguardando: List[str] = field(default_factory=list)
    estado: str = NA_FILA
    resposta: str = ""
    motivo: str = ""
    # O que a pessoa respondeu quando a tarefa esperava por ela.
    retorno: str = ""
    # O comando que espera aprovação, como o cartão de permissão o mostra.
    pendente: str = ""
    tentativas: int = 0
    custo_usd: float = 0.0
    # Turnos sem custo conhecido: assinatura, ou modelo pago sem preço no catálogo.
    turnos_sem_custo: int = 0
    criada_em: float = 0.0
    iniciada_em: float = 0.0
    terminada_em: float = 0.0
    atualizada_em: float = 0.0
    eventos: List[Dict[str, Any]] = field(default_factory=list)
    anexos: List[Dict[str, str]] = field(default_factory=list)

    def publico(self) -> Dict[str, Any]:
        dados = asdict(self)
        dados.pop("eventos", None)
        return dados


# A fila é lida a cada consulta da tela (lista de residentes, orçamento, vez da Mesa). A pasta
# é criada uma vez, e cada tarefa já lida fica na memória até o arquivo dela mudar no disco.
_PASTAS_PRONTAS: set = set()
_LIDAS: Dict[str, Tuple[Tuple[int, int, int], Dict[str, Any]]] = {}


def _marca(info: os.stat_result) -> Tuple[int, int, int]:
    """Data e tamanho podem repetir em duas gravações no mesmo tique do relógio; o
    identificador do arquivo muda a cada uma, porque cada gravação troca o arquivo."""
    return (info.st_ino, info.st_mtime_ns, info.st_size)


def _pasta() -> Path:
    pasta = _m.casa() / "tarefas"
    if str(pasta) not in _PASTAS_PRONTAS:
        pasta.mkdir(parents=True, exist_ok=True)
        _PASTAS_PRONTAS.add(str(pasta))
    return pasta


def _gravar(tarefa: Tarefa) -> Tarefa:
    tarefa.atualizada_em = time.time()
    alvo = _pasta() / f"{tarefa.id}.json"
    tmp = alvo.with_suffix(".tmp")
    texto = json.dumps(asdict(tarefa), ensure_ascii=False, indent=1)
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(alvo)
    # Quem grava já sabe o conteúdo: a leitura seguinte neste processo não depende do disco.
    try:
        _LIDAS[str(alvo)] = (_marca(alvo.stat()), json.loads(texto))
    except OSError:
        _LIDAS.pop(str(alvo), None)
    return tarefa


def _evento(tarefa: Tarefa, tipo: str, **dados: Any) -> None:
    tarefa.eventos.append({"em": time.time(), "tipo": tipo, **dados})
    del tarefa.eventos[:-50]


def carregar(tarefa_id: str) -> Optional[Tarefa]:
    limpo = "".join(c for c in str(tarefa_id or "") if c.isalnum() or c in "-_")
    if not limpo:
        return None
    dados = _dados(_pasta() / f"{limpo}.json")
    return _montar(dados) if dados is not None else None


def _dados(arquivo: Path) -> Optional[Dict[str, Any]]:
    """O conteúdo do arquivo, da memória enquanto ele não mudou no disco."""
    try:
        info = arquivo.stat()
    except OSError:
        return None
    marca = _marca(info)
    guardada = _LIDAS.get(str(arquivo))
    if guardada and guardada[0] == marca:
        return guardada[1]
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    _LIDAS[str(arquivo)] = (marca, dados)
    return dados


def _montar(dados: Dict[str, Any]) -> Tarefa:
    conhecidos = set(Tarefa.__dataclass_fields__)
    # Cópia a cada leitura: quem recebe a tarefa pode alterá-la antes de gravar.
    return Tarefa(**{k: copy.deepcopy(v) for k, v in dados.items() if k in conhecidos})


def listar(agente: str = "", estados: tuple = (), desde: float = 0.0) -> List[Tarefa]:
    achadas = []
    for arquivo in _pasta().glob("*.json"):
        dados = _dados(arquivo)
        # Filtra nos dados crus: só a tarefa que serve vira objeto.
        if dados is None or (agente and dados.get("agente") != agente):
            continue
        if estados and dados.get("estado") not in estados:
            continue
        if desde and float(dados.get("criada_em") or 0) < desde:
            continue
        achadas.append(_montar(dados))
    return sorted(achadas, key=lambda t: t.criada_em)


TETO_DO_FEED = 200


def eventos_recentes(desde: float = 0.0, limite: int = 60) -> List[Dict[str, Any]]:
    """O que aconteceu nas tarefas depois de `desde`, do mais novo para o mais antigo.

    É o feed do Escritório: cada evento sai com o agente, a tarefa e o começo do
    pedido, para a tela não abrir tarefa por tarefa. Só lê as tarefas que mudaram
    depois de `desde`."""
    limite = max(1, min(int(limite or 1), TETO_DO_FEED))
    achados: List[Dict[str, Any]] = []
    for arquivo in _pasta().glob("*.json"):
        tarefa = carregar(arquivo.stem)
        if tarefa is None or tarefa.atualizada_em <= desde:
            continue
        for evento in tarefa.eventos:
            if float(evento.get("em") or 0) <= desde:
                continue
            achados.append({
                **evento,
                "agente": tarefa.agente,
                "tarefa": tarefa.id,
                "pedido": tarefa.pedido[:160],
                "origem": tarefa.origem,
                # O comando que espera aprovação só faz sentido no evento de espera.
                "pendente": tarefa.pendente if evento.get("tipo") == ESPERANDO else "",
            })
    achados.sort(key=lambda e: e["em"], reverse=True)
    return achados[:limite]


def cadeia(tarefa: Tarefa) -> List[Tarefa]:
    """Os pais da tarefa, do mais próximo ao pedido original."""
    pais: List[Tarefa] = []
    atual = tarefa
    while atual.pai and len(pais) <= MAX_PROFUNDIDADE + 1:
        pai = carregar(atual.pai)
        if pai is None:
            break
        pais.append(pai)
        atual = pai
    return pais


def checar_pedido_de_colega(pai: Tarefa, agente: str) -> None:
    """Recusa o pedido que fecharia um laço ou passaria do limite de profundidade."""
    if agente == pai.agente:
        raise TarefaInvalida("um residente não pede a si mesmo")
    if agente in {t.agente for t in cadeia(pai)}:
        raise TarefaInvalida(f"'{agente}' já está esperando nesta cadeia de pedidos; "
                             "pedir a ele fecharia um laço")
    if pai.profundidade + 1 > MAX_PROFUNDIDADE:
        raise TarefaInvalida(f"a cadeia de pedidos já tem {pai.profundidade + 1} níveis; "
                             "resolva com o que tem ou devolva o que faltou")


def enfileirar(agente: str, pedido: str, origem: str = "", pai: str = "", anexos=None) -> Tarefa:
    pedido = str(pedido or "").strip()
    if not pedido:
        raise TarefaInvalida("o pedido está vazio")
    if len(pedido) > TETO_DO_PEDIDO:
        raise TarefaInvalida(f"o pedido passa de {TETO_DO_PEDIDO} caracteres")
    profundidade = 0
    if pai:
        de_quem = carregar(pai)
        if de_quem is None:
            raise TarefaInvalida(f"não existe tarefa '{pai}'")
        checar_pedido_de_colega(de_quem, agente)
        profundidade = de_quem.profundidade + 1
    agora = time.time()
    tarefa = Tarefa(id=f"t{int(agora)}-{uuid.uuid4().hex[:8]}", agente=agente, pedido=pedido,
                    origem=str(origem or ""), pai=str(pai or ""), profundidade=profundidade,
                    anexos=[dict(a) for a in (anexos or [])],
                    criada_em=agora)
    _evento(tarefa, "enfileirada", origem=tarefa.origem)
    with _LOCK:
        return _gravar(tarefa)


def da_mesa(tarefa: "Tarefa") -> bool:
    return str(tarefa.origem or "").startswith("mesa:")


def proxima(agente: str, mesa: Optional[bool] = None) -> Optional[Tarefa]:
    """A mais antiga na fila. Uma de cada vez por faixa: a que espera aprovação segura
    as de trás, porque a seguinte pode depender dela. A Mesa é uma faixa à parte do
    trabalho (`mesa=True`), para a conversa não esperar uma tarefa longa terminar;
    sem `mesa`, vale a fila inteira do agente."""
    with _LOCK:
        def na_faixa(t: "Tarefa") -> bool:
            return mesa is None or da_mesa(t) == mesa

        if any(na_faixa(t) for t in listar(agente, (RODANDO, ESPERANDO))):
            return None
        fila = [t for t in listar(agente, (NA_FILA,)) if na_faixa(t)]
        return fila[0] if fila else None


def _exigir(tarefa_id: str, *estados: str) -> Tarefa:
    tarefa = carregar(tarefa_id)
    if tarefa is None:
        raise TarefaInvalida(f"não existe tarefa '{tarefa_id}'")
    if estados and tarefa.estado not in estados:
        raise TarefaInvalida(f"a tarefa está '{tarefa.estado}'")
    return tarefa


def comecar(tarefa_id: str) -> Tarefa:
    with _LOCK:
        tarefa = _exigir(tarefa_id, NA_FILA)
        tarefa.estado = RODANDO
        tarefa.tentativas += 1
        tarefa.iniciada_em = time.time()
        _evento(tarefa, "comecou", tentativa=tarefa.tentativas)
        return _gravar(tarefa)


def retomar_controle(tarefa_id: str) -> Tarefa:
    with _LOCK:
        tarefa = _exigir(tarefa_id, NA_FILA)
        tarefa.estado = RODANDO
        return _gravar(tarefa)


def _somar_custo(tarefa: Tarefa, custo_usd: Optional[float]) -> None:
    """`None` é custo desconhecido, que não é o mesmo que grátis."""
    if custo_usd is None:
        tarefa.turnos_sem_custo += 1
    else:
        tarefa.custo_usd = round(tarefa.custo_usd + float(custo_usd), 6)


def _terminar(tarefa_id: str, estado: str, *, resposta: str = "", motivo: str = "",
              custo_usd: Optional[float] = 0.0) -> Tarefa:
    with _LOCK:
        tarefa = _exigir(tarefa_id)
        tarefa.estado = estado
        tarefa.resposta = str(resposta or tarefa.resposta)
        tarefa.motivo = str(motivo or "")
        _somar_custo(tarefa, custo_usd)
        if estado in (FEITA, FALHOU, CANCELADA):
            tarefa.terminada_em = time.time()
        extra: Dict[str, Any] = {}
        if estado == ESPERANDO and tarefa.aguardando:
            extra["aguardando"] = [c.agente for c in map(carregar, tarefa.aguardando) if c]
        _evento(tarefa, estado, motivo=tarefa.motivo, **extra)
        return _gravar(tarefa)


def registrar_custo(tarefa_id: str, custo_usd: Optional[float]) -> Tarefa:
    with _LOCK:
        tarefa = _exigir(tarefa_id)
        _somar_custo(tarefa, custo_usd)
        return _gravar(tarefa)


def concluir(tarefa_id: str, resposta: str, custo_usd: Optional[float] = 0.0) -> Tarefa:
    return _terminar(tarefa_id, FEITA, resposta=resposta, custo_usd=custo_usd)


def esperar(tarefa_id: str, motivo: str, resposta: str = "", custo_usd: Optional[float] = 0.0,
            pendente: str = "", aguardando: Optional[List[str]] = None) -> Tarefa:
    with _LOCK:
        tarefa = _exigir(tarefa_id)
        tarefa.pendente = str(pendente or "")
        tarefa.aguardando = list(aguardando or [])
        _gravar(tarefa)
    return _terminar(tarefa_id, ESPERANDO, resposta=resposta, motivo=motivo, custo_usd=custo_usd)


def falhar(tarefa_id: str, motivo: str, custo_usd: Optional[float] = 0.0, de_novo: bool = True) -> Tarefa:
    """Falha que ainda tem tentativa volta para a fila; a última fecha a tarefa. Com
    `de_novo=False` fecha na primeira: quem espera por ela não pode ficar parado."""
    with _LOCK:
        tarefa = _exigir(tarefa_id)
        if de_novo and tarefa.tentativas < MAX_TENTATIVAS:
            tarefa.estado = NA_FILA
            tarefa.motivo = str(motivo or "")
            _somar_custo(tarefa, custo_usd)
            _evento(tarefa, "volta_para_a_fila", motivo=tarefa.motivo)
            return _gravar(tarefa)
    return _terminar(tarefa_id, FALHOU, motivo=motivo, custo_usd=custo_usd)


def cancelar(tarefa_id: str, motivo: str = "cancelada") -> Tarefa:
    _exigir(tarefa_id, *ABERTAS)
    return _terminar(tarefa_id, CANCELADA, motivo=motivo)


def anotar(tarefa_id: str, motivo: str) -> Tarefa:
    """Diz por que a tarefa ainda não andou, sem mudar o estado dela."""
    with _LOCK:
        tarefa = _exigir(tarefa_id)
        if tarefa.motivo == motivo:
            return tarefa
        tarefa.motivo = str(motivo or "")
        return _gravar(tarefa)


def devolver_a_fila(tarefa_id: str, retorno: str = "", **dados: Any) -> Tarefa:
    """A que esperava volta para rodar, com a resposta junto. `dados` vai no
    evento: `por="colegas"` quando quem respondeu foram outros residentes,
    `negado=<comando>` quando a pessoa disse não a um pedido de ferramenta."""
    with _LOCK:
        tarefa = _exigir(tarefa_id, ESPERANDO)
        tarefa.estado = NA_FILA
        tarefa.retorno = str(retorno or "").strip()[:TETO_DO_RETORNO]
        tarefa.tentativas = 0
        tarefa.pendente = ""
        tarefa.aguardando = []
        _evento(tarefa, "liberada", **dados)
        return _gravar(tarefa)


TERMINADAS = (FEITA, FALHOU, CANCELADA)


def filhos(tarefa_id: str, *, so_nao_entregues: bool = False) -> List[Tarefa]:
    return [t for t in listar() if t.pai == tarefa_id and not (so_nao_entregues and t.entregue)]


def marcar_entregue(tarefa_id: str) -> None:
    with _LOCK:
        tarefa = carregar(tarefa_id)
        if tarefa is not None and not tarefa.entregue:
            tarefa.entregue = True
            _gravar(tarefa)


def _o_que_o_colega_devolveu(colega: Tarefa) -> str:
    Nome = colega.agente[:1].upper() + colega.agente[1:]
    if colega.estado == FEITA:
        resposta = colega.resposta.strip() or "terminou sem resposta em texto."
        if len(resposta) > TETO_DA_RESPOSTA_DE_COLEGA:
            resposta = resposta[:TETO_DA_RESPOSTA_DE_COLEGA] + " [...]"
        return f"{Nome} respondeu:\n{resposta}"
    if colega.estado == CANCELADA:
        return f"A tarefa de {Nome} foi cancelada: {colega.motivo or 'sem motivo'}."
    return f"{Nome} não conseguiu: {colega.motivo or colega.estado}."


def liberar_se_os_colegas_terminaram(tarefa_id: str) -> Optional[Tarefa]:
    """A tarefa que esperava colegas volta para a fila quando o último deles
    termina, com o que cada um devolveu. Devolve a tarefa liberada, ou None."""
    with _LOCK:
        tarefa = carregar(tarefa_id)
        if tarefa is None or tarefa.estado != ESPERANDO or not tarefa.aguardando:
            return None
        colegas = [c for c in map(carregar, tarefa.aguardando) if c is not None]
        if any(c.estado not in TERMINADAS for c in colegas):
            return None
        for colega in colegas:
            marcar_entregue(colega.id)
        retorno = "\n\n".join(_o_que_o_colega_devolveu(c) for c in colegas)
        return devolver_a_fila(tarefa_id, retorno, por="colegas")


def recuperar() -> int:
    """No startup: o que estava `rodando` quando o processo caiu volta para a fila."""
    voltaram = 0
    for tarefa in listar(estados=(RODANDO,)):
        falhar(tarefa.id, "o processo caiu no meio da tarefa")
        voltaram += 1
    return voltaram


def ultima_liberacao(tarefa: Tarefa) -> Optional[Dict[str, Any]]:
    return next((e for e in reversed(tarefa.eventos) if e.get("tipo") == "liberada"), None)


def retoma_passo_autorizado(tarefa: Tarefa) -> bool:
    """A tarefa volta de uma autorização da pessoa, e o passo bloqueado deve rodar.
    Tarefa nova, volta dos colegas e ferramenta negada não retomam passo nenhum."""
    liberada = ultima_liberacao(tarefa)
    return bool(liberada) and not liberada.get("por") and not liberada.get("negado")


def mensagem_do_turno(tarefa: Tarefa) -> str:
    """O que o agente lê no turno: o pedido, ou a continuação depois de quem
    ele esperava (a pessoa ou os colegas)."""
    liberada = ultima_liberacao(tarefa)
    if liberada is None:
        if tarefa.origem.startswith("agente:"):
            de = tarefa.origem.split(":", 1)[1]
            return f"{de[:1].upper()}{de[1:]}, outro residente, te pediu:\n{tarefa.pedido}"
        return tarefa.pedido
    if liberada.get("por") == "colegas":
        return ("Os colegas devolveram o que você pediu com `pedir_ao_agente`; as respostas estão no "
                "resultado dessa ferramenta, logo acima. Continue a tarefa de onde parou. "
                f"O pedido original era:\n{tarefa.pedido}")
    return (f"A pessoa respondeu: {tarefa.retorno or 'autorizado'}.\n\n"
            f"Continue a tarefa de onde parou. O pedido original era:\n{tarefa.pedido}")


def resultado_dos_colegas(tarefa: Tarefa) -> Optional[str]:
    """O que os colegas devolveram, como resultado do `pedir_ao_agente` que os chamou.

    É resultado de ferramenta, e não fala da pessoa: assim o número que o colega
    calculou conta como lastro na resposta de quem pediu.
    """
    liberada = ultima_liberacao(tarefa)
    if liberada is None or liberada.get("por") != "colegas":
        return None
    return f'RESULTADO DA FERRAMENTA "pedir_ao_agente" (já executada):\n{tarefa.retorno}'
