"""Repete os turnos gravados nesta maquina e confere se batem com a producao.

Compara o resultado repetido com o observado na produção e separa mudanças
de comportamento, falhas e gravações que não bastam para repetir o turno.

    python scripts/replay_bateria.py
    python scripts/replay_bateria.py --conjunto avaliacao --limite 20
    python scripts/replay_bateria.py --json > bateria.json
    python scripts/replay_bateria.py --avaliar

Nao chama modelo nenhum: as respostas vem gravadas no traco. Os traços moram
em `~/.sentury/tracos` (ou em `SENTURY_TRACOS_DIR`).

O que pode dar `mudou` sem ser defeito do replay, e vale ler antes de concluir:

- o codigo mudou desde a gravacao (o traco guarda o commit em `ambiente`);
- o dado mudou: o store e lido AGORA, nao no dia do turno;
- o traço não tem os resultados de ferramentas necessários para repetir.

O replay nao age no mundo nem na casa do Sentury. Roda numa copia descartavel
da `SENTURY_HOME` (a trava de escritor, o registro do turno e os artefatos caem
nela, e um Sentury aberto ao mesmo tempo segue intocado), e memoria,
experiencias, skills e store recusam escrita. O resultado lista o que cada
turno tentou escrever.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _casa_descartavel() -> Path:
    """Copia a casa do Sentury para uma pasta temporaria e passa a usar a copia.

    Tem que rodar antes de qualquer import do `sentury`: a configuracao le a
    `SENTURY_HOME` uma vez. Os tracos continuam sendo lidos de onde estao.
    """
    real = Path(os.environ.get("SENTURY_HOME") or (Path.home() / ".sentury")).expanduser()
    # A busca da bancada usa o índice local, sem chamadas externas nem downloads.
    os.environ["SENTURY_GEMINI_EMBEDDINGS"] = "false"
    os.environ["SENTURY_EMBEDDINGS"] = "false"
    os.environ.setdefault("SENTURY_TRACOS_DIR", str(real / "tracos"))
    base = Path(tempfile.mkdtemp(prefix="sentury-replay-"))
    copia = base / "casa"
    if real.is_dir():
        shutil.copytree(real, copia, ignore=shutil.ignore_patterns("escritor.lock", "tracos"))
    else:
        copia.mkdir(parents=True)
    os.environ["SENTURY_HOME"] = str(copia)
    # Turno repetido que gera arquivo não escreve nos Documentos da pessoa.
    os.environ["SENTURY_ARTEFATOS_DIR"] = str(base / "entregas")
    return base


def _construtor():
    """O orquestrador da producao, com o modelo trocado pelo gravado.

    Compactacao e conselho recebem o MESMO dublê que o planner:
    na producao eles se revezam na mesma cadeia, e a fila gravada tem a ordem
    dessa cadeia.
    """
    from sentury import main as app
    from sentury.harness.context_budget import ContextBudgetManager, Contextualizer
    from sentury.harness.council import SenturyCouncil
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.mutation.efeitos import somente_leitura

    def construir(planner, responder):
        deps, recusadas = somente_leitura(
            memory=app.user_memory, experience_library=app.exp_lib,
            skills=app.skill_store, store=app.data_store,
        )
        orquestrador = SenturyOrchestrator(
            planner=planner,
            responder=responder,
            store=deps["store"],
            knowledge=app.knowledge_base,
            memory=deps["memory"],
            skills=deps["skills"],
            context_budget_manager=ContextBudgetManager(Contextualizer(responder)),
            experience_library=deps["experience_library"],
            council=SenturyCouncil(planner),
        )
        orquestrador.efeitos_recusados = recusadas
        return orquestrador

    return construir


def main() -> int:
    base = _casa_descartavel()
    try:
        return _rodar()
    finally:
        # No Windows a trava da copia so solta quando o processo sai: o que
        # sobrar fica na pasta temporaria do sistema.
        shutil.rmtree(base, ignore_errors=True)


def _rodar() -> int:
    from sentury.mutation import replay

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--conjunto", default="desenvolvimento", choices=replay.CONJUNTOS)
    parser.add_argument("--limite", type=int, default=0, help="so os N mais recentes")
    parser.add_argument("--json", action="store_true", help="resultado inteiro em JSON")
    parser.add_argument("--avaliar", action="store_true", help="confere as expectativas dos casos rotulados")
    args = parser.parse_args()

    if args.avaliar:
        from sentury.evals.dos_tracos import rodar

        resultados = asyncio.run(rodar(_construtor(), "avaliacao"))
        for r in resultados:
            print(f"[{'PASS' if r.ok else 'FALHA'}] {r.nome}" + (f"\n        -> {r.detalhe}" if r.detalhe else ""))
        passou = sum(r.ok for r in resultados)
        print(f"\n{passou}/{len(resultados)} casos reais passaram.")
        return 0 if resultados and passou == len(resultados) else 1

    resultado = asyncio.run(replay.bateria(_construtor(), args.conjunto, limite=args.limite))
    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0 if resultado["fiel"] else 1

    print(f"{resultado['tracos']} tracos de '{args.conjunto}' em {replay.pasta()}")
    print(f"  selecionados:      {resultado['selecionados']}")
    print(f"  fora da bateria:   {len(resultado['fora_da_bateria'])}")
    print(f"  repetidos:         {resultado['repetidos']}")
    print(f"  iguais a producao: {resultado['iguais']}")
    print(f"  mudaram:           {len(resultado['mudaram'])}")
    print(f"  falharam:          {len(resultado['falharam'])}")
    print(f"  pulados:           {len(resultado.get('pulados') or [])} (faltam resultados gravados)")
    for d in resultado["mudaram"]:
        print(f"  - {d.get('traco')}: {'; '.join(d.get('motivos') or []) or 'mudou'}")
    for f in resultado["falharam"]:
        print(f"  x {f['traco']}: {f.get('erro') or 'falhou'}")
    for p in resultado.get("pulados") or []:
        print(f"  . {p['traco']}: {', '.join(p['ferramentas'])}")
    efeitos = resultado.get("efeitos_recusados") or []
    if efeitos:
        print(f"  escritas recusadas em {len(efeitos)} tracos (a producao fez; o replay so anotou):")
        for e in efeitos:
            nomes = sorted({f"{x['dependencia']}.{x['metodo']}" for x in e["efeitos"]})
            print(f"  ~ {e['traco']}: {', '.join(nomes)}")
    if not resultado["repetidos"]:
        print("Nenhum traço foi repetido: confira o conjunto e os motivos de exclusão.")
    print("FIEL" if resultado["fiel"] else "NAO FIEL")
    return 0 if resultado["fiel"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
