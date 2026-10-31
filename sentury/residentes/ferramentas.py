"""O despacho de `criar_agente`, `pedir_ao_agente`, `memoria_do_agente` e
`pedir_ferramenta`.

Criar agente e dar ferramenta nova a um residente se confirmam sempre na hora:
"permitir tudo" e "sempre" não valem, só o "desta vez" do cartão.
"""
from __future__ import annotations

from typing import Any, Dict

from . import cliente as _cliente
from . import manifesto as _m

_CAMPOS = ("nome", "papel", "objetivo", "ferramentas", "personalidade", "instrucoes",
           "canais", "orcamento", "familia", "acessorios", "cerebro")


def _resumo(manifesto: _m.Manifesto) -> str:
    return (f"{manifesto.nome}, {manifesto.papel}. Objetivo: {manifesto.objetivo} "
            f"Ferramentas: {', '.join(manifesto.ferramentas)}. "
            f"Orçamento: US$ {manifesto.orcamento['usd_por_dia']:.2f} e "
            f"{int(manifesto.orcamento['turnos_por_dia'])} turnos por dia. "
            + (f"Cérebro: {manifesto.cerebro['modelo']} via {manifesto.cerebro['provedor']}."
               if manifesto.cerebro else "Cérebro: o Router do RobinBandit."))


def _autorizar(manifesto: _m.Manifesto, sessao: str) -> Dict[str, Any] | None:
    from ..exec.contrato import CodigoDeErro
    from ..exec.politica import avaliar

    comando = f"criar_agente {manifesto.nome}"
    decisao = avaliar(comando, sessao, checar_alvo=False, na_hora=True)
    if decisao.get("permitido"):
        return None
    base = {"ok": False, "executado": False, "fase": "permissao", "chave": "criar_agente",
            "motivo": f"criar o agente residente {_resumo(manifesto)}", "comando": comando,
            "manifesto": manifesto.para_dict()}
    if decisao.get("precisa_perguntar"):
        return {**base, "precisa_permissao": True, "so_desta_vez": True,
                "codigo_erro": CodigoDeErro.PRECISA_PERMISSAO}
    return {**base, "recusado": True, "motivo": str(decisao.get("motivo") or ""),
            "codigo_erro": CodigoDeErro.RECUSADO_POLITICA}


async def _criar(argumentos: Dict[str, Any], state: Any) -> Dict[str, Any]:
    dados = {k: argumentos[k] for k in _CAMPOS if k in argumentos}
    try:
        manifesto = _m.validar(dados)
    except _m.ManifestoInvalido as exc:
        return {"ok": False, "erro": str(exc)}
    pedido = _autorizar(manifesto, str(getattr(state, "session_id", "") or ""))
    if pedido is not None:
        return pedido
    try:
        ficha = await _cliente.criar(dados, criado_por=str(getattr(state, "user_id", "") or ""))
    except (_m.ManifestoInvalido, _cliente.HQIndisponivel) as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": True, "agente": ficha, "hq": _cliente.onde(),
            "proximo_passo": f"o agente existe e está dormindo; use `pedir_ao_agente` para dar "
                             f"a primeira tarefa a {manifesto.nome}"}


