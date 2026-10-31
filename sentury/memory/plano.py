"""Persiste planos legíveis e acompanha a execução entre sessões.

O checklist fica em Markdown para edição humana; tentativas e resultados ficam
num estado local separado para não sujar o repositório. A ferramenta de status
mantém as tarefas atualizadas enquanto o agente trabalha.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

# `- [ ] 1. Titulo` / `- [x] 2.1 Outro` / `- [ ]* 3. Opcional`
# `!` marca um portão que impede avanço até a decisão; `[-]` preserva tarefas
# em andamento no parser do checklist.
_ITEM = re.compile(r"^(\s*)- \[([ xX-])\]([*!]?)\s*(.+?)\s*$")
_CAIXINHA = re.compile(r"- \[[ xX-]\]")


def _marca(tarefa: "Tarefa") -> str:
    """O que vai dentro da caixinha: `x` feito, `-` em andamento, espaco o resto."""
    if tarefa.feito:
        return "x"
    return "-" if tarefa.estado == "fazendo" else " "
# `_Requisitos: Componente 1, interface_` no fim do bloco de um item
_REQUISITO = re.compile(r"^\s*_[Rr]equisitos?:\s*(.+?)_\s*$")
# A agenda no plano liga o passo recorrente à retomada do trabalho.
_AGENDA = re.compile(r"^\s*_[Aa]genda:\s*(.+?)_\s*$")
# `- opcao: sim, pode subir` sob um portao. Portao sem opcao e uma pergunta
# aberta no meio da execucao, e quem responde tem que adivinhar o que vale.
_OPCAO = re.compile(r"^\s*-\s*op[cç][aã]o:\s*(.+?)\s*$", re.IGNORECASE)

ESTADOS = ("pendente", "fazendo", "feito", "falhou", "pulado")


def raiz_dos_planos(trabalho: Optional[Path] = None) -> Path:
    """Onde o plano legível mora: junto do trabalho, versionável."""
    from ..tools.arquivos import raiz_de_trabalho

    return (trabalho or raiz_de_trabalho()) / ".sentury" / "planos"


def _casa() -> Path:
    escolhida = os.environ.get("SENTURY_HOME")
    return Path(escolhida).expanduser() if escolhida else (Path.home() / ".sentury")


def _arquivo_de_estado(nome: str) -> Path:
    alvo = _casa() / "planos"
    alvo.mkdir(parents=True, exist_ok=True)
    return alvo / f"{_limpar(nome)}.json"


def _limpar(nome: str) -> str:
    limpo = "".join(c if c.isalnum() or c in "-_" else "-" for c in str(nome or "").strip().lower())
    return re.sub(r"-+", "-", limpo).strip("-")[:80] or "plano"


@dataclass
class Tarefa:
    """Um item do checklist.

    `id` é o número escrito no próprio arquivo (`2.1`), não uma posição: assim
    reordenar o Markdown não renumera o histórico de execução.
    """

    id: str
    titulo: str
    feito: bool = False
    opcional: bool = False
    # Portao: o plano nao passa daqui ate isto ser resolvido.
    gate: bool = False
    nivel: int = 0
    detalhes: List[str] = field(default_factory=list)
    requisitos: str = ""
    # So para portao: o que a pessoa pode responder.
    opcoes: List[str] = field(default_factory=list)
    # Cron ou intervalo, quando o passo se repete sozinho.
    agenda: str = ""
    estado: str = "pendente"
    tentativas: List[Dict[str, Any]] = field(default_factory=list)

    def como_linha(self) -> str:
        marca = _marca(self)
        sinal = "*" if self.opcional else ("!" if self.gate else "")
        return f"{'  ' * self.nivel}- [{marca}]{sinal} {self.id} {self.titulo}"

    def publico(self) -> Dict[str, Any]:
        return {
            "id": self.id, "titulo": self.titulo, "feito": self.feito,
            "opcional": self.opcional, "gate": self.gate, "estado": self.estado,
            "requisitos": self.requisitos, "tentativas": len(self.tentativas),
            # So aparecem quando existem: campo vazio em todo item vira ruido
            # no contexto que o modelo le a cada retomada.
            **({"opcoes": list(self.opcoes)} if self.opcoes else {}),
            **({"agenda": self.agenda} if self.agenda else {}),
        }


def ler(nome: str, trabalho: Optional[Path] = None) -> List[Tarefa]:
    """As tarefas do plano, com o estado de execução já costurado.

    O Markdown é a verdade sobre QUAIS tarefas existem; o JSON, sobre o que
    aconteceu com elas. Se alguém editar o checklist na mão, o item novo
    aparece: sem histórico, que é o correto.
    """
    alvo = raiz_dos_planos(trabalho) / _limpar(nome) / "tarefas.md"
    try:
        linhas = alvo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    estado = _ler_estado(nome)
    tarefas: List[Tarefa] = []
    for linha in linhas:
        achado = _ITEM.match(linha)
        if achado:
            recuo, marca, sinal, resto = achado.groups()
            numero, _, titulo = resto.partition(" ")
            if not re.match(r"^[\d.]+$", numero):
                numero, titulo = str(len(tarefas) + 1), resto
            tarefa = Tarefa(
                id=numero.rstrip("."), titulo=titulo.strip(),
                feito=marca.lower() == "x", opcional=sinal == "*",
                gate=sinal == "!", nivel=len(recuo) // 2,
            )
            guardado = estado.get(tarefa.id) or {}
            no_arquivo = "feito" if tarefa.feito else ("fazendo" if marca == "-" else "pendente")
            tarefa.estado = guardado.get("estado") or no_arquivo
            tarefa.tentativas = list(guardado.get("tentativas") or [])
            tarefas.append(tarefa)
            continue
        if not tarefas:
            continue
        requisito = _REQUISITO.match(linha)
        agenda = _AGENDA.match(linha)
        opcao = _OPCAO.match(linha)
        if requisito:
            tarefas[-1].requisitos = requisito.group(1).strip()
        elif agenda:
            tarefas[-1].agenda = agenda.group(1).strip()
        elif opcao and linha.startswith(" "):
            tarefas[-1].opcoes.append(opcao.group(1).strip())
        elif linha.strip().startswith("- ") and linha.startswith(" "):
            tarefas[-1].detalhes.append(linha.strip()[2:])
    return tarefas


def _ler_estado(nome: str) -> Dict[str, Any]:
    try:
        return json.loads(_arquivo_de_estado(nome).read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _gravar_estado(nome: str, dados: Dict[str, Any]) -> None:
    alvo = _arquivo_de_estado(nome)
    try:
        tmp = alvo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(alvo)
    except OSError as exc:
        logger.warning("Nao consegui gravar o estado do plano %s: %s", nome, exc)


def marcar(
    nome: str,
    tarefa_id: str,
    estado: str,
    *,
    session_id: str = "",
    nota: str = "",
    trabalho: Optional[Path] = None,
) -> Dict[str, Any]:
    """Marca uma tarefa, no JSON e no Markdown.

    Escrever nos dois é o ponto: o JSON guarda quem tentou e quando, e o
    Markdown continua legível para uma pessoa abrir e entender sem ferramenta.
    """
    if estado not in ESTADOS:
        return {"ok": False, "erro": f"estado deve ser um de {', '.join(ESTADOS)}"}

    with _LOCK:
        tarefas = ler(nome, trabalho)
        if not tarefas:
            return {"ok": False, "erro": f"plano '{nome}' nao existe ou nao tem tarefas"}
        alvo = next((t for t in tarefas if t.id == str(tarefa_id).strip()), None)
        if alvo is None:
            return {
                "ok": False,
                "erro": f"tarefa '{tarefa_id}' nao existe",
                "existentes": [t.id for t in tarefas][:20],
            }

        guardado = _ler_estado(nome)
        registro = guardado.setdefault(alvo.id, {"tentativas": []})
        registro["estado"] = estado
        registro["titulo"] = alvo.titulo
        # O historico e append-only: uma tentativa que falhou e evidencia, nao
        # lixo a ser sobrescrito pela seguinte.
        registro["tentativas"].append({
            "sessao": str(session_id or ""), "estado": estado,
            "em": time.time(), "nota": str(nota or "")[:300],
        })
        _gravar_estado(nome, guardado)

        alvo.feito = estado == "feito"
        alvo.estado = estado
        _reescrever_marcas(nome, tarefas, trabalho)

        restantes = [t for t in ler(nome, trabalho) if not t.feito and not t.opcional]
        # O Markdown conta o que falta; ele nao conta que um dia nao faltava
        # nada. Sem este registro, plano fechado que ganha tarefa nova fica
        # igual a plano que nunca terminou: e escopo que cresceu e informacao.
        if not restantes and "__fechado_em" not in guardado:
            guardado["__fechado_em"] = time.time()
            _gravar_estado(nome, guardado)

        return {
            "ok": True, "tarefa": alvo.publico(),
            "restantes": len(restantes),
            "proxima": restantes[0].publico() if restantes else None,
        }


def _reescrever_marcas(nome: str, tarefas: List[Tarefa], trabalho: Optional[Path] = None) -> None:
    """Atualiza só o `[ ]`/`[-]`/`[x]` das linhas, preservando o resto do arquivo.

    Reescrever o Markdown inteiro a partir das tarefas apagaria a prosa que
    alguém escreveu entre os itens: e essa prosa costuma ser o motivo.
    """
    alvo = raiz_dos_planos(trabalho) / _limpar(nome) / "tarefas.md"
    try:
        linhas = alvo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    por_id = {t.id: t for t in tarefas}
    saida, indice = [], 0
    for linha in linhas:
        achado = _ITEM.match(linha)
        if not achado:
            saida.append(linha)
            continue
        resto = achado.group(4)
        numero = resto.split(" ", 1)[0].rstrip(".")
        tarefa = por_id.get(numero) or (tarefas[indice] if indice < len(tarefas) else None)
        indice += 1
        if tarefa is None:
            saida.append(linha)
            continue
        saida.append(_CAIXINHA.sub(f"- [{_marca(tarefa)}]", linha, count=1))
    try:
        alvo.write_text("\n".join(saida) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Nao consegui reescrever %s: %s", alvo, exc)


def criar(
    nome: str,
    titulo: str,
    tarefas: List[str],
    *,
    contexto: str = "",
    trabalho: Optional[Path] = None,
) -> Dict[str, Any]:
    """Cria o plano. `tarefas` são linhas prontas do checklist."""
    pasta = raiz_dos_planos(trabalho) / _limpar(nome)
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        if contexto:
            (pasta / "contexto.md").write_text(
                f"# {titulo}\n\n{contexto.strip()}\n", encoding="utf-8",
            )
        # Linha que ja vem como item: ou como detalhe/requisito, que comeca
        # com `_` ou com `-` recuado: passa intacta; so texto solto vira item
        # novo. Numerar tudo transformaria a linha de requisitos numa tarefa.
        pronto, numero = [], 0
        for linha in tarefas:
            nua = linha.lstrip()
            if nua.startswith("- [") or nua.startswith("_") or (linha[:1].isspace() and nua.startswith("- ")):
                pronto.append(linha)
                continue
            numero += 1
            pronto.append(f"- [ ] {numero}. {linha}")
        corpo = "\n".join(pronto)
        (pasta / "tarefas.md").write_text(
            f"# {titulo}\n\n## Tarefas\n\n{corpo}\n", encoding="utf-8",
        )
    except OSError as exc:
        return {"ok": False, "erro": str(exc)}
    return {"ok": True, "plano": _limpar(nome), "caminho": str(pasta), "tarefas": len(ler(nome, trabalho))}


def listar(trabalho: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Os planos deste trabalho, com quanto falta em cada um."""
    raiz = raiz_dos_planos(trabalho)
    if not raiz.is_dir():
        return []
    saida = []
    for pasta in sorted(raiz.iterdir()):
        if not (pasta / "tarefas.md").is_file():
            continue
        tarefas = ler(pasta.name, trabalho)
        obrigatorias = [t for t in tarefas if not t.opcional]
        feitas = [t for t in obrigatorias if t.feito]
        saida.append({
            "plano": pasta.name,
            "tarefas": len(tarefas),
            "feitas": len(feitas),
            "faltam": len(obrigatorias) - len(feitas),
            "proxima": next((t.publico() for t in obrigatorias if not t.feito), None),
        })
    return saida


