"""As operações da HQ, num lugar só: a API chama estas, e o cliente em modo
local também. Assim o PC sem Docker e a VPS fazem exatamente a mesma coisa."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from . import manifesto as _m
from . import mesa as _mesa
from . import orcamento as _orcamento
from . import registro as _registro
from . import tarefas as _tarefas
from . import worker as _worker
from .aparencia import cores

PEDIDO_DE_FERRAMENTA = _tarefas.PEDIDO_DE_FERRAMENTA


class NaoEncontrado(LookupError):
    pass


def sessao_do(nome: str) -> str:
    """A conversa do agente: uma por agente, persistente entre tarefas."""
    return f"agente:{nome}"


def sessao_da_vez(nome: str, origem: str = "") -> Tuple[str, bool]:
    """Onde roda o turno, e se ele começa sem histórico. A vez na Mesa traz a conversa do
    assunto no próprio pedido; com o histórico do residente junto, o modelo imita as voltas
    antigas ("minha fala foi registrada") em vez de falar. Ela roda numa sessão à parte."""
    if str(origem or "").startswith(_mesa.ORIGEM):
        return f"{sessao_do(nome)}:mesa", True
    return sessao_do(nome), False


def _ficha(agente: _m.Manifesto) -> Dict[str, Any]:
    todas = _tarefas.listar(agente.nome)
    abertas = [t for t in todas if t.estado in _tarefas.ABERTAS]
    ultima = todas[-1] if todas else None
    return {
        **agente.para_dict(),
        "uso_de_hoje": _orcamento.uso_de_hoje(agente.nome),
        "corte": _orcamento.corte(agente),
        "acordado": _worker.acordado(agente.nome),
        "tarefas_abertas": len(abertas),
        "previa": (ultima.resposta or ultima.pedido)[:160] if ultima else "",
        # As cores já resolvidas: o client desenha sem conhecer o catálogo.
        "cores": cores(agente.aparencia),
    }


def _exigir(nome: str) -> _m.Manifesto:
    agente = _registro.carregar(nome)
    if agente is None:
        raise NaoEncontrado(f"não existe agente '{nome}'")
    return agente


def criar(manifesto: Dict[str, Any], criado_por: str = "") -> Dict[str, Any]:
    return _ficha(_registro.criar(manifesto, criado_por=criado_por))


def listar() -> List[Dict[str, Any]]:
    return [_ficha(a) for a in _registro.listar()]


# O retrato da equipe no turno do Sentury tem teto: a seção não cresce com a equipe.
TETO_DO_RETRATO = 1_400


def _situacao(agente: _m.Manifesto) -> str:
    # A vez na Mesa é conversa entre eles; aqui conta o trabalho.
    abertas = [t for t in _tarefas.listar(agente.nome)
               if t.estado in _tarefas.ABERTAS and not t.origem.startswith(_mesa.ORIGEM)]
    da_pessoa = next((t for t in abertas if t.estado == _tarefas.ESPERANDO and not t.aguardando), None)
    rodando = next((t for t in abertas if t.estado == _tarefas.RODANDO), None)
    if da_pessoa is not None:
        situacao = f"espera você: {da_pessoa.motivo or 'uma resposta'}"
    elif rodando is not None:
        pedido = " ".join(rodando.pedido.split())
        situacao = f'trabalhando em "{pedido[:90]}{"…" if len(pedido) > 90 else ""}"'
    elif any(t.estado == _tarefas.ESPERANDO for t in abertas):
        situacao = "esperando colegas"
    elif abertas:
        situacao = f"{len(abertas)} tarefa(s) na fila"
    else:
        situacao = "pausado" if agente.estado == _m.PAUSADO else "livre"
    corte = _orcamento.corte(agente)
    return f"{situacao}; {corte}" if corte else situacao


def retrato_para_o_sentury() -> str:
    """A equipe agora, para o turno do Sentury principal: quem existe, o papel e o
    que cada um está fazendo. Sem isso ele só sabia da equipe se perguntasse."""
    linhas, usado = [], 0
    agentes = _registro.listar()
    for i, agente in enumerate(agentes):
        Nome = agente.nome[:1].upper() + agente.nome[1:]
        linha = f"- {Nome} ({agente.papel}): {_situacao(agente)}"
        if usado + len(linha) > TETO_DO_RETRATO:
            linhas.append(f"- e mais {len(agentes) - i}; `pedir_ao_agente` com `listar` mostra todos")
            break
        linhas.append(linha)
        usado += len(linha)
    if not linhas:
        return ""
    return "\n".join(["### EQUIPE DE RESIDENTES", *linhas,
                      "São os residentes que você criou, agora. Para pedir trabalho a um deles, use "
                      "`pedir_ao_agente`; o andamento de uma tarefa vem com `acompanhar`."])


def ver(nome: str, ultimas: int = 10) -> Dict[str, Any]:
    agente = _exigir(nome)
    recentes = _tarefas.listar(nome)[-ultimas:]
    return {**_ficha(agente), "memoria": _registro.ler_memoria(nome),
            "tarefas": [t.publico() for t in reversed(recentes)]}


def mudar(nome: str, acao: str) -> Dict[str, Any]:
    _exigir(nome)
    funcoes = {"pausar": _registro.pausar, "retomar": _registro.retomar,
               "aposentar": _registro.aposentar}
    if acao not in funcoes:
        raise _m.ManifestoInvalido(f"ação '{acao}' não existe: use {', '.join(funcoes)}")
    agente = funcoes[acao](nome)
    if acao == "retomar":
        _worker.acordar(nome)
    if acao == "pausar":
        # O pedido de colega na fila volta para quem pediu; o da pessoa espera a retomada.
        for tarefa in _tarefas.listar(nome, (_tarefas.NA_FILA,)):
            if tarefa.origem.startswith("agente:"):
                _worker.terminou(_tarefas.cancelar(tarefa.id, f"{nome[:1].upper()}{nome[1:]} foi pausado"))
    return _ficha(agente)


def editar(nome: str, campos: Dict[str, Any]) -> Dict[str, Any]:
    _exigir(nome)
    return _ficha(_registro.editar(nome, campos))


def trocar_acessorios(nome: str, acessorios: Any) -> Dict[str, Any]:
    _exigir(nome)
    return _ficha(_registro.trocar_acessorios(nome, acessorios))


def catalogo_de_aparencia() -> Dict[str, Any]:
    """Famílias, plumagens e encaixes, para o client montar as corujas."""
    from .aparencia import catalogo

    return catalogo()


def pedir(nome: str, pedido: str, origem: str = "", pai: str = "", anexos=None) -> Dict[str, Any]:
    agente = _exigir(nome)
    if agente.estado == _m.APOSENTADO:
        raise _m.ManifestoInvalido(f"'{nome}' está aposentado")
    if origem.startswith("agente:"):
        # O colega que pede não pode ficar esperando quem não vai andar hoje: ele
        # sabe na hora e escolhe outro caminho. O pedido da pessoa espera na fila.
        motivo = "está pausado" if agente.estado == _m.PAUSADO else _orcamento.corte(agente)
        if motivo:
            raise _m.ManifestoInvalido(
                f"{nome[:1].upper()}{nome[1:]} não pode pegar tarefa agora: {motivo}. Peça a outro "
                "colega ou siga sem essa parte e diga na resposta o que faltou")
    tarefa = _tarefas.enfileirar(nome, pedido, origem, pai, anexos=anexos)
    acordou = _worker.acordar(nome)
    resposta = tarefa.publico()
    if agente.estado == _m.PAUSADO:
        resposta["aviso"] = f"{nome[:1].upper()}{nome[1:]} está pausado; a tarefa espera ele ser retomado"
    elif not acordou and not _worker.acordado(nome):
        resposta["aviso"] = "a HQ não tem worker ligado: a tarefa fica na fila"
    return resposta


def tarefa(tarefa_id: str) -> Dict[str, Any]:
    achada = _tarefas.carregar(tarefa_id)
    if achada is None:
        raise NaoEncontrado(f"não existe tarefa '{tarefa_id}'")
    return achada.publico()


def responder(tarefa_id: str, resposta: str, retorno: str = "") -> Dict[str, Any]:
    """A pessoa responde à tarefa que esperava por ela.

    `resposta` segue o cartão de permissão (uma_vez, sessao, sempre, negar);
    `retorno` é o texto livre, para quando o agente fez uma pergunta.
    """
    achada = _tarefas.carregar(tarefa_id)
    if achada is None:
        raise NaoEncontrado(f"não existe tarefa '{tarefa_id}'")
    if achada.estado != _tarefas.ESPERANDO:
        raise _tarefas.TarefaInvalida(f"a tarefa está '{achada.estado}', não esperando")
    if achada.motivo == "pessoa no controle":
        raise _tarefas.TarefaInvalida("A pessoa está no controle do navegador; devolva pela aba Tela.")
    if achada.aguardando:
        raise _tarefas.TarefaInvalida("a tarefa espera outros residentes, não a pessoa")
    comando = achada.pendente
    if resposta and comando:
        from ..tools.permissoes import responder as _responder

        _responder(comando, resposta, sessao_do(achada.agente))
    negou = resposta in ("negar", "negar_sempre")
    if negou and comando.startswith(PEDIDO_DE_FERRAMENTA):
        # Ferramenta negada não encerra a tarefa: ele segue sem ela.
        ferramenta = comando[len(PEDIDO_DE_FERRAMENTA):].strip()
        liberada = _tarefas.devolver_a_fila(
            tarefa_id, retorno or f"não liberou a ferramenta {ferramenta}; siga sem ela",
            negado=comando)
        _worker.acordar(achada.agente)
        return liberada.publico()
    if negou:
        cancelada = _tarefas.cancelar(tarefa_id, "a pessoa negou a autorização")
        _worker.terminou(cancelada)
        return cancelada.publico()
    liberada = _tarefas.devolver_a_fila(tarefa_id, retorno or resposta)
    _worker.acordar(achada.agente)
    return liberada.publico()


def esperando() -> List[Dict[str, Any]]:
    """As tarefas que esperam a pessoa, de todos os agentes."""
    return [t.publico() for t in _tarefas.listar(estados=(_tarefas.ESPERANDO,)) if not t.aguardando]


def eventos(desde: float = 0.0, limite: int = 60) -> List[Dict[str, Any]]:
    """O feed do Escritório: o que aconteceu nas tarefas e na Mesa."""
    juntos = _tarefas.eventos_recentes(desde, limite) + _mesa.eventos_recentes(desde, limite)
    juntos.sort(key=lambda e: e["em"], reverse=True)
    return juntos[:limite]


# ---------- A Mesa ----------

def abrir_assunto(titulo: str, aberto_por: str = "pessoa", texto: str = "", canal: str = "") -> Dict[str, Any]:
    if aberto_por != "pessoa":
        agente = _exigir(aberto_por)
        teto = int(agente.autonomia.get("iniciativas_por_dia", 0))
        if _mesa.abertos_hoje_por(aberto_por) >= teto:
            raise _mesa.AssuntoInvalido(
                f"{aberto_por} já abriu {teto} assunto(s) hoje, o teto de iniciativas; um pedido a "
                "um colega com `pedir_ao_agente` continua valendo, e o teto volta amanhã")
    assunto = _mesa.abrir(titulo, aberto_por, "" if aberto_por != "pessoa" else texto, canal)
    if aberto_por != "pessoa" and str(texto or "").strip():
        # O residente que abre já disse o que queria: essa é a primeira fala dele.
        assunto = _mesa.falar(assunto.id, aberto_por, texto)
    _mesa.em_segundo_plano(_convidar_e_dar_a_vez(assunto.id))
    return assunto.publico()


def falar_na_mesa(assunto_id: str, texto: str) -> Dict[str, Any]:
    """A pessoa entra num assunto aberto; quem ela chamou, ou a mesa toda, ganha a vez."""
    assunto = _mesa.falar(assunto_id, _mesa.PESSOA, texto)
    dar_a_vez(assunto.id)
    return assunto.publico()


async def _convidar_e_dar_a_vez(assunto_id: str) -> None:
    try:
        await _mesa.convidar(assunto_id)
    finally:
        dar_a_vez(assunto_id)


def _fala_pendente(assunto_id: str) -> bool:
    origem = f"{_mesa.ORIGEM}{assunto_id}"
    return any(t.origem == origem for t in _tarefas.listar(estados=_tarefas.ABERTAS))


def dar_a_vez(assunto_id: str) -> None:
    """Põe na fila a próxima fala, ou o fechamento. Uma vez de cada assunto por vez."""
    assunto = _mesa.carregar(assunto_id)
    if assunto is None or assunto.estado != _mesa.ABERTO or _fala_pendente(assunto_id):
        return
    origem = f"{_mesa.ORIGEM}{assunto_id}"
    nome = _mesa.proximo(assunto)
    if nome:
        pedir(nome, _mesa.pedido_da_fala(assunto, nome), origem)
        return
    if assunto.aberto_por == _mesa.PESSOA and not assunto.fechando:
        # A conversa é da pessoa, mas a Mesa existe para decidir: acabada a rodada, quem conduz
        # media. Sem o que mediar, ou depois do limite, a vez volta para ela.
        quem = _mesa.quem_fecha(assunto)
        if quem and _mesa.houve_conversa(assunto) and assunto.mediacoes < _mesa.LIMITE_DE_MEDIACOES:
            vez = pedir(quem, _mesa.pedido_da_fala(assunto, quem, mediando=True), origem)
            _mesa.marcar_mediando(assunto_id, quem, vez["id"])
            return
        _mesa.esperar_a_pessoa(assunto_id)
        return
    pedir_o_resumo(assunto)


def pedir_o_resumo(assunto: "_mesa.Assunto") -> None:
    """A vez de fechar vai para quem fecha; sem ninguém que tenha falado, fecha sem resumo."""
    quem = _mesa.quem_fecha(assunto)
    if quem is None or (assunto.fechando and not _fala_pendente(assunto.id)):
        _mesa.fechar(assunto.id, assunto.motivo or "ninguém falou", por=quem or "")
        return
    vez = pedir(quem, _mesa.pedido_da_fala(assunto, quem, fechando=True), f"{_mesa.ORIGEM}{assunto.id}")
    _mesa.marcar_fechando(assunto.id, vez["id"])


def depois_da_fala(tarefa: _tarefas.Tarefa) -> None:
    """Fim de uma tarefa da Mesa: registra o que o residente disse, se ele não
    usou a ferramenta, e passa a vez."""
    assunto_id = _mesa.de_origem(tarefa.origem)
    assunto = _mesa.carregar(assunto_id) if assunto_id else None
    if assunto is None or assunto.estado != _mesa.ABERTO:
        return
    nome = tarefa.agente
    if assunto.fechamento == tarefa.id and not assunto.fechando:
        # A pessoa falou enquanto o resumo era escrito: a conversa seguiu e o resumo velho sai.
        dar_a_vez(assunto_id)
        return
    agiu = _mesa.agiu_nesta_vez(assunto, nome, tarefa.criada_em)
    resposta = tarefa.resposta.strip() if tarefa.estado == _tarefas.FEITA else ""
    if assunto.fechando and nome == _mesa.quem_fecha(assunto):
        _mesa.fechar(assunto_id, resposta or assunto.motivo or "sem resumo", por=nome)
        return
    mediando = bool(assunto.mediacao) and assunto.mediacao == tarefa.id
    if not agiu:
        # A resposta em texto é a fala quando é a primeira dele na rodada, a resposta a quem o
        # chamou com @ ou a mediação; fora disso, conta como passar a vez.
        fala = _mesa.fala_da_vez(assunto, nome, tarefa.criada_em, resposta, mediando=mediando)
        if fala:
            # Cada um fala uma vez por rodada: a fala não devolve a palavra a todos, só a quem
            # ela chamou com @. Assim a rodada não vira recapitulação.
            _mesa.falar(assunto_id, nome, fala, reabre=False)
        else:
            # Sem ele escolher (sem orçamento, pausado, provedor fora), a vez passa com o motivo.
            motivo = tarefa.motivo if tarefa.estado in (_tarefas.CANCELADA, _tarefas.FALHOU) else ""
            _mesa.passar(assunto_id, nome, motivo)
    if mediando and _mesa.fala_da_vez(_mesa.carregar(assunto_id) or assunto, nome, tarefa.criada_em) is None:
        _mesa.encerrar_mediacao(assunto_id)
    dar_a_vez(assunto_id)


def _vezes() -> Dict[str, List[Dict[str, Any]]]:
    """Quem está com a vez em cada assunto, e se ainda está na fila ou já escrevendo. Quem
    já falou ou passou nesta vez sai: o resto do turno dele não aparece na conversa."""
    vezes: Dict[str, List[Dict[str, Any]]] = {}
    assuntos: Dict[str, Any] = {}
    for vez in _tarefas.listar(estados=_tarefas.ABERTAS):
        assunto_id = _mesa.de_origem(vez.origem)
        if not assunto_id:
            continue
        if assunto_id not in assuntos:
            assuntos[assunto_id] = _mesa.carregar(assunto_id)
        assunto = assuntos[assunto_id]
        if assunto is not None and _mesa.agiu_nesta_vez(assunto, vez.agente, vez.criada_em):
            continue
        papel = ("mediando" if assunto is not None and assunto.mediacao == vez.id
                 else "resumindo" if assunto is not None and assunto.fechamento == vez.id else "falando")
        # Desde quando ele está com a vez: a tela mostra a espera, e uma espera longa não parece travada.
        desde = next((e.get("em") for e in reversed(vez.eventos) if e.get("tipo") == "comecou"), vez.criada_em)
        # A tarefa vai junto para a Mesa mostrar, na conversa, a autorização que ela espera.
        vezes.setdefault(assunto_id, []).append({"agente": vez.agente, "estado": vez.estado, "papel": papel,
                                                 "desde": desde, "tarefa": vez.id})
    return vezes


def _encaminhadas(todas: List[_tarefas.Tarefa]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]:
    """O que saiu de cada assunto (as tarefas que os residentes pediram aos colegas durante as
    vezes dele, para a decisão não terminar só no papel) e quanto o assunto custou: as vezes de
    fala e o dinheiro delas, mais o dos próximos passos."""
    assunto_da_vez = {t.id: _mesa.de_origem(t.origem) for t in todas if _mesa.de_origem(t.origem)}
    saidas: Dict[str, List[Dict[str, Any]]] = {}
    custos: Dict[str, Dict[str, Any]] = {}
    for tarefa in todas:
        da_vez = assunto_da_vez.get(tarefa.id)
        if da_vez:
            conta = custos.setdefault(da_vez, {"vezes": 0, "usd": 0.0})
            conta["vezes"] += 1
            conta["usd"] += float(tarefa.custo_usd or 0)
        assunto_id = assunto_da_vez.get(tarefa.pai or "")
        if assunto_id:
            saidas.setdefault(assunto_id, []).append({
                "id": tarefa.id, "agente": tarefa.agente, "pedido": tarefa.pedido[:300],
                "estado": tarefa.estado, "resposta": tarefa.resposta[:1200]})
            custos.setdefault(assunto_id, {"vezes": 0, "usd": 0.0})["usd"] += float(tarefa.custo_usd or 0)
    return saidas, custos


def assuntos() -> List[Dict[str, Any]]:
    vezes = _vezes()
    saidas, custos = _encaminhadas(_tarefas.listar())
    return [{**a.publico(), "vez": vezes.get(a.id, []), "encaminhadas": saidas.get(a.id, []),
             "custo": custos.get(a.id, {"vezes": 0, "usd": 0.0})} for a in _mesa.listar()]


def apagar_assunto(assunto_id: str) -> Dict[str, Any]:
    """Apaga o assunto, a fala que esperava a vez nele e a decisão que saiu dele.
    A nota na memória de cada residente fica: o que ele viveu é dele."""
    if _mesa.carregar(assunto_id) is None:
        raise NaoEncontrado(f"não existe assunto '{assunto_id}'")
    origem = f"{_mesa.ORIGEM}{assunto_id}"
    for vez in _tarefas.listar(estados=_tarefas.ABERTAS):
        if vez.origem == origem:
            _worker.terminou(_tarefas.cancelar(vez.id))
    _mesa.apagar(assunto_id)
    from ..memory import decisoes as _decisoes

    _decisoes.apagar(origem)
    return {"ok": True, "id": assunto_id}


def decisoes() -> List[Dict[str, Any]]:
    """As decisões da equipe, da mais nova para a mais antiga, para a tela."""
    from ..memory import decisoes as _decisoes

    return _decisoes.listar()


def assunto(assunto_id: str) -> Dict[str, Any]:
    achado = _mesa.carregar(assunto_id)
    if achado is None:
        raise NaoEncontrado(f"não existe assunto '{assunto_id}'")
    return achado.publico()


def fechar_assunto(assunto_id: str, resumo: str = "") -> Dict[str, Any]:
    """Com resumo, fecha na hora; sem, quem coordenou escreve o resumo da conversa."""
    assunto = _mesa.carregar(assunto_id)
    if assunto is None:
        raise NaoEncontrado(f"não existe assunto '{assunto_id}'")
    if resumo.strip() or assunto.estado != _mesa.ABERTO or _mesa.quem_fecha(assunto) is None:
        return _mesa.fechar(assunto_id, resumo or "fechado pela pessoa", por="pessoa").publico()
    if not assunto.fechando:
        pedir_o_resumo(assunto)
    return (_mesa.carregar(assunto_id) or assunto).publico()


_worker.ao_terminar(depois_da_fala)


def cancelar(tarefa_id: str) -> Dict[str, Any]:
    if _tarefas.carregar(tarefa_id) is None:
        raise NaoEncontrado(f"não existe tarefa '{tarefa_id}'")
    cancelada = _tarefas.cancelar(tarefa_id)
    _worker.terminou(cancelada)
    return cancelada.publico()