async def _pedir(argumentos: Dict[str, Any]) -> Dict[str, Any]:
    from . import tarefas as _tarefas
    from .escopo import agente_do_turno, tarefa_do_turno

    eu, minha = agente_do_turno(), tarefa_do_turno()
    acao = str(argumentos.get("acao") or "listar").strip().lower()
    try:
        if acao == "listar":
            return {"ok": True, "agentes": await _cliente.listar(), "hq": _cliente.onde()}
        if acao == "pedir":
            agente = str(argumentos.get("agente") or "").strip().lower()
            pedido = str(argumentos.get("pedido") or "").strip()
            if not agente or not pedido:
                return {"ok": False, "erro": "`pedir` precisa de `agente` e `pedido`"}
            if eu is None:
                tarefa = await _cliente.pedir(agente, pedido)
                return {"ok": True, "tarefa": tarefa,
                        "proximo_passo": "a tarefa está na fila; `acompanhar` com o `tarefa_id` "
                                         "mostra a resposta quando ele terminar"}
            if agente == "sentury":
                return {"ok": False,
                        "erro": "o Sentury não recebe pedido por aqui: a sua resposta final já volta "
                                "para quem pediu. Ferramenta que falta se pede com `pedir_ferramenta`; "
                                "trabalho de colega, com o nome dele (`listar` mostra a equipe)"}
            Nome = agente[:1].upper() + agente[1:]
            aberta = next((t for t in _tarefas.filhos(getattr(minha, "id", "") or "")
                           if t.agente == agente and t.estado in _tarefas.ABERTAS), None) if minha else None
            if aberta is not None:
                return {"ok": False, "tarefa": aberta.publico(),
                        "erro": f"você já pediu a {Nome} nesta tarefa e o pedido está "
                                f"'{aberta.estado}'. Termine o turno: a sua tarefa volta com a "
                                f"resposta dele, e aí você pede o resto"}
            tarefa = await _cliente.pedir(agente, pedido, f"agente:{eu.nome}",
                                          getattr(minha, "id", "") or "")
            if minha is not None and _tarefas.da_mesa(minha):
                return {"ok": True, "tarefa": tarefa,
                        "proximo_passo": f"pedido feito a {Nome}; ele trabalha na fila dele e a Mesa não "
                                         "espera. Peça aos outros donos agora e siga: feche com `resumo` "
                                         "dizendo quem faz o quê"}
            return {"ok": True, "tarefa": tarefa,
                    "proximo_passo": f"pedido feito a {Nome}. Se a tarefa precisa de outros colegas, "
                                     "peça a eles agora, nesta mesma volta, cada um com a sua parte: "
                                     "eles trabalham ao mesmo tempo. Depois termine o turno dizendo o que "
                                     "pediu; a sua tarefa espera todos e volta com as respostas juntas"}
        if acao == "acompanhar":
            tarefa_id = str(argumentos.get("tarefa_id") or "").strip()
            if not tarefa_id:
                return {"ok": False, "erro": "`acompanhar` precisa de `tarefa_id`"}
            achada = await _cliente.tarefa(tarefa_id)
            # Resposta que o residente já leu aqui não volta de novo no fim do turno.
            if (minha is not None and achada.get("pai") == minha.id
                    and achada.get("estado") in _tarefas.TERMINADAS):
                _tarefas.marcar_entregue(tarefa_id)
            if minha is not None and achada.get("pai") == minha.id \
                    and achada.get("estado") in _tarefas.ABERTAS:
                Nome = str(achada.get("agente") or "")[:1].upper() + str(achada.get("agente") or "")[1:]
                espera = (f" {Nome} espera a autorização da pessoa para `{achada.get('pendente')}`; "
                          f"a autorização é dela e só ela dá." if achada.get("pendente") else "")
                return {"ok": True, "tarefa": achada,
                        "proximo_passo": f"ainda não terminou.{espera} Termine o turno: a sua tarefa "
                                         f"volta com a resposta de {Nome} quando ele acabar"}
            return {"ok": True, "tarefa": achada}
    except (_m.ManifestoInvalido, _cliente.HQIndisponivel) as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": False, "erro": f"ação '{acao}' não existe: use listar, pedir ou acompanhar"}


def _memoria(argumentos: Dict[str, Any]) -> Dict[str, Any]:
    from . import memoria as _lembrancas
    from .escopo import agente_do_turno

    agente = agente_do_turno()
    if agente is None:
        return {"ok": False, "erro": "só um agente residente tem memória própria"}
    acao = str(argumentos.get("acao") or "ler").strip().lower()
    if acao == "anotar":
        nota = str(argumentos.get("nota") or "").strip()[:500]
        if not nota:
            return {"ok": False, "erro": "`anotar` precisa de `nota`"}
        trocada = _lembrancas.anotar(agente.nome, nota)
        return {"ok": True, "anotado": nota, **({"trocou": trocada} if trocada else {})}
    if acao == "buscar":
        termo = str(argumentos.get("termo") or "").strip()
        if not termo:
            return {"ok": False, "erro": "`buscar` precisa de `termo`"}
        return {"ok": True, "notas": _lembrancas.buscar(agente.nome, termo)}
    if acao == "ler":
        todas = _lembrancas.notas(agente.nome)
        return {"ok": True, "notas": todas[-_lembrancas.QUANTAS_AO_LER:], "total": len(todas)}
    return {"ok": False, "erro": f"ação '{acao}' não existe: use anotar, buscar ou ler"}