def ciclo(tarefas: List[Tarefa], ja_fechou: bool = False) -> Dict[str, Any]:
    """Em que pe o plano esta, derivado do checklist: nao guardado ao lado.

    Estado guardado em separado vira a segunda fonte de verdade que este modulo
    existe para evitar: bastaria alguem editar o Markdown na mao para o JSON
    passar a mentir. Aqui a pergunta e respondida lendo o que esta escrito.

    - `fechado`: nao falta obrigatoria nenhuma.
    - `travado`: a proxima obrigatoria e um portao ainda nao resolvido. Nada
      depois dele deve acontecer, e quem le precisa saber POR QUE parou.
    - `reaberto`: ja esteve fechado e voltou a ter trabalho.
    - `aberto`: ha trabalho e ele pode seguir.
    """
    obrigatorias = [t for t in tarefas if not t.opcional]
    pendentes = [t for t in obrigatorias if not t.feito]
    if not pendentes:
        return {"estado": "fechado", "travado_por": None}
    if pendentes[0].gate:
        return {"estado": "travado", "travado_por": pendentes[0].publico()}
    return {"estado": "reaberto" if ja_fechou else "aberto", "travado_por": None}


def resumo(nome: str, trabalho: Optional[Path] = None) -> Dict[str, Any]:
    """O plano inteiro, como o agente precisa ver para retomar."""
    tarefas = ler(nome, trabalho)
    if not tarefas:
        return {"ok": False, "erro": f"plano '{nome}' nao existe"}
    obrigatorias = [t for t in tarefas if not t.opcional]
    situacao = ciclo(tarefas, ja_fechou="__fechado_em" in _ler_estado(nome))
    # Com portao, `proxima` e o portao: apontar o passo seguinte seria convidar
    # o agente a pular a decisao que trava justamente para nao ser pulada.
    proxima = next((t.publico() for t in obrigatorias if not t.feito), None)
    return {
        "ok": True,
        "plano": _limpar(nome),
        "tarefas": [t.publico() for t in tarefas],
        "faltam": sum(1 for t in obrigatorias if not t.feito),
        "proxima": proxima,
        "estado": situacao["estado"],
        "travado_por": situacao["travado_por"],
        "contexto": _ler_contexto(nome, trabalho),
    }


