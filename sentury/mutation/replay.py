"""Repetir turnos que já aconteceram, contra a baseline e contra a candidata.

Evita a armadilha do "parece melhor no exemplo que acabamos de inventar": um
caso escrito depois de ver o defeito costuma favorecer a solução que já se tem
em mente. Turno histórico não tem esse viés: ele aconteceu antes de existir
a ideia da mutação.

**A gravação inclui as respostas do LLM.** Sem isso, repetir o turno chamaria o
modelo de novo, e a resposta viria diferente por conta própria: não daria para
saber se a diferença observada veio do código alterado ou do modelo variando.
Com as respostas gravadas, baseline e candidata veem exatamente a mesma coisa,
e o que sobra de diferença é o que a mutação fez.

Isso tem um limite que precisa estar escrito: **mutação que altera o prompt não
pode ser medida por replay determinístico**, porque ali a resposta do modelo
*deveria* mudar. Esse caso exige rodada ao vivo, repetida, e é mais cara e mais
ruidosa. O registro do traço diz qual modo ele suporta.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Um traço serve para desenvolver, para avaliar, ou fica guardado sem ser usado
# em nenhuma das duas: este último é o que impede a mutação de se ajustar ao
# próprio gabarito.
CONJUNTOS = ("desenvolvimento", "avaliacao", "holdout")


@dataclass
class Traco:
    """Um turno que aconteceu, com o bastante para acontecer de novo igual."""

    id: str
    mensagem: str
    historico: List[Dict[str, Any]] = field(default_factory=list)
    # Cada item e um registro `{texto, tool_calls, modelo, provedor, ms}`. Uma
    # string tambem vale, e vira `{"texto": ...}`, traco escrito a mao nao
    # precisa saber de tool_calls.
    respostas_llm: List[Any] = field(default_factory=list)
    resultado_esperado: Dict[str, Any] = field(default_factory=dict)
    conjunto: str = "avaliacao"
    origem: str = ""              # sessão de onde veio, quando veio de uma real
    determinista: bool = True     # falso quando o traço depende de rede/relógio
    gravado_em: float = 0.0
    # O estado inteiro de antes do turno, nao so o historico: `tarefa_pendente`
    # dispara a retomada, `filtros` muda a consulta e `funcoes_ativas` muda
    # quais ferramentas existem.
    estado_inicial: Dict[str, Any] = field(default_factory=dict)
    # Esforco, modo, dominio, flags e commit. Sem isto, baseline e candidata
    # podem diferir por ambiente e a diferenca e creditada ao codigo.
    ambiente: Dict[str, Any] = field(default_factory=dict)
    # O que o turno de fato produziu. `resultado_esperado` e para caso escrito
    # a mao; este e para comparar contra a propria producao.
    resultado_observado: Dict[str, Any] = field(default_factory=dict)
    # O que cada ferramenta que age no mundo devolveu, em ordem
    # (`{tool, argumentos, resultado}` ou `{tool, argumentos, erro}`). E o que
    # deixa repetir um turno de navegador ou computador sem agir de novo.
    resultados_ferramentas: List[Dict[str, Any]] = field(default_factory=list)

    def para_dict(self) -> Dict[str, Any]:
        return asdict(self)


def pasta() -> Path:
    escolhido = os.environ.get("SENTURY_TRACOS_DIR")
    if escolhido:
        return Path(escolhido).expanduser()
    # Fora do repositorio: o traco e a conversa em texto puro, e o padrao
    # antigo (`sentury/mutation/tracos/`) punha isso dentro da arvore de
    # trabalho, sem uma linha no `.gitignore`, com dois agentes commitando.
    return Path(os.environ.get("SENTURY_HOME") or (Path.home() / ".sentury")) / "tracos"


def _caminho(traco_id: str) -> Path:
    return pasta() / f"{traco_id}.json"


def normalizar_respostas(respostas: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Aceita texto puro ou registro, devolve sempre registro.

    Traco escrito a mao passa string; o gravador do turno passa o que a cadeia
    coletou, com `tool_calls` junto.
    """
    saida: List[Dict[str, Any]] = []
    for item in (respostas or []):
        if isinstance(item, dict):
            saida.append(dict(item))
        else:
            saida.append({"texto": "" if item is None else str(item)})
    return saida