def _pedir_ferramenta(argumentos: Dict[str, Any], state: Any) -> Dict[str, Any]:
    from ..exec.contrato import CodigoDeErro
    from ..exec.politica import avaliar
    from . import registro as _registro
    from . import tarefas as _tarefas
    from .escopo import agente_do_turno, nome_visivel, tarefa_do_turno

    agente = agente_do_turno()
    if agente is None:
        return {"ok": False, "erro": "só um agente residente pede ferramenta"}
    nome = str(argumentos.get("ferramenta") or "").strip()
    porque = str(argumentos.get("motivo") or "").strip()[:300]
    if not nome or not porque:
        return {"ok": False, "erro": "`pedir_ferramenta` precisa de `ferramenta` e `motivo`"}
    if nome in agente.ferramentas:
        return {"ok": True, "ferramenta": nome, "ja_tinha": True}
    if nome not in _m._ferramentas_conhecidas():
        return {"ok": False, "erro": f"'{nome}' não existe; `search_tools` mostra as que existem"}
    if nome in _m._proibidas():
        return {"ok": False, "erro": f"'{nome}' não é dada a residente"}

    comando = _tarefas.PEDIDO_DE_FERRAMENTA + nome
    tarefa = tarefa_do_turno()
    liberacao = _tarefas.ultima_liberacao(tarefa) if tarefa is not None else None
    if liberacao and liberacao.get("negado") == comando:
        return {"ok": False, "negado": True,
                "erro": f"a pessoa não liberou {nome}; siga sem ela e diga na resposta o que faltou"}

    sessao = str(getattr(state, "session_id", "") or "")
    decisao = avaliar(comando, sessao, checar_alvo=False, na_hora=True)
    if not decisao.get("permitido"):
        base = {"ok": False, "executado": False, "fase": "permissao", "chave": "pedir_ferramenta",
                "motivo": f"{nome_visivel(agente)} quer a ferramenta {nome}: {porque}",
                "comando": comando, "ferramenta_pedida": nome}
        if decisao.get("precisa_perguntar"):
            return {**base, "precisa_permissao": True, "so_desta_vez": True,
                    "codigo_erro": CodigoDeErro.PRECISA_PERMISSAO}
        return {**base, "recusado": True, "motivo": str(decisao.get("motivo") or ""),
                "codigo_erro": CodigoDeErro.RECUSADO_POLITICA}
    try:
        _registro.liberar_ferramenta(agente.nome, nome)
    except _m.ManifestoInvalido as exc:
        return {"ok": False, "erro": str(exc)}
    # O manifesto do turno é o mesmo objeto: a ferramenta vale já na próxima chamada.
    agente.ferramentas.append(nome)
    return {"ok": True, "ferramenta": nome, "proximo_passo": f"`{nome}` está liberada; pode usar"}


def _falar_na_mesa(argumentos: Dict[str, Any]) -> Dict[str, Any]:
    from . import mesa as _mesa
    from .escopo import agente_do_turno, tarefa_do_turno

    agente, tarefa = agente_do_turno(), tarefa_do_turno()
    assunto_id = _mesa.de_origem(getattr(tarefa, "origem", "") or "")
    if agente is None or not assunto_id:
        return {"ok": False, "erro": "só se fala na Mesa na sua vez de um assunto; para começar "
                                     "uma conversa, use `abrir_assunto`"}
    assunto = _mesa.carregar(assunto_id)
    if assunto is None or assunto.estado != _mesa.ABERTO:
        return {"ok": False, "erro": "o assunto já foi fechado; termine o turno"}
    resumo = str(argumentos.get("resumo") or "").strip()
    if not resumo and _mesa.agiu_nesta_vez(assunto, agente.nome, getattr(tarefa, "criada_em", 0.0)):
        return {"ok": False, "erro": "você já falou nesta vez; termine o turno e espere a próxima"}
    try:
        # Fecha quem tem a vez de fechar, ou quem media e viu o acordo fechado.
        pode_fechar = assunto.fechando or (tarefa is not None and assunto.mediacao == tarefa.id)
        if resumo and pode_fechar and _mesa.quem_fecha(assunto) == agente.nome:
            _mesa.fechar(assunto_id, resumo, por=agente.nome)
            return {"ok": True, "resposta": resumo, "proximo_passo": "assunto fechado; termine o turno"}
        if resumo and not argumentos.get("texto"):
            # Resumo fora da vez de fechar entra como a fala dele: é o que ele quis dizer.
            argumentos = {**argumentos, "texto": resumo}
        if argumentos.get("passar"):
            _mesa.passar(assunto_id, agente.nome)
        else:
            _mesa.falar(assunto_id, agente.nome, str(argumentos.get("texto") or ""),
                        str(argumentos.get("para") or ""), reabre=False)
    except _mesa.AssuntoInvalido as exc:
        return {"ok": False, "erro": str(exc)}
    fala = "Passei a vez." if argumentos.get("passar") else str(argumentos.get("texto") or "")
    return {"ok": True, "resposta": fala, "proximo_passo": "termine o turno; a vez passa ao próximo"}


