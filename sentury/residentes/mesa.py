"""A Mesa: o lugar onde os residentes conversam sobre um assunto.

Um assunto tem título, quem abriu, participantes e falas. Cada fala é um turno
do residente, que chega pela fila como qualquer tarefa (origem `mesa:<id>`):
orçamento, pausa, cartão de autorização e pedido a colega valem igual. A
ordem de quem fala e os limites são do código, não do modelo:

- cada residente fala no máximo `TETO_DE_FALAS` vezes num assunto, e ganha
  uma fala a mais quando é chamado com @;
- num assunto com mais de dois, dois que só se respondem por `PINGUE_PONGUE`
  falas seguidas fecham o assunto (com dois só, o teto de falas já limita);
- quando todos os que ainda podem falar passam a vez, a rodada acaba: o assunto
  aberto por um residente fecha; no aberto pela pessoa, quem conduz media
  (sintetiza a divergência e chama quem discordou, fecha o acordo com os próximos
  passos, ou passa quando a conversa não pedia decisão), até `LIMITE_DE_MEDIACOES`
  vezes por rodada, e depois o assunto espera a próxima fala da pessoa.

Quem fecha escreve um resumo, que vai para a memória de quem participou.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from . import manifesto as _m

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

ABERTO = "aberto"
FECHADO = "fechado"
TETO_DE_FALAS = 3
PINGUE_PONGUE = 6
LIMITE_DE_MEDIACOES = 3
TETO_DO_TITULO = 200
TETO_DA_FALA = 2_000
ORIGEM = "mesa:"
PESSOA = "pessoa"

_MENCAO = re.compile(r"@([a-z][a-z0-9-]*)", re.IGNORECASE)

Decidir = Callable[[_m.Manifesto, "Assunto"], Awaitable[bool]]
_DECIDIR: Optional[Decidir] = None
_AO_FECHAR: List[Callable[["Assunto"], Any]] = []


class AssuntoInvalido(ValueError):
    pass


@dataclass
class Assunto:
    id: str
    titulo: str
    aberto_por: str  # "pessoa" ou o nome do residente
    texto: str = ""
    # Onde a pessoa abriu ("telegram:<chat>"), para o resumo voltar para lá.
    canal: str = ""
    participantes: List[str] = field(default_factory=list)
    # Consultados na abertura que não entraram: a tela mostra, e um @ depois os traz.
    ficaram_de_fora: List[str] = field(default_factory=list)
    falas: List[Dict[str, Any]] = field(default_factory=list)
    # Quem passou a vez desde a última fala de verdade.
    passaram: List[str] = field(default_factory=list)
    # Chamado com @ e ainda sem responder: tem a vez e uma fala a mais.
    chamados: List[str] = field(default_factory=list)
    estado: str = ABERTO
    # A vez de fechar com resumo já foi dada; `fechamento` é a tarefa dessa vez.
    fechando: bool = False
    fechamento: str = ""
    # Quem está nesta rodada: quem a pessoa chamou com @, e quem eles chamarem. Vazio é a mesa toda.
    rodada: List[str] = field(default_factory=list)
    # Mediações desta rodada, e a tarefa da que está em curso.
    mediacoes: int = 0
    mediacao: str = ""
    resumo: str = ""
    motivo: str = ""
    criado_em: float = 0.0
    atualizado_em: float = 0.0
    eventos: List[Dict[str, Any]] = field(default_factory=list)

    def falas_de(self, nome: str) -> int:
        # A fala da pessoa abre uma rodada nova: o teto de cada um recomeça dali.
        inicio = max((i + 1 for i, f in enumerate(self.falas) if f.get("de") == PESSOA), default=0)
        return sum(1 for f in self.falas[inicio:] if f.get("de") == nome)

    def publico(self) -> Dict[str, Any]:
        dados = asdict(self)
        dados.pop("eventos", None)
        return dados


def configurar(decidir: Optional[Decidir]) -> None:
    """A decisão de entrar num assunto: o `main` liga o modelo barato do Router."""
    global _DECIDIR
    _DECIDIR = decidir


def ao_fechar(funcao: Callable[["Assunto"], Any]) -> None:
    """Chamado quando um assunto fecha: é por aqui que o resumo volta ao canal."""
    if funcao not in _AO_FECHAR:
        _AO_FECHAR.append(funcao)


def _avisar_fechamento(assunto: "Assunto") -> None:
    for funcao in list(_AO_FECHAR):
        try:
            retorno = funcao(assunto)
            if asyncio.iscoroutine(retorno):
                em_segundo_plano(retorno)
        except Exception:
            logger.warning("Aviso de fechamento do assunto %s falhou.", assunto.id, exc_info=True)


def _pasta() -> Path:
    pasta = _m.casa() / "mesa"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _gravar(assunto: Assunto) -> Assunto:
    assunto.atualizado_em = time.time()
    alvo = _pasta() / f"{assunto.id}.json"
    tmp = alvo.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(assunto), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(alvo)
    return assunto


def _evento(assunto: Assunto, tipo: str, **dados: Any) -> None:
    assunto.eventos.append({"em": time.time(), "tipo": tipo, **dados})
    del assunto.eventos[:-200]


def carregar(assunto_id: str) -> Optional[Assunto]:
    limpo = "".join(c for c in str(assunto_id or "") if c.isalnum() or c in "-_")
    if not limpo:
        return None
    try:
        dados = json.loads((_pasta() / f"{limpo}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    conhecidos = set(Assunto.__dataclass_fields__)
    return Assunto(**{k: v for k, v in dados.items() if k in conhecidos})


def listar(estados: tuple = ()) -> List[Assunto]:
    achados = [carregar(a.stem) for a in _pasta().glob("*.json")]
    achados = [a for a in achados if a and (not estados or a.estado in estados)]
    return sorted(achados, key=lambda a: a.criado_em, reverse=True)


def agiu_nesta_vez(assunto: Assunto, nome: str, desde: float) -> bool:
    """O residente já falou, passou ou fechou desde o começo da vez dele."""
    return any(e.get("agente") == nome and e.get("em", 0) >= desde
               and e.get("tipo") in ("mesa_fala", "mesa_passou", "mesa_fechada")
               for e in assunto.eventos)


def fala_da_vez(assunto: Assunto, nome: str, desde: float, resposta: str = "",
                mediando: bool = False) -> Optional[str]:
    """O que a vez do residente pôs na conversa: a fala feita pela ferramenta, a resposta em
    texto quando ela conta como fala, ou None quando ele passou. Uma segunda fala sem ninguém
    ter chamado costuma ser recapitulação do que já se disse, e não entra."""
    if agiu_nesta_vez(assunto, nome, desde):
        return next((f["texto"] for f in reversed(assunto.falas)
                     if f.get("de") == nome and float(f.get("em") or 0) >= desde), None)
    resposta = str(resposta or "").strip()
    # Conta como fala a primeira dele na rodada, a resposta a quem o chamou com @ e a mediação.
    chamado = nome in assunto.chamados
    if resposta and (mediando or chamado or not assunto.falas_de(nome)) and pode_falar(assunto, nome):
        return resposta
    return None


def de_origem(origem: str) -> str:
    """O id do assunto numa origem de tarefa `mesa:<id>`, ou ""."""
    return origem[len(ORIGEM):] if str(origem or "").startswith(ORIGEM) else ""


def _ativos() -> Dict[str, _m.Manifesto]:
    from . import registro

    return {a.nome: a for a in registro.listar() if a.estado not in (_m.PAUSADO, _m.APOSENTADO)}


def _mencionados(texto: str, validos) -> List[str]:
    vistos: List[str] = []
    for nome in _MENCAO.findall(texto or ""):
        nome = nome.lower()
        if nome in validos and nome not in vistos:
            vistos.append(nome)
    return vistos


def abertos_hoje_por(nome: str) -> int:
    from .orcamento import inicio_do_dia

    desde = inicio_do_dia()
    return sum(1 for a in listar() if a.aberto_por == nome and a.criado_em >= desde)


def abrir(titulo: str, aberto_por: str = "pessoa", texto: str = "", canal: str = "") -> Assunto:
    """Abre o assunto e já põe nele quem foi chamado com @. Os outros decidem
    depois (`convidar`)."""
    titulo = str(titulo or "").strip()
    if not titulo:
        raise AssuntoInvalido("o assunto precisa de título")
    if len(titulo) > TETO_DO_TITULO:
        raise AssuntoInvalido(f"o título passa de {TETO_DO_TITULO} caracteres")
    texto = str(texto or "").strip()[:TETO_DA_FALA]
    ativos = _ativos()
    chamados = [n for n in _mencionados(f"{titulo} {texto}", ativos) if n != aberto_por]
    agora = time.time()
    assunto = Assunto(id=f"m{int(agora)}-{uuid.uuid4().hex[:6]}", titulo=titulo,
                      aberto_por=aberto_por, texto=texto, canal=str(canal or ""), criado_em=agora,
                      participantes=([aberto_por] if aberto_por in ativos else []) + chamados,
                      chamados=chamados)
    _evento(assunto, "mesa_aberta", agente=aberto_por, participantes=list(assunto.participantes),
            iniciativa=aberto_por != "pessoa")
    with _LOCK:
        return _gravar(assunto)


async def convidar(assunto_id: str) -> Assunto:
    """Sem @ na abertura, cada residente ativo que ainda não está no assunto decide
    se entra. Com @, quem abriu já disse quem quer: só os chamados ficam, e os
    outros entram se alguém os chamar numa fala."""
    assunto = carregar(assunto_id)
    if assunto is None or assunto.estado != ABERTO:
        raise AssuntoInvalido(f"não há assunto aberto '{assunto_id}'")
    if _DECIDIR is not None and not assunto.chamados:
        from . import orcamento

        candidatos = [(nome, agente) for nome, agente in _ativos().items()
                      if nome not in assunto.participantes and not orcamento.corte(agente)]

        async def decide(nome: str, agente: _m.Manifesto) -> bool:
            try:
                return bool(await _DECIDIR(agente, assunto))
            except Exception:
                logger.warning("A decisão de %s sobre o assunto %s falhou.", nome, assunto.id, exc_info=True)
                return False

        # Cada decisão é uma chamada ao modelo: em fila elas somavam segundos antes da primeira
        # fala. A ordem de entrada é a dos residentes, que é a ordem em que falam.
        entram = await asyncio.gather(*(decide(nome, agente) for nome, agente in candidatos))
        with _LOCK:
            assunto = carregar(assunto_id)
            for (nome, _agente), entra in zip(candidatos, entram):
                if entra and nome not in assunto.participantes:
                    assunto.participantes.append(nome)
                    _evento(assunto, "mesa_entrou", agente=nome)
                elif not entra and nome not in assunto.ficaram_de_fora:
                    assunto.ficaram_de_fora.append(nome)
                    _evento(assunto, "mesa_ficou_de_fora", agente=nome)
            _gravar(assunto)
    return carregar(assunto_id)


def _pingue_pongue(assunto: Assunto) -> bool:
    if len(assunto.participantes) <= 2:
        return False
    ultimas = [f.get("de") for f in assunto.falas[-PINGUE_PONGUE:]]
    if len(ultimas) < PINGUE_PONGUE or len(set(ultimas)) != 2:
        return False
    return all(a != b for a, b in zip(ultimas, ultimas[1:]))


def teto_de_falas(nome: str) -> int:
    from . import registro

    agente = registro.carregar(nome)
    return int((agente.autonomia if agente else {}).get("falas_por_assunto", TETO_DE_FALAS))


def pode_falar(assunto: Assunto, nome: str) -> bool:
    teto = teto_de_falas(nome) + (1 if nome in assunto.chamados else 0)
    return assunto.estado == ABERTO and nome in assunto.participantes and assunto.falas_de(nome) < teto


def falar(assunto_id: str, de: str, texto: str, para: str = "", reabre: bool = True) -> Assunto:
    """`reabre=False` registra a fala sem chamar os outros de volta: ela conta como a
    vez de quem falou e a rodada segue para quem ainda não falou."""
    texto = str(texto or "").strip()[:TETO_DA_FALA]
    if not texto:
        raise AssuntoInvalido("a fala está vazia")
    with _LOCK:
        assunto = carregar(assunto_id)
        pessoa = de == PESSOA
        # A pessoa retoma um assunto fechado falando nele: a conversa continua
        # na Mesa, sem precisar ir ao chat de cada residente.
        if assunto is not None and assunto.estado == FECHADO and pessoa:
            assunto.estado = ABERTO
            assunto.resumo = ""
            _evento(assunto, "mesa_reaberta", agente=PESSOA)
        if assunto is None or assunto.estado != ABERTO:
            raise AssuntoInvalido(f"não há assunto aberto '{assunto_id}'")
        if not pessoa and de not in assunto.participantes:
            assunto.participantes.append(de)
            assunto.ficaram_de_fora = [n for n in assunto.ficaram_de_fora if n != de]
        if not pessoa and not pode_falar(assunto, de):
            raise AssuntoInvalido(f"{de} já falou {assunto.falas_de(de)} vezes neste assunto")
        ativos = _ativos()
        para = str(para or "").strip().lower()
        mencionados = _mencionados(texto, ativos)
        if not para and mencionados:
            para = mencionados[0]
        assunto.falas.append({"de": de, "para": para, "texto": texto, "em": time.time()})
        if reabre:
            assunto.passaram = []
        elif de not in assunto.passaram:
            assunto.passaram.append(de)
        assunto.chamados = [n for n in assunto.chamados if n != de]
        for nome in mencionados:
            if nome != de and nome not in assunto.chamados:
                assunto.chamados.append(nome)
            if nome != de and nome not in assunto.participantes:
                assunto.participantes.append(nome)
                assunto.ficaram_de_fora = [n for n in assunto.ficaram_de_fora if n != nome]
            if assunto.rodada and nome not in assunto.rodada:
                assunto.rodada.append(nome)
        if pessoa:
            # A pessoa fala fora da conta de vez, e a fala dela reabre a rodada:
            # para quem ela chamou com @ ou, sem @, para a mesa toda.
            assunto.fechando = False
            assunto.motivo = ""
            assunto.mediacoes = 0
            assunto.mediacao = ""
            # Com @, a rodada é de quem ela chamou; sem @, da mesa toda.
            assunto.rodada = [n for n in mencionados if n != PESSOA]
            for nome in ([] if mencionados else assunto.participantes):
                if nome not in assunto.chamados:
                    assunto.chamados.append(nome)
        _evento(assunto, "mesa_fala", agente=de, para=para, texto=texto[:300])
        if _pingue_pongue(assunto):
            assunto.motivo = "dois só se respondiam enquanto os outros esperavam"
        return _gravar(assunto)


def passar(assunto_id: str, nome: str, motivo: str = "") -> Assunto:
    """`motivo` diz por que ele não falou quando não foi escolha dele (pausa, orçamento)."""
    with _LOCK:
        assunto = carregar(assunto_id)
        if assunto is None or assunto.estado != ABERTO:
            raise AssuntoInvalido(f"não há assunto aberto '{assunto_id}'")
        if nome not in assunto.passaram:
            assunto.passaram.append(nome)
        assunto.chamados = [n for n in assunto.chamados if n != nome]
        _evento(assunto, "mesa_passou", agente=nome, **({"motivo": motivo} if motivo else {}))
        return _gravar(assunto)


def proximo(assunto: Assunto) -> Optional[str]:
    """Quem fala agora, ou None quando ninguém mais tem o que dizer."""
    if assunto.estado != ABERTO or assunto.motivo:
        return None
    ultimo = assunto.falas[-1]["de"] if assunto.falas else ""
    for nome in assunto.chamados:
        if pode_falar(assunto, nome):
            return nome
    candidatos = [n for n in assunto.participantes
                  if n != ultimo and n not in assunto.passaram and pode_falar(assunto, n)
                  and (not assunto.rodada or n in assunto.rodada)]
    if not candidatos:
        return None
    # Quem falou menos primeiro; no empate, a ordem de entrada.
    return min(candidatos, key=lambda n: (assunto.falas_de(n), assunto.participantes.index(n)))


def quem_fecha(assunto: Assunto) -> Optional[str]:
    """Quem abriu fecha; se foi a pessoa, o primeiro participante que falou."""
    if assunto.aberto_por in assunto.participantes:
        return assunto.aberto_por
    return next((f["de"] for f in assunto.falas), None)


def marcar_fechando(assunto_id: str, tarefa_id: str = "") -> Optional[Assunto]:
    with _LOCK:
        assunto = carregar(assunto_id)
        if assunto is None or assunto.estado != ABERTO:
            return None
        assunto.fechando = True
        assunto.fechamento = tarefa_id
        return _gravar(assunto)


def houve_conversa(assunto: Assunto) -> bool:
    """Dois ou mais residentes conversaram desde a última fala da pessoa: há o que mediar.
    A resposta de um só a quem ela chamou não pede mediador."""
    inicio = max((i + 1 for i, f in enumerate(assunto.falas) if f.get("de") == PESSOA), default=0)
    return len({f.get("de") for f in assunto.falas[inicio:] if f.get("de") != PESSOA}) >= 2


def marcar_mediando(assunto_id: str, nome: str, tarefa_id: str) -> Optional[Assunto]:
    """A vez de mediar foi dada; quem media ganha uma fala a mais, como quem é chamado."""
    with _LOCK:
        assunto = carregar(assunto_id)
        if assunto is None or assunto.estado != ABERTO:
            return None
        assunto.mediacoes += 1
        assunto.mediacao = tarefa_id
        if nome not in assunto.chamados:
            assunto.chamados.append(nome)
        return _gravar(assunto)


def encerrar_mediacao(assunto_id: str) -> Optional[Assunto]:
    """Quem media passou: não há o que decidir nesta rodada, a vez volta à pessoa."""
    with _LOCK:
        assunto = carregar(assunto_id)
        if assunto is None:
            return None
        assunto.mediacoes = LIMITE_DE_MEDIACOES
        assunto.mediacao = ""
        return _gravar(assunto)


def esperar_a_pessoa(assunto_id: str) -> Optional[Assunto]:
    """A rodada acabou num assunto da pessoa: fica aberto, à espera dela."""
    with _LOCK:
        assunto = carregar(assunto_id)
        if assunto is None or assunto.estado != ABERTO:
            return None
        if not (assunto.eventos and assunto.eventos[-1].get("tipo") == "mesa_sua_vez"):
            _evento(assunto, "mesa_sua_vez", agente=PESSOA)
            _gravar(assunto)
        return assunto


def apagar(assunto_id: str) -> Optional[Assunto]:
    """Tira o assunto da Mesa. Devolve o que foi apagado, ou None se não existia."""
    with _LOCK:
        assunto = carregar(assunto_id)
        if assunto is None:
            return None
        (_pasta() / f"{assunto.id}.json").unlink(missing_ok=True)
        return assunto


def fechar(assunto_id: str, resumo: str, por: str = "") -> Assunto:
    from . import registro

    with _LOCK:
        assunto = carregar(assunto_id)
        if assunto is None:
            raise AssuntoInvalido(f"não existe assunto '{assunto_id}'")
        if assunto.estado == FECHADO:
            return assunto
        assunto.estado = FECHADO
        assunto.resumo = str(resumo or "").strip()[:TETO_DA_FALA]
        _evento(assunto, "mesa_fechada", agente=por or assunto.aberto_por, resumo=assunto.resumo[:300],
                motivo=assunto.motivo)
        _gravar(assunto)
    _avisar_fechamento(assunto)
    if assunto.resumo:
        for nome in {f["de"] for f in assunto.falas}:
            try:
                # Reaberto e fechado de novo, o assunto troca a nota antiga em vez de somar outra.
                registro.anotar_memoria(nome, f"Mesa, '{assunto.titulo}': {assunto.resumo}"[:500],
                                        substitui=f"Mesa, '{assunto.titulo}':")
            except Exception:
                logger.warning("Não consegui anotar o resumo na memória de %s.", nome, exc_info=True)
        # A memória é de cada um e o turno recebe só parte dela; a decisão fica para a equipe toda
        # e para o Sentury principal, que a recebem no contexto dos próximos turnos.
        try:
            from ..memory import decisoes

            decisoes.registrar(f"{ORIGEM}{assunto.id}", assunto.titulo, assunto.resumo,
                               [f["de"] for f in assunto.falas if f["de"] != PESSOA])
        except Exception:
            logger.warning("Não consegui registrar a decisão do assunto %s.", assunto.id, exc_info=True)
    return assunto


def pedido_da_fala(assunto: Assunto, nome: str, fechando: bool = False, mediando: bool = False) -> str:
    """O que o residente lê no turno da fala: o assunto e a conversa até aqui."""
    linhas = [f"Assunto na Mesa: {assunto.titulo}"]
    if assunto.texto:
        linhas.append(assunto.texto)
    linhas.append(f"Aberto por: {'a pessoa' if assunto.aberto_por == 'pessoa' else assunto.aberto_por}. "
                  f"Participantes: {', '.join(assunto.participantes)}.")
    if assunto.falas:
        linhas += ["", "Conversa até aqui:"]
        for f in assunto.falas[-20:]:
            alvo = f" para {f['para']}" if f.get("para") else ""
            linhas.append(f"- {f['de']}{alvo}: {f['texto']}")
    # O que a pessoa disse por último é o que esta rodada responde; no meio de vinte falas,
    # o modelo tende a continuar o assunto anterior (inclusive um consenso já fechado).
    ultima = next((f["texto"] for f in reversed(assunto.falas) if f.get("de") == PESSOA), "")
    if ultima and not fechando:
        linhas += ["", f"A pessoa acabou de dizer: \"{ultima}\". Esta rodada responde a isso; o que já "
                       "foi decidido antes só entra se ajudar a responder."]
    linhas.append("")
    if fechando:
        linhas.append("A conversa terminou. Feche o assunto com `falar_na_mesa` e `resumo`: o que se "
                      "concluiu e o que ficou pendente, em poucas linhas.")
    elif mediando:
        linhas.append(
            "A rodada acabou e você conduz esta mesa. A Mesa existe para a equipe decidir e o trabalho "
            "andar; leia o que se disse desde a última mensagem da pessoa e escolha uma saída. Se ficou "
            "divergência que impede decidir, proponha em duas ou três frases uma síntese que resolva e "
            "chame com @ quem discordou, para aceitar ou ajustar. Se a mesa chegou a um acordo, peça a cada "
            "dono os próximos passos com `pedir_ao_agente` e feche com `falar_na_mesa` e `resumo`: o que "
            "se decidiu, quem faz o quê e o que ficou pendente; o resumo vira decisão registrada. Se a "
            "conversa não pedia decisão (apresentação, opinião, pergunta), use `falar_na_mesa` com "
            "`passar: true` e a vez volta para a pessoa.")
    else:
        restam = teto_de_falas(nome) + (1 if nome in assunto.chamados else 0) - assunto.falas_de(nome)
        if assunto.falas_de(nome):
            quem = next((f["de"] for f in reversed(assunto.falas)
                         if nome in _mencionados(f.get("texto", ""), {nome: True}) or f.get("para") == nome), "")
            linhas.append(
                f"{quem.capitalize() if quem else 'Um colega'} chamou você. Responda a ele em duas ou três "
                "frases: aceite, ajuste ou discorde dizendo o porquê, sem repetir o que já disse. Para trazer "
                "outro colega, escreva @nome. Se não tem o que acrescentar, use `falar_na_mesa` com "
                "`passar: true`.")
            return "\n".join(linhas)
        linhas.append(
            f"É a sua vez de falar (até {restam} fala(s) nesta rodada). Isto é uma conversa da equipe, e "
            "quem acompanha quer conhecer cada um: fale do seu jeito, na primeira pessoa, reagindo ao que "
            "acabou de ser dito, em duas ou três frases, como numa conversa. Concordar, discordar dizendo "
            "o porquê, perguntar a um colega ou trazer o que só a sua especialidade vê são boas falas. "
            "Repetir o que um colega já disse, ou cumprimentar quem já foi cumprimentado, não acrescenta: "
            "se você concorda com quem já respondeu e não tem nada diferente, passe a vez; quem acompanha "
            "prefere menos falas, cada uma com algo novo. "
            "Cada um fala uma vez por rodada; para ouvir a resposta de um colega, escreva @nome e ele "
            "ganha a vez. A sua resposta em texto aparece na conversa exatamente como você escrever. Se "
            "não tem o que dizer agora, use `falar_na_mesa` com `passar: true`.")
    return "\n".join(linhas)


def eventos_recentes(desde: float = 0.0, limite: int = 60) -> List[Dict[str, Any]]:
    """Os eventos da Mesa no formato do feed das tarefas."""
    achados: List[Dict[str, Any]] = []
    for arquivo in _pasta().glob("*.json"):
        assunto = carregar(arquivo.stem)
        if assunto is None or assunto.atualizado_em <= desde:
            continue
        for evento in assunto.eventos:
            if float(evento.get("em") or 0) <= desde:
                continue
            achados.append({**evento, "agente": evento.get("agente") or "", "tarefa": assunto.id,
                            "assunto": assunto.id, "pedido": assunto.titulo[:160],
                            "origem": f"{ORIGEM}{assunto.id}"})
    achados.sort(key=lambda e: e["em"], reverse=True)
    return achados[:max(1, int(limite or 1))]


def em_segundo_plano(coro: Awaitable[Any]) -> None:
    """Agenda no loop que estiver rodando; fora de loop (script, teste síncrono), descarta."""
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
