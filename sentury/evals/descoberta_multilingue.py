"""Bancada de descoberta: contrato local e escolha por LLM são medidas distintas.

    python -m sentury.evals.descoberta_multilingue
    python -m sentury.evals.descoberta_multilingue --live --provider chatgpt_codex --model gpt-5.5 --limite 4

Sem --live, confere apenas acesso à capacidade e carregamento do schema. Com
--live, roda o harness sobre um arquivo temporário cujo código só pode ser
conhecido depois da leitura. Não modifica configuração persistida ou sessões
do usuário. O suporte do adapter a tools é informado no relatório.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import inspect
import os
import time
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..domains.escopo import usar_setor
from ..harness import descoberta
from ..harness.state import AnalysisState


@dataclass(frozen=True)
class Caso:
    idioma: str
    pedido: str
    ferramenta: str = "ler_arquivo"


CASOS = (
    Caso("pt", "Leia resumo.txt e me diga o código de leitura que está nele."),
    Caso("en", "Read resumo.txt and tell me the reading code inside it."),
    Caso("zh", "请读取 resumo.txt 并告诉我其中的阅读代码。"),
    Caso("zh+Python", "请用 Python 读取 resumo.txt 并告诉我其中的阅读代码。"),
    Caso("es", "Lee resumo.txt y dime el código de lectura que contiene."),
    Caso("ar", "اقرأ resumo.txt وأخبرني برمز القراءة الموجود فيه."),
    Caso("ru", "Прочитай resumo.txt и сообщи код чтения из файла."),
    Caso("ja", "resumo.txt を読んで、その中の読み取りコードを教えてください。"),
    Caso("pt-informal", "le o resumo.txt ai e me fala q codigo ta la"),
    Caso("misto", "看看 resumo.txt and me fala o código que tá lá."),
    Caso("zh-chat", "我想和你聊聊，你今天怎么样？", ""),
    Caso("en-chat", "I'd like to talk with you. How are you today?", ""),
    Caso("pt-negacao", "Não abra o computador nem monte workflow. Só converse comigo.", ""),
    Caso("zh-negacao", "不要操作电脑，也不要创建工作流。只和我聊天。", ""),
)


def medir_acesso(casos=CASOS) -> list[dict[str, Any]]:
    resultados = []
    with usar_setor("generalista"):
        for caso in casos:
            token = descoberta.abrir()
            try:
                state = AnalysisState.new("eval-descoberta", "eval")
                matches, _, mapa, _ = descoberta.preparar(state, caso.pedido, [])
                esperada = caso.ferramenta
                resultado = descoberta.consultar(state, {"nomes": [esperada]}) if esperada else {}
                schemas = [s["function"]["name"] for s in resultado.get("schemas", [])]
                resultados.append({"idioma": caso.idioma,
                                   "recall_lexical": esperada in {m["name"] for m in matches} if esperada else None,
                                   "acesso": f"`{esperada}`" in mapa and esperada in schemas if esperada else None,
                                   "manifesto_chars": len(mapa)})
            finally:
                descoberta.fechar(token)
    return resultados


class _Medido:
    def __init__(self, provider):
        self.provider = provider
        self.supports_tools = getattr(provider, "supports_tools", False)
        self.chamadas: list[dict[str, Any]] = []
        self.retornos: list[str] = []

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def __setattr__(self, name, value):
        if name.startswith("last_"):
            setattr(self.provider, name, value)
        else:
            object.__setattr__(self, name, value)

    async def complete(self, messages, tools=None, **kwargs):
        inicio = time.monotonic()
        parametros = inspect.signature(self.provider.complete).parameters
        extras = {**kwargs, "tools": tools, "reasoning_effort": "low"}
        if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parametros.values()):
            extras = {name: value for name, value in extras.items() if name in parametros}
        texto = await self.provider.complete(messages, **extras)
        from ..llm.action_parser import extract_plain_text

        self.retornos.append(extract_plain_text(str(texto or ""))[:2000])
        self.chamadas.append({"ms": round((time.monotonic() - inicio) * 1000),
                              "schemas_enviados": len(tools or []) if self.supports_tools else 0,
                              "contexto_chars": sum(len(str(m.get("content") or "")) for m in messages),
                              "tokens": getattr(self.provider, "last_usage", None)})
        return texto


async def medir_live(provider, casos=CASOS) -> list[dict[str, Any]]:
    from ..config import settings
    from ..harness.orchestrator import SenturyOrchestrator

    # O teto em zero liga a carga sob demanda, que é o que este eval mede.
    flags = {"SENTURY_NATIVE_TOOLS": True, "SENTURY_PROGRESSIVE_CAPABILITIES": True,
             "SENTURY_FERRAMENTAS_TETO_TOKENS": 0, "SENTURY_AGENT_LOOP": True,
             "SENTURY_GRAVAR_TRACOS": False}
    anteriores = {name: getattr(settings, name) for name in flags}
    workspace_anterior = os.environ.get("SENTURY_WORKSPACE")
    resultados = []
    try:
        for name, value in flags.items():
            setattr(settings, name, value)
        with TemporaryDirectory(prefix="sentury-descoberta-live-") as workspace, usar_setor("generalista"):
            os.environ["SENTURY_WORKSPACE"] = workspace
            for caso in casos:
                codigo = "LEITURA-" + uuid4().hex[:10]
                Path(workspace, "resumo.txt").write_text(f"Código de leitura: {codigo}\n", encoding="utf-8")
                medido = _Medido(provider)
                orq = SenturyOrchestrator(planner=medido, responder=medido, store=None)
                state = AnalysisState.new("eval-" + uuid4().hex, "eval-multilingue")
                inicio = time.monotonic()
                try:
                    resposta = await orq.handle_message(state, caso.pedido, effort="low")
                    tools = resposta.get("harness", {}).get("ferramentas", [])
                    texto = resposta.get("message", "")
                    resultado = {"idioma": caso.idioma, "modelo": getattr(provider, "last_model", None),
                                 "native_tools": medido.supports_tools, "ferramentas": tools,
                                 "escolha_esperada": caso.ferramenta in tools if caso.ferramenta else not tools,
                                 "concluiu": codigo in texto if caso.ferramenta else bool(texto) and not tools,
                                 "ms": round((time.monotonic() - inicio) * 1000),
                                 "chamadas": medido.chamadas, "erro": None}
                    if not resultado["concluiu"]:
                        resultado["diagnostico"] = {
                            "contrato_planner": orq.turno.contrato,
                            "retornos": medido.retornos,
                            "resposta": texto[:2000],
                        }
                except Exception as exc:
                    resultado = {"idioma": caso.idioma, "concluiu": False,
                                 "erro": f"{type(exc).__name__}: {exc}"[:300]}
                resultados.append(resultado)
    finally:
        for name, value in anteriores.items():
            setattr(settings, name, value)
        if workspace_anterior is None:
            os.environ.pop("SENTURY_WORKSPACE", None)
        else:
            os.environ["SENTURY_WORKSPACE"] = workspace_anterior
    return resultados


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--provider", default="chatgpt_codex")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--limite", type=int, default=len(CASOS))
    parser.add_argument("--idiomas", nargs="*", choices=[caso.idioma for caso in CASOS])
    args = parser.parse_args()
    casos = tuple(caso for caso in CASOS if args.idiomas is None or caso.idioma in args.idiomas)
    casos = casos[:max(0, args.limite)]
    if not args.live:
        resultados = medir_acesso(casos)
    else:
        from ..config import settings
        from .live_benchmark import _instantiate_provider

        provider = _instantiate_provider(settings, args.provider, args.model)
        resultados = asyncio.run(medir_live(provider, casos))
    print(json.dumps(resultados, ensure_ascii=False, indent=2))
    return int(any(r.get("erro") or r.get("acesso") is False or r.get("concluiu") is False for r in resultados))


if __name__ == "__main__":
    raise SystemExit(main())