async def _abrir_assunto(argumentos: Dict[str, Any]) -> Dict[str, Any]:
    from .escopo import agente_do_turno

    agente = agente_do_turno()
    if agente is None:
        return {"ok": False, "erro": "só um residente abre assunto por aqui"}
    try:
        assunto = await _cliente.abrir_assunto(str(argumentos.get("titulo") or ""),
                                               str(argumentos.get("texto") or ""), agente.nome)
    except (_m.ManifestoInvalido, _cliente.HQIndisponivel) as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": True, "assunto": assunto,
            "proximo_passo": "o assunto está aberto e os colegas vão falar na vez deles; siga a sua "
                             "tarefa, o resumo chega à sua memória quando fechar"}


def _decisao(argumentos: Dict[str, Any], state: Any) -> Dict[str, Any]:
    from ..memory import decisoes
    from .escopo import agente_do_turno

    agente = agente_do_turno()
    acao = str(argumentos.get("acao") or "").strip().lower()
    if acao == "buscar":
        termo = str(argumentos.get("termo") or "").strip()
        achadas = decisoes.buscar(termo, agente=agente.nome if agente else "")
        return {"ok": True, "decisoes": achadas,
                **({} if achadas else {"aviso": "nenhuma decisão parecida; tente outras palavras do tema"})}
    if acao == "anotar":
        titulo = str(argumentos.get("titulo") or "").strip()
        texto = str(argumentos.get("decisao") or "").strip()
        if not titulo or not texto:
            return {"ok": False, "erro": "`anotar` precisa de `titulo` e `decisao`"}
        quem = [str(p).strip().lower() for p in argumentos.get("participantes") or [] if str(p).strip()]
        if agente and agente.nome not in quem:
            quem.append(agente.nome)
        sessao = str(getattr(state, "session_id", "") or "")
        origem = f"agente:{agente.nome}" if agente else f"conversa:{sessao}"
        caminho = decisoes.registrar(f"{origem}:{decisoes.agora_id()}", titulo, texto, quem)
        return {"ok": True, "arquivo": str(caminho),
                "proximo_passo": "decisão registrada; ela chega no contexto de quem participou"}
    return {"ok": False, "erro": f"ação '{acao}' não existe: use anotar ou buscar"}


async def executar(ferramenta: str, argumentos: Dict[str, Any], state: Any) -> Dict[str, Any]:
    if ferramenta == "decisao":
        return _decisao(argumentos, state)
    if ferramenta == "falar_na_mesa":
        return _falar_na_mesa(argumentos)
    if ferramenta == "abrir_assunto":
        return await _abrir_assunto(argumentos)
    if ferramenta == "criar_agente":
        return await _criar(argumentos, state)
    if ferramenta == "pedir_ao_agente":
        return await _pedir(argumentos)
    if ferramenta == "pedir_ferramenta":
        return _pedir_ferramenta(argumentos, state)
    return _memoria(argumentos)


NOMES = ("criar_agente", "pedir_ao_agente", "memoria_do_agente", "pedir_ferramenta", "falar_na_mesa",
         "abrir_assunto", "decisao")
