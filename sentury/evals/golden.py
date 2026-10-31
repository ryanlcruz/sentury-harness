"""Evals "golden" do Sentury: cenários ponta-a-ponta que afirmam as GARANTIAS
visíveis ao usuário: diferente dos unit tests, rodam o orquestrador inteiro
(planner roteado deterministicamente) e checam o comportamento final.

Rode standalone:  python -m sentury.evals

São determinísticos (sem chamar LLM real), então servem de rede de regressão em
CI. As evals de ROTEAMENTO com LLM de verdade (pergunta → ferramenta esperada)
ficam em `routing.py` e só rodam quando há GROQ_API_KEY.
"""
import json
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, List, Optional, Tuple

from ..config import settings
from ..harness.orchestrator import SenturyOrchestrator
from ..harness.state import AnalysisState
from ..memory.session_store import InMemorySessionStore
from ..memory.user_memory import get_user_memory_store
from ..domains.escopo import usar_setor


def _setor_de_eval():
    from ..domains.registry import DOMAIN_REGISTRY, get_active_domain

    ativo = get_active_domain()
    if ativo.analise_de_base:
        return ativo.name
    return next(
        (p.name for p in DOMAIN_REGISTRY.values() if p.analise_de_base), ativo.name,
    )


def _eval_no_setor(caso):
    """Isola a execução num pacote disponível sem alterar a escolha da instalação."""

    @wraps(caso)
    async def isolada():
        with usar_setor(_setor_de_eval()):
            return await caso()

    isolada.requer_analise = True
    return isolada


@dataclass
class EvalResult:
    nome: str
    ok: bool
    detalhe: str = ""


class _Scripted:
    """Planner que devolve, em ordem, as ações roteadas (simula a decisão da LLM
    de forma determinística para a eval)."""

    last_model = "scripted"

    def __init__(self, acoes: List[str]):
        self._acoes = list(acoes)

    async def complete(self, messages):
        return self._acoes.pop(0) if self._acoes else json.dumps({"action": "respond", "message": "fim"})


class _Echo:
    last_model = "echo"

    def __init__(self, message: str = "Resumo final."):
        self._message = message

    async def complete(self, messages):
        return json.dumps({"action": "respond", "message": self._message})


def _tool(tool: str, **args) -> str:
    return json.dumps({"action": "tool_call", "tool": tool, "arguments": args})


def _say(msg: str) -> str:
    return json.dumps({"action": "respond", "message": msg})


def _store():
    from ..data.store import _base_do_setor

    return _base_do_setor(settings)


def _orch(planner, responder=None, memory=None) -> SenturyOrchestrator:
    return SenturyOrchestrator(planner=planner, responder=responder or _Echo(), store=_store(), memory=memory)


@_eval_no_setor
async def _eval_root_cause_global() -> EvalResult:
    """Causa raiz global roda liberada e não pede para tentar de novo."""
    from ..domains.do_setor import ferramenta_de_causa

    orch = _orch(_Scripted([_tool(ferramenta_de_causa()), _say("pronto")]))
    r = await orch.handle_message(AnalysisState.new("s", "u"), "me traz a causa raiz")
    ok = r["harness"]["harness_allowed"] is True and "tentar de novo" not in r["message"]
    return EvalResult("root_cause global não quebra", ok, r["message"][:60])


@_eval_no_setor
async def _eval_export_pdf_deterministico() -> EvalResult:
    """Export em PDF confirma e anexa o arquivo."""
    from ..domains.do_setor import analise_de_base

    orch = _orch(_Scripted([_tool(analise_de_base()), _tool("export_pdf")]))
    r = await orch.handle_message(AnalysisState.new("s", "u"), "gera um pdf da consulta")
    anexo = r.get("attachment") or {}
    # O arquivo fica na pasta de entregas e quem responde é o modelo, sem frase pronta.
    ok = anexo.get("type") == "pdf" and bool(anexo.get("caminho")) and "Pronto" not in r["message"]
    return EvalResult("export PDF vai para a pasta de entregas e o modelo responde", ok, r["message"][:60])


