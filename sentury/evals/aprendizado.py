"""Bancada do aprendizado: a pausa de revisão guarda o que devia, e só isso.

    python -m sentury.evals.aprendizado
    python -m sentury.evals.aprendizado --live --provider chatgpt_codex --model gpt-5.5
    python -m sentury.evals.aprendizado --live --casos correcao_de_formato decisao_de_projeto

Os casos moram em `casos_de_aprendizado.yaml`. Com --live, cada caso roda a
revisão de verdade sobre a conversa, numa casa temporária; depois a bancada lê
o que foi escrito em skills e memória e confere com o esperado. Sem --live,
só confere que os casos carregam. Não toca a casa nem as skills da pessoa.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional

CASOS = Path(__file__).resolve().parent / "casos_de_aprendizado.yaml"


def carregar(caminho: Path = CASOS) -> List[Dict[str, Any]]:
    import yaml

    casos = yaml.safe_load(caminho.read_text(encoding="utf-8")) or []
    for caso in casos:
        if not caso.get("nome") or not caso.get("conversa"):
            raise ValueError(f"caso sem nome ou sem conversa: {caso!r}"[:200])
    return casos


def escritas(casa: Path) -> List[Dict[str, str]]:
    """Tudo o que a revisão deixou na casa: skills do usuário e memória."""
    saida = []
    for skill in sorted((casa / "skills").glob("*/SKILL.md")):
        anexos = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                           for p in skill.parent.rglob("*") if p.is_file() and p.name != "SKILL.md")
        saida.append({"tipo": "skill", "nome": skill.parent.name,
                      "texto": skill.read_text(encoding="utf-8", errors="replace") + anexos})
    for item in sorted((casa / "memoria").glob("*/*.md")):
        if item.name != "MEMORIA.md":
            saida.append({"tipo": "memoria", "nome": item.stem,
                          "texto": item.read_text(encoding="utf-8", errors="replace")})
    return saida


def _tem(texto: str, termos: List[str]) -> bool:
    texto = texto.lower()
    return any(str(t).lower() in texto for t in termos)


def julgar(caso: Dict[str, Any], feitas: List[Dict[str, str]]) -> Dict[str, Any]:
    """Confere o que foi escrito com o que o caso espera. Devolve ok e por quê."""
    espera = caso.get("espera") or {}
    motivos = []
    if espera.get("nada") and feitas:
        motivos.append("devia não guardar nada e guardou " + ", ".join(f"{e['tipo']}:{e['nome']}" for e in feitas))
    if espera.get("alguma") and not any(_tem(e["texto"], espera["alguma"]) for e in feitas):
        motivos.append(f"nenhuma escrita fala de {espera['alguma']}")
    if espera.get("memoria") and not any(e["tipo"] == "memoria" and _tem(e["texto"], espera["memoria"]) for e in feitas):
        motivos.append(f"a memória não guardou {espera['memoria']}")
    if espera.get("sobra_uma_de"):
        ficaram = [n for n in espera["sobra_uma_de"] if any(e["tipo"] == "skill" and e["nome"] == n for e in feitas)]
        if len(ficaram) != 1:
            motivos.append(f"das skills {espera['sobra_uma_de']} ficaram {ficaram or 'nenhuma'}")
    if espera.get("skill"):
        alvo = [e for e in feitas if e["tipo"] == "skill" and e["nome"] == espera["skill"]]
        if not alvo:
            motivos.append(f"a skill {espera['skill']} não foi corrigida")
        elif espera.get("skill_contem") and not _tem(alvo[0]["texto"], espera["skill_contem"]):
            motivos.append(f"a skill {espera['skill']} não ganhou {espera['skill_contem']}")
    proibidas = [e for e in feitas if _tem(e["texto"], caso.get("nao_pode") or [])]
    if proibidas:
        motivos.append(f"escreveu o que não podia ({caso['nao_pode']}) em "
                       + ", ".join(f"{e['tipo']}:{e['nome']}" for e in proibidas))
    return {"ok": not motivos, "motivos": motivos}


async def rodar_caso(planner: Any, caso: Dict[str, Any]) -> Dict[str, Any]:
    """Roda a revisão sobre a conversa do caso numa casa temporária."""
    from ..config import settings
    from ..domains.escopo import usar_setor
    from ..harness import aprendizado
    from ..harness.orchestrator import SenturyOrchestrator
    from ..harness.state import AnalysisState
    from ..knowledge import manual
    from ..memory.session_store import InMemorySessionStore
    from ..memory.user_memory import get_user_memory_store

    anterior = os.environ.get("SENTURY_HOME")
    gravar = settings.SENTURY_GRAVAR_TRACOS
    with TemporaryDirectory(prefix="sentury-bancada-aprendizado-") as casa, usar_setor("generalista"):
        os.environ["SENTURY_HOME"] = casa
        settings.SENTURY_GRAVAR_TRACOS = False
        manual.esquecer()
        inicio = time.monotonic()
        try:
            from ..skills import escrita

            for skill in caso.get("skills_antes") or []:
                escrita.criar(skill["nome"], skill.get("descricao", ""), skill.get("corpo", ""), mesmo_assim=True)
            memoria = get_user_memory_store(InMemorySessionStore())
            orq = SenturyOrchestrator(planner=planner, responder=planner, store=None, memory=memoria)
            estado = AnalysisState.new(f"bancada-{caso['nome']}", "bancada")
            estado.history = [dict(m) for m in caso["conversa"]]
            feito = await aprendizado.revisar(orq, estado)
            feitas = escritas(Path(casa))
            return {"caso": caso["nome"], **julgar(caso, feitas), "ferramentas": feito["ferramentas"],
                    "respostas": feito.get("respostas", []),
                    "fala": feito["mensagem"][:300], "escritas": feitas,
                    "ms": round((time.monotonic() - inicio) * 1000), "erro": None}
        except Exception as exc:
            return {"caso": caso["nome"], "ok": False, "motivos": [], "erro": f"{type(exc).__name__}: {exc}"[:300]}
        finally:
            settings.SENTURY_GRAVAR_TRACOS = gravar
            manual.esquecer()
            if anterior is None:
                os.environ.pop("SENTURY_HOME", None)
            else:
                os.environ["SENTURY_HOME"] = anterior


async def rodar(planner_de: Any, casos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [await rodar_caso(planner_de(), caso) for caso in casos]


def resumo(resultados: List[Dict[str, Any]]) -> Dict[str, Any]:
    certos = [r["caso"] for r in resultados if r.get("ok")]
    return {"acertos": f"{len(certos)}/{len(resultados)}",
            "errados": {r["caso"]: r.get("erro") or r.get("motivos") for r in resultados if not r.get("ok")}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--provider", default="chatgpt_codex")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--casos", nargs="*")
    args = parser.parse_args()
    casos = [c for c in carregar() if not args.casos or c["nome"] in args.casos]
    if not args.live:
        print(json.dumps([{"caso": c["nome"], "descricao": c.get("descricao", "")} for c in casos],
                         ensure_ascii=False, indent=2))
        return 0
    from ..config import settings
    from .descoberta_multilingue import _Medido
    from .live_benchmark import _instantiate_provider

    provedor = _instantiate_provider(settings, args.provider, args.model)
    resultados = asyncio.run(rodar(lambda: _Medido(provedor), casos))
    print(json.dumps({"resumo": resumo(resultados), "casos": resultados}, ensure_ascii=False, indent=2))
    return int(not all(r.get("ok") for r in resultados))


if __name__ == "__main__":
    raise SystemExit(main())