def gravar(
    *,
    mensagem: str,
    historico: Optional[List[Dict[str, Any]]] = None,
    respostas_llm: Optional[List[Any]] = None,
    resultado_esperado: Optional[Dict[str, Any]] = None,
    conjunto: str = "avaliacao",
    origem: str = "",
    determinista: bool = True,
    traco_id: str = "",
    estado_inicial: Optional[Dict[str, Any]] = None,
    ambiente: Optional[Dict[str, Any]] = None,
    resultado_observado: Optional[Dict[str, Any]] = None,
    resultados_ferramentas: Optional[List[Dict[str, Any]]] = None,
) -> Traco:
    if conjunto not in CONJUNTOS:
        raise ValueError(f"conjunto deve ser um de {', '.join(CONJUNTOS)}")
    if not (mensagem or "").strip():
        raise ValueError("traco precisa da mensagem que iniciou o turno")

    traco = Traco(
        id=(traco_id or f"T-{uuid.uuid4().hex[:8]}"),
        mensagem=mensagem.strip(),
        historico=list(historico or []),
        respostas_llm=normalizar_respostas(respostas_llm),
        resultado_esperado=dict(resultado_esperado or {}),
        conjunto=conjunto,
        origem=origem,
        determinista=determinista,
        gravado_em=time.time(),
        estado_inicial=dict(estado_inicial or {}),
        ambiente=dict(ambiente or {}),
        resultado_observado=dict(resultado_observado or {}),
        resultados_ferramentas=list(resultados_ferramentas or []),
    )
    destino = _caminho(traco.id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(json.dumps(traco.para_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(destino)
    return traco


def carregar(traco_id: str) -> Optional[Traco]:
    caminho = _caminho(str(traco_id or "").strip())
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Traco ilegivel (%s): %s", caminho, exc)
        return None
    conhecidos = {c for c in Traco.__dataclass_fields__}
    return Traco(**{k: v for k, v in dados.items() if k in conhecidos})


def _arquivos_do_mais_novo() -> List[Path]:
    """Os arquivos de traco, do mais novo para o mais velho, sem abrir nenhum.

    A data do arquivo basta para ordenar: o traco e escrito uma vez, e so
    `separar_holdout` reescreve: o que o deixa mais novo, e isso nao muda o
    que a poda faz, porque ela nao toca holdout.
    """
    if not pasta().is_dir():
        return []
    datados = []
    for arquivo in pasta().glob("*.json"):
        try:
            datados.append((arquivo.stat().st_mtime, arquivo))
        except OSError:
            continue
    return [a for _, a in sorted(datados, key=lambda par: par[0], reverse=True)]


def listar(conjunto: str = "", limite: int = 0) -> List[Traco]:
    """Os tracos, do mais velho para o mais novo.

    Com `limite`, abre so os N mais recentes daquele conjunto em vez de ler o
    diretorio inteiro para a memoria: com o corpus crescendo turno a turno,
    ler tudo para usar os ultimos vinte era o custo que so aumentava.
    """
    achados: List[Traco] = []
    for arquivo in _arquivos_do_mais_novo():
        traco = carregar(arquivo.stem)
        if traco is None or (conjunto and traco.conjunto != conjunto):
            continue
        achados.append(traco)
        if limite > 0 and len(achados) >= limite:
            break
    return sorted(achados, key=lambda t: t.gravado_em)


# O que a poda pode apagar. `avaliacao` e `holdout` sao curados a mao ou pelo
# `separar_holdout`: apagar ali mudaria a bateria que julga o mutation, e dois
# resultados deixariam de ser comparaveis.
_PODAVEIS = ("desenvolvimento",)
_MARCA_DA_PODA = ".ultima_poda"
_PODA_NO_MAXIMO_A_CADA_S = 24 * 3600


def podar(
    maximo: Optional[int] = None,
    dias: Optional[int] = None,
    *,
    agora: Optional[float] = None,
) -> Dict[str, int]:
    """Apaga traco de desenvolvimento velho demais ou alem do teto.

    Dois criterios, porque sao dois problemas: o teto e o disco e o custo de
    listar; o prazo e o dado pessoal: o traco guarda a conversa inteira, e
    guardar para sempre nao foi decisao de ninguem.
    """
    from ..config import settings

    maximo = int(maximo if maximo is not None else getattr(settings, "SENTURY_TRACOS_MAXIMO", 500))
    dias = int(dias if dias is not None else getattr(settings, "SENTURY_TRACOS_DIAS", 30))
    agora = time.time() if agora is None else agora
    corte = agora - dias * 86400 if dias > 0 else None

    mantidos = apagados_por_idade = apagados_por_teto = 0
    for arquivo in _arquivos_do_mais_novo():
        traco = carregar(arquivo.stem)
        if traco is None or traco.conjunto not in _PODAVEIS:
            continue
        motivo = ""
        if corte is not None and (traco.gravado_em or 0) < corte:
            motivo = "idade"
        elif maximo > 0 and mantidos >= maximo:
            motivo = "teto"
        if not motivo:
            mantidos += 1
            continue
        try:
            arquivo.unlink()
        except OSError as exc:
            logger.warning("Nao consegui apagar o traco %s: %s", arquivo.name, exc)
            continue
        if motivo == "idade":
            apagados_por_idade += 1
        else:
            apagados_por_teto += 1

    try:
        (pasta() / _MARCA_DA_PODA).write_text(str(agora), encoding="utf-8")
    except OSError:
        pass
    return {"mantidos": mantidos, "por_idade": apagados_por_idade, "por_teto": apagados_por_teto}


def podar_se_preciso(*, agora: Optional[float] = None) -> Optional[Dict[str, int]]:
    """Chamado depois de cada gravacao; poda de verdade raramente.

    O que custa aqui por turno e uma listagem de diretorio e um `stat`. A poda
    completa abre os tracos, entao roda so quando o teto estourou ou quando a
    ultima faz mais de um dia: sem a segunda condicao, o prazo nunca venceria
    num corpus que fica abaixo do teto.
    """
    from ..config import settings

    if not pasta().is_dir():
        return None
    agora = time.time() if agora is None else agora
    maximo = int(getattr(settings, "SENTURY_TRACOS_MAXIMO", 500))
    try:
        ultima = float((pasta() / _MARCA_DA_PODA).read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        ultima = 0.0
    passou_do_teto = maximo > 0 and sum(1 for _ in pasta().glob("*.json")) > maximo
    if not passou_do_teto and agora - ultima < _PODA_NO_MAXIMO_A_CADA_S:
        return None
    return podar(agora=agora)


class LlmGravado:
    """Devolve, em ordem, o que o modelo respondeu quando o turno aconteceu.

    Acabando as respostas gravadas, ele **falha** em vez de inventar. Um replay
    que continua com resposta improvisada mede outra coisa e não avisa.

    Devolve o texto E repoe `last_tool_calls`, porque em modo nativo a resposta
    do modelo nao esta na string: ela esta no canal lateral. Um dublê que so
    devolve texto repete um turno nativo como "o modelo nao pediu ferramenta
    nenhuma": e a mutação mediria o vazio.
    """

    def __init__(self, respostas: List[Any], nativo: Optional[bool] = None):
        self._fila = normalizar_respostas(respostas)
        self.consumidas = 0
        self.faltou = False
        self.last_model = "replay"
        self.last_provider = "replay"
        self.last_usage = None
        self.last_tool_calls = None
        self.last_reasoning_summary = None
        # Um turno que usou ferramenta nativa so repete igual se o dublê também
        # se declarar capaz: senão o harness cai no planner de texto e mede
        # outro caminho. A marca gravada vale mais que a inferência: num turno
        # nativo em que o modelo falhou não sobra chamada para inferir.
        self.supports_tools = nativo if nativo is not None else any(
            r.get("tool_calls") for r in self._fila)

    async def complete(self, messages, *args, **kwargs):
        if not self._fila:
            self.faltou = True
            raise RuntimeError("replay pediu mais respostas do que o traco gravou")
        self.consumidas += 1
        registro = self._fila.pop(0)
        if registro.get("erro") is not None:
            # Na produção esta chamada falhou: repetir com a mesma falha leva o
            # turno pelo mesmo caminho (a frase de erro, a troca por tamanho).
            from robinbandit.chain import FalhaDaCadeia

            raise FalhaDaCadeia(str(registro["erro"]), list(registro.get("tipos") or []))
        self.last_tool_calls = registro.get("tool_calls")
        self.last_model = registro.get("modelo") or "replay"
        self.last_provider = registro.get("provedor") or "replay"
        self.last_usage = registro.get("uso")
        return registro.get("texto") or ""



async def repetir(traco: Traco, construir_orquestrador) -> Dict[str, Any]:
    """Roda o turno de novo. `construir_orquestrador(planner, responder)` monta
    a versão que se quer medir: baseline ou candidata."""
    from ..harness.state import AnalysisState
    from ..harness.gravacao_do_turno import (
        EM_REPLAY, REPLAY_BLOQUEIOS, REPLAY_FERRAMENTAS, FilaDeResultados, observar, sem_resultado_gravado,
    )

    # Acao no mundo sem resultado gravado agiria de novo. Recuse antes ate de
    # construir o runtime.
    ferramentas = (traco.resultado_observado or {}).get("ferramentas") or []
    nao_aprovadas = sem_resultado_gravado(ferramentas, traco.resultados_ferramentas)
    if nao_aprovadas:
        return {"ok": False, "traco": traco.id,
                "erro": ("replay recusou ferramenta sem leitura aprovada nem resultado gravado: "
                         f"{', '.join(nao_aprovadas)}"),
                "ferramentas_bloqueadas": nao_aprovadas}

    # Uma fila só, compartilhada. A ordem verdadeira e a da cadeia, e planner,
    # responder, classificador e compactacao se revezam nela; dar uma fila
    # para cada um faria a segunda chamada do planner consumir a resposta que
    # era do responder.
    despacho = (traco.ambiente or {}).get("despacho")
    gravado = LlmGravado(traco.respostas_llm,
                         nativo=None if despacho is None else despacho == "passo_unico")
    planner = responder = gravado
    orquestrador = construir_orquestrador(planner, responder)

    # O estado inteiro quando existe; historico sozinho e o formato antigo.
    if traco.estado_inicial:
        estado = AnalysisState.from_dict(dict(traco.estado_inicial))
        estado.session_id = f"replay-{traco.id}"
    else:
        estado = AnalysisState.new(f"replay-{traco.id}", "replay")
        estado.history = [dict(m) for m in traco.historico]

    # Sem esta marca, cada rodada de mutacao grava copias de si mesma e o
    # corpus vira eco do proprio replay.
    _marca = EM_REPLAY.set(True)
    bloqueios: List[str] = []
    _marca_bloqueios = REPLAY_BLOQUEIOS.set(bloqueios)
    fila = FilaDeResultados(traco.resultados_ferramentas)
    _marca_fila = REPLAY_FERRAMENTAS.set(fila)
    # Sem a pasta da produção, um caminho que lá era da pasta de trabalho cai
    # fora das liberadas aqui, e o turno toma outro caminho.
    from ..tools.arquivos import PASTA_FIXADA

    _marca_pasta = PASTA_FIXADA.set(str((traco.ambiente or {}).get("pasta_de_trabalho") or ""))
    inicio = time.time()
    try:
        resultado = await orquestrador.handle_message(estado, traco.mensagem)
    except Exception as exc:
        return {
            "ok": False, "traco": traco.id, "erro": f"{type(exc).__name__}: {exc}",
            "respostas_faltaram": planner.faltou,
        }
    finally:
        PASTA_FIXADA.reset(_marca_pasta)
        REPLAY_FERRAMENTAS.reset(_marca_fila)
        REPLAY_BLOQUEIOS.reset(_marca_bloqueios)
        EM_REPLAY.reset(_marca)
    if bloqueios:
        return {"ok": False, "traco": traco.id,
                "erro": ("replay recusou ferramenta sem leitura aprovada nem resultado gravado: "
                         f"{', '.join(bloqueios)}"),
                "ferramentas_bloqueadas": bloqueios,
                # Pedido que existe no traço com outros argumentos: o código de
                # hoje pediu outra coisa ao mundo.
                "divergencias": list(fila.divergencias)}
    return {
        "ok": True,
        "traco": traco.id,
        "ms": int((time.time() - inicio) * 1000),
        # A mesma leitura que a gravacao fez na producao; ver `observar`.
        **observar(resultado),
        "respostas_consumidas": planner.consumidas,
        # Resposta gravada que sobrou e sinal de que o replay tomou outro
        # caminho e chamou o modelo menos vezes do que a producao chamou.
        "respostas_sobraram": len(gravado._fila),
        # Acao no mundo servida do traco, e a gravada que ninguem pediu: o
        # codigo de hoje agiu menos vezes que a producao.
        "ferramentas_servidas": fila.servidos,
        "resultados_sobraram": fila.sobraram,
        # E o contrario: o codigo de hoje quis mais uma volta do modelo. O
        # orquestrador engole a falha e responde com a frase de erro, entao sem
        # esta marca a bateria so veria "mensagem diferente".
        "respostas_faltaram": gravado.faltou,
        # Escritas que o turno tentou nas dependencias (ver `mutation.efeitos`).
        "efeitos_recusados": list(getattr(orquestrador, "efeitos_recusados", None) or []),
    }


def comparar(baseline: Dict[str, Any], candidata: Dict[str, Any]) -> Dict[str, Any]:
    """O que mudou entre as duas execuções do mesmo turno.

    Não decide se ficou melhor: só diz o que ficou diferente. Julgar é do
    fitness, e misturar as duas coisas aqui esconderia o critério.
    """
    if not baseline.get("ok") or not candidata.get("ok"):
        return {
            "comparavel": False,
            "motivo": "uma das execucoes falhou",
            "baseline_ok": baseline.get("ok"), "candidata_ok": candidata.get("ok"),
            "erro_baseline": baseline.get("erro", ""), "erro_candidata": candidata.get("erro", ""),
        }

    msg_igual = baseline.get("mensagem") == candidata.get("mensagem")
    # `None` e "este lado nao sabe" (traco de antes do formato 2): a
    # comparacao de ferramentas fica de fora em vez de acusar mudanca.
    sem_lista = baseline.get("ferramentas") is None or candidata.get("ferramentas") is None
    tools_base = list(baseline.get("ferramentas") or [])
    tools_cand = list(candidata.get("ferramentas") or [])
    tools_iguais = None if sem_lista else tools_base == tools_cand
    anexo_igual = baseline.get("anexo") == candidata.get("anexo")
    return {
        "comparavel": True,
        "traco": baseline.get("traco"),
        "mensagem_igual": msg_igual,
        "ferramentas_iguais": tools_iguais,
        "ferramentas_baseline": tools_base,
        "ferramentas_candidata": tools_cand,
        "anexo_igual": anexo_igual,
        "delta_ms": (candidata.get("ms") or 0) - (baseline.get("ms") or 0),
        "mudou": not (msg_igual and tools_iguais is not False and anexo_igual)
                 or bool(baseline.get("respostas_faltaram") or candidata.get("respostas_faltaram")),
    }


def producao(traco: Traco) -> Dict[str, Any]:
    """O que o turno produziu quando aconteceu, na forma de uma execucao.

    Comparar replay com replay prova so que o replay e estavel: duas rodadas
    consumindo a mesma fila podem errar igual. A prova de que ele e FIEL e
    repetir e bater com a producao.
    """
    if not traco.resultado_observado:
        return {"ok": False, "traco": traco.id,
                "erro": "traco sem resultado_observado: foi escrito a mao, nao gravado"}
    from ..harness.gravacao_do_turno import FORMATO_DO_OBSERVADO

    observado = dict(traco.resultado_observado)
    if (traco.ambiente or {}).get("formato_do_observado", 1) < FORMATO_DO_OBSERVADO:
        # Gravado quando a lista de ferramentas saia sempre vazia: `[]` ali nao
        # quer dizer "nao rodou nada", quer dizer "nao sei".
        observado["ferramentas"] = None
    return {"ok": True, "traco": traco.id, **observado}


async def contra_producao(traco: Traco, construir_orquestrador) -> Dict[str, Any]:
    """Repete o turno e compara com o que a producao produziu."""
    repetido = await repetir(traco, construir_orquestrador)
    diferenca = comparar(producao(traco), repetido)
    if repetido.get("ok") and repetido.get("respostas_sobraram"):
        # A mensagem pode ate sair igual; o caminho nao foi o mesmo.
        diferenca["mudou"] = True
        diferenca["respostas_sobraram"] = repetido["respostas_sobraram"]
    if repetido.get("ok") and repetido.get("resultados_sobraram"):
        # Resultado gravado que ninguem pediu: o codigo de hoje agiu menos.
        diferenca["mudou"] = True
        diferenca["resultados_sobraram"] = repetido["resultados_sobraram"]
    if repetido.get("ok") and repetido.get("respostas_faltaram"):
        # Mensagem de erro igual não prova fidelidade quando a chamada falta.
        diferenca["respostas_faltaram"] = True
    if repetido.get("ferramentas_bloqueadas"):
        diferenca["ferramentas_bloqueadas"] = repetido["ferramentas_bloqueadas"]
    if repetido.get("divergencias"):
        diferenca["divergencias"] = repetido["divergencias"]
    if repetido.get("efeitos_recusados"):
        # Nao muda o veredito: a producao tambem escreveu. So diz o que foi barrado.
        diferenca["efeitos_recusados"] = repetido["efeitos_recusados"]
    if diferenca.get("comparavel"):
        diferenca["motivos"] = _motivos(diferenca)
    return diferenca


def _motivos(diferenca: Dict[str, Any]) -> List[str]:
    """Por que o turno mudou, em palavras: quem lê a bateria decide pelo motivo."""
    motivos = []
    if not diferenca.get("mudou"):
        return motivos
    if diferenca.get("respostas_faltaram"):
        motivos.append("o replay pediu uma resposta do modelo que não está gravada")
    if diferenca.get("respostas_sobraram"):
        motivos.append("o codigo de hoje chamou o modelo menos vezes do que a producao")
    if diferenca.get("resultados_sobraram"):
        motivos.append("o codigo de hoje agiu no mundo menos vezes do que a producao")
    if diferenca.get("ferramentas_iguais") is False:
        motivos.append("ferramentas diferentes")
    if not diferenca.get("anexo_igual", True):
        motivos.append("anexo diferente")
    if not diferenca.get("mensagem_igual", True) and not motivos:
        motivos.append("mesmo caminho, mensagem diferente")
    return motivos


FORMATO_ANTIGO = "formato antigo: gravado sem o despacho do turno"


async def bateria(
    construir_orquestrador,
    conjunto: str = "desenvolvimento",
    *,
    limite: int = 0,
) -> Dict[str, Any]:
    """Repete os tracos gravados de um conjunto contra a propria producao.

    Com o codigo de hoje, o esperado e `mudou: false` em todos os tracos
    deterministas: e isso que diz que o replay serve de regua. Os que mudarem
    sao, eles mesmos, o achado: ou o traco nao repete, ou o codigo mudou desde
    a gravacao, e as duas coisas precisam ser sabidas antes de ligar o mutation.
    """
    from ..harness.gravacao_do_turno import sem_resultado_gravado

    selecionados = listar(conjunto, limite=limite)
    candidatos, fora = [], []
    for traco in selecionados:
        motivo = "não determinista" if not traco.determinista else ""
        if not motivo and not traco.resultado_observado:
            motivo = "sem resultado observado"
        # Sem o despacho, o replay não sabe se o turno foi nativo ou em texto, e a
        # gravação dessa época nem sempre guardava todas as respostas do modelo:
        # repetir mede o palpite, não o código.
        if not motivo and not (traco.ambiente or {}).get("despacho"):
            motivo = FORMATO_ANTIGO
        if motivo:
            fora.append({"traco": traco.id, "motivo": motivo})
        else:
            candidatos.append(traco)
    # Traço marcado determinista pode ter agido no mundo sem o resultado
    # gravado. Repetir ali agiria de novo, e contar como falha esconderia as
    # falhas de verdade.
    tracos, pulados = [], []
    for traco in candidatos:
        com_efeito = sem_resultado_gravado(traco.resultado_observado.get("ferramentas") or [],
                                           traco.resultados_ferramentas)
        if com_efeito:
            pulados.append({"traco": traco.id, "ferramentas": com_efeito})
        else:
            tracos.append(traco)
    iguais, mudaram, falharam, efeitos = [], [], [], []
    for traco in tracos:
        diferenca = await contra_producao(traco, construir_orquestrador)
        if diferenca.get("efeitos_recusados"):
            efeitos.append({"traco": traco.id, "efeitos": diferenca["efeitos_recusados"]})
        if diferenca.get("ferramentas_bloqueadas") and traco.resultados_ferramentas:
            # O traço tem o que o mundo devolveu e o codigo de hoje pediu outra
            # coisa: isso e mudanca de comportamento, nao traço que nao repete.
            mudaram.append({"traco": traco.id, "mudou": True, "divergencias": diferenca.get("divergencias", []),
                            "motivos": ["o codigo de hoje pediu ao mundo o que a producao nao pediu"]})
        elif diferenca.get("ferramentas_bloqueadas"):
            # Traço de formato antigo nao lista o que rodou: so o replay descobre.
            pulados.append({"traco": traco.id, "ferramentas": diferenca["ferramentas_bloqueadas"]})
        elif not diferenca.get("comparavel"):
            falharam.append({"traco": traco.id, "erro": diferenca.get("erro_candidata", "")})
        elif diferenca.get("mudou"):
            mudaram.append(diferenca)
        else:
            iguais.append(traco.id)
    return {
        "conjunto": conjunto,
        "selecionados": len(selecionados),
        "fora_da_bateria": fora,
        "tracos": len(tracos),
        "repetidos": len(iguais) + len(mudaram) + len(falharam),
        "iguais": len(iguais),
        "mudaram": mudaram,
        "falharam": falharam,
        "pulados": pulados,
        "efeitos_recusados": efeitos,
        "fiel": bool(iguais) and not mudaram and not falharam,
    }


def salvar(traco: Traco) -> None:
    """Regrava o traço no lugar, depois de mudar conjunto ou rótulo."""
    _caminho(traco.id).write_text(
        json.dumps(traco.para_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def separar_holdout(proporcao: float = 0.3) -> Dict[str, int]:
    """Move parte dos traços de avaliação para holdout.

    Sem um conjunto que a mutação nunca viu, ela pode ser ajustada até passar
    exatamente nos casos que a motivaram: e passar ali não diz nada sobre o
    resto.
    """
    candidatos = listar("avaliacao")
    quantos = int(len(candidatos) * max(0.0, min(1.0, proporcao)))
    movidos = 0
    # Determinístico: os mais antigos viram holdout. Sorteio faria a mesma
    # bateria mudar de composição entre execuções, e aí duas medições não se
    # comparam.
    for traco in candidatos[:quantos]:
        traco.conjunto = "holdout"
        salvar(traco)
        movidos += 1
    return {"movidos": movidos, "avaliacao": len(candidatos) - movidos}


__all__ = [
    "CONJUNTOS", "LlmGravado", "Traco", "bateria", "carregar", "comparar",
    "contra_producao", "gravar", "listar", "pasta", "podar", "podar_se_preciso",
    "producao", "repetir", "salvar", "separar_holdout",
]