@_eval_no_setor
async def _eval_grounding_sem_moeda() -> EvalResult:
    """Valor sem lastro na resposta vem com o aviso de que não tem origem."""
    orch = _orch(_Scripted([_say("Economia de R$ 100.000,00/mês.")]))
    r = await orch.handle_message(AnalysisState.new("s", "u"), "quanto eu economizo?")
    # Apagar custava uma chamada de modelo por resposta e ainda podia levar
    # junto valor COM lastro. Agora o numero fica e o aviso vai anexado: quem
    # vai usar o valor e quem precisa saber que ele nao tem origem.
    ok = "R$ 100.000,00" in r["message"] and "Não encontrei lastro" in r["message"]
    return EvalResult("grounding avisa sobre valor inventado", ok, r["message"][:60])


def _entrega(resultado: dict) -> str:
    """Tudo que chega ao usuário: a mensagem mais o conteúdo do anexo.

    A garantia é sobre o que é ENTREGUE, não sobre onde. Quando o plano
    passou a sair como artefato, a eval que só lia `message` acusou falha
    sem que nada tivesse quebrado: checar a entrega inteira não tem esse
    ponto cego.
    """
    partes = [str(resultado.get("message") or "")]
    anexo = resultado.get("attachment") or {}
    conteudo = anexo.get("content")
    if isinstance(conteudo, str):
        partes.append(conteudo)
    elif anexo.get("content_base64"):
        import base64

        try:
            partes.append(base64.b64decode(anexo["content_base64"]).decode("utf-8", "replace"))
        except Exception:
            pass
    return "\n".join(partes)


@_eval_no_setor
async def _eval_memoria_aprende_e_recupera() -> EvalResult:
    """O que o modelo guarda numa conversa chega ao contexto da seguinte."""
    import tempfile

    mem = get_user_memory_store(InMemorySessionStore(), raiz=tempfile.mkdtemp(prefix="sentury-eval-memoria-"))
    orch = _orch(_Scripted([_tool("memoria", acao="salvar", fato="prefere tabelas para comparar opções"),
                            _say("ok")]), memory=mem)
    await orch.handle_message(AnalysisState.new("sA", "pessoa"), "prefiro tabelas para comparar opções")
    memorias = await mem.all("pessoa")
    contexto = await orch._contexto_do_turno(AnalysisState.new("sB", "pessoa"), {"artifact_plan": None})
    ok = any("tabelas" in m["texto"].lower() for m in memorias) and "tabelas" in str(contexto).lower()
    return EvalResult("memória guardada pelo modelo volta na conversa seguinte", ok,
                      str([m["texto"] for m in memorias]))


_CASES: List[Callable[[], Any]] = [
    _eval_root_cause_global,
    _eval_export_pdf_deterministico,
    _eval_grounding_sem_moeda,
    _eval_memoria_aprende_e_recupera,
]


def casos_do_setor(setor: str) -> List[Callable[[], Any]]:
    """As evals que valem para o setor: as do motor (sem `setor`) e as dele."""
    from ..domains.registry import DOMAIN_REGISTRY

    pacote = DOMAIN_REGISTRY.get(setor)
    return [
        caso for caso in _CASES
        if (bool(pacote and pacote.analise_de_base) if getattr(caso, "requer_analise", False)
            else getattr(caso, "setor", "") in ("", setor))
    ]


async def run_golden_evals(casos: Optional[List[Callable[[], Any]]] = None) -> List[EvalResult]:
    resultados = []
    for caso in (_CASES if casos is None else casos):
        try:
            resultados.append(await caso())
        except Exception as exc:  # uma eval que explode é falha, não crash do runner
            resultados.append(EvalResult(caso.__name__, False, f"exceção: {exc}"))
    return resultados