def _ler_contexto(nome: str, trabalho: Optional[Path] = None) -> str:
    alvo = raiz_dos_planos(trabalho) / _limpar(nome) / "contexto.md"
    try:
        return alvo.read_text(encoding="utf-8")[:4000]
    except OSError:
        return ""


__all__ = ["ESTADOS", "Tarefa", "criar", "listar", "ler", "marcar", "raiz_dos_planos", "resumo"]


# Na terceira tentativa da mesma tarefa, insistir exige intervenção.
EMPERRADA_A_PARTIR_DE = 3


def telemetria(nome: str, trabalho: Optional[Path] = None) -> Dict[str, Any]:
    """Como este plano está indo: derivado do que já foi gravado.

    O `loop_stats` mede o TURNO; um workflow atravessa vários, e ninguém media
    isso. A pergunta que faltava resposta é a que decide se vale continuar:
    **há tarefa queimando tentativa sem sair do lugar?** Quatro falhas na mesma
    tarefa em três sessões não aparecem em lugar nenhum hoje: cada turno vê só
    a sua.

    Nada aqui é contado à parte: o histórico já é append-only por tarefa, com
    sessão e hora. Um contador paralelo seria a segunda fonte de verdade que
    este módulo existe para evitar.
    """
    tarefas = ler(nome, trabalho)
    if not tarefas:
        return {"ok": False, "erro": f"plano '{nome}' nao existe"}

    guardado = _ler_estado(nome)
    sessoes, tentativas, primeiro = set(), 0, None
    for tarefa in tarefas:
        for t in tarefa.tentativas:
            tentativas += 1
            if t.get("sessao"):
                sessoes.add(str(t["sessao"]))
            quando = t.get("em")
            if isinstance(quando, (int, float)) and (primeiro is None or quando < primeiro):
                primeiro = quando

    emperradas = [
        {"id": t.id, "titulo": t.titulo, "falhas": falhas}
        for t in tarefas
        for falhas in [sum(1 for x in t.tentativas if x.get("estado") == "falhou")]
        if falhas >= EMPERRADA_A_PARTIR_DE
    ]
    situacao = ciclo(tarefas, ja_fechou="__fechado_em" in guardado)
    return {
        "ok": True,
        "plano": _limpar(nome),
        "estado": situacao["estado"],
        "travado_por": situacao["travado_por"],
        "sessoes": len(sessoes),
        "tentativas": tentativas,
        "aberto_ha_s": round(time.time() - primeiro) if primeiro else 0,
        # Vazio na maioria dos planos, e e por isso que ele importa: quando tem
        # conteudo, e a unica coisa desta resposta que pede acao.
        "emperradas": emperradas,
    }
