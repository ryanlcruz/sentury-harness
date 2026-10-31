"""python -m sentury.evals: roda as evals e imprime um relatório."""
import asyncio

from .golden import run_golden_evals
from .regressoes import run_regressoes


def main() -> int:
    async def tudo():
        return [
            ("Garantias", await run_golden_evals()),
            ("Regressões", await run_regressoes()),
        ]

    grupos = asyncio.run(tudo())
    print("\n=== Sentury — Evals ===")
    total = passou = 0
    for nome, resultados in grupos:
        print(f"\n--- {nome} ---")
        for r in resultados:
            marca = "PASS" if r.ok else "FALHA"
            print(f"[{marca}] {r.nome}")
            if not r.ok and r.detalhe:
                print(f"        -> {r.detalhe}")
        total += len(resultados)
        passou += sum(1 for r in resultados if r.ok)
    print(f"\n{passou}/{total} evals passaram.\n")
    return 0 if passou == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
