"""Mede o que o usuário vê enquanto o turno roda, não só o que sobra no fim.

Três defeitos apareceram em teste manual e nenhum deles é visível numa suíte de
unidade, porque todos dependem do que o MODELO devolve num turno de verdade:

- ele executa sem dizer o que vai fazer (a fala existia e era descartada);
- as linhas de execução dizem "Executando ferramenta…", todas iguais;
- a execução não conta em cima de quê rodou.

Este script dispara turnos reais contra a API no ar, lê o SSE e conta. Roda
assim, com a API já de pé:

    python scripts/bench_execucao.py --modo ultra_max

Ele não julga a resposta: mede o acompanhamento. Uma resposta certa entregue
em silêncio continua sendo o problema que estamos consertando.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List

# Tarefas que EXIGEM ferramenta: sem execução não há o que narrar, e o
# benchmark mediria o vazio.
TAREFAS = [
    "o que tem na pasta deste projeto?",
    "quantos arquivos .py existem aqui e qual o maior deles?",
    "leia o README deste projeto e me diga em uma frase o que ele faz",
    "liste as pastas do projeto e conte quantos testes existem",
]

GENERICO = "Executando ferramenta"

# O contrato do planejador pede JSON, e quando alguma etapa tropeça esse JSON
# chega na tela como se fosse a resposta. Já aconteceu: seis voltas, zero
# ferramentas, e uma cerca ```json vazia entregue ao usuário.
VAZAMENTO = re.compile(r"```json|\{\s*\"plan\"|\{\s*\"tool\"")


def _eventos(base: str, mensagem: str, modo: str, timeout: float) -> List[Dict[str, Any]]:
    corpo = json.dumps({
        "session_id": f"bench-{int(time.time() * 1000)}",
        "user_id": "bench",
        "message": mensagem,
        "mode": modo,
    }).encode("utf-8")
    pedido = urllib.request.Request(
        f"{base}/chat/stream", data=corpo,
        headers={"Content-Type": "application/json"},
    )
    recolhidos: List[Dict[str, Any]] = []
    with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
        for linha in resposta:
            linha = linha.decode("utf-8", "replace").strip()
            if not linha.startswith("data:"):
                continue
            try:
                recolhidos.append(json.loads(linha[5:].strip()))
            except ValueError:
                continue
    return recolhidos


def _resposta(eventos: List[Dict[str, Any]]) -> str:
    """O texto que a pessoa lê no fim: token a token, ou o `done` inteiro."""
    partes = [str(e.get("text") or e.get("content") or "")
              for e in eventos if e.get("type") == "token"]
    if partes:
        return "".join(partes)
    return next((str(e.get("result") or "")
                 for e in eventos if e.get("type") == "done"), "")


def _medir(eventos: List[Dict[str, Any]]) -> Dict[str, Any]:
    inicios = [e for e in eventos if e.get("type") == "tool_start"]
    resposta = _resposta(eventos)
    # A fala vive no evento que anuncia o passo: um passo mudo e o defeito.
    falas = [e for e in inicios if str(e.get("fala") or "").strip()]
    falas += [e for e in eventos if e.get("type") == "narracao"]
    titulos = [str(e.get("title") or "") for e in inicios]
    return {
        "ferramentas": len(inicios),
        "falas": len(falas),
        "titulos_genericos": sum(1 for t in titulos if GENERICO in t),
        # O alvo (qual pasta, qual consulta) vive no corpo do cartão de
        # execução, não no título: no título ele quebrava a linha em três
        # repetindo o que já estava ao lado.
        "com_alvo": sum(1 for e in inicios if str(e.get("command") or "").strip()),
        "vazou_json": bool(VAZAMENTO.search(resposta)),
        "erro": next((str(e.get("message") or e.get("error") or "")[:120]
                      for e in eventos if e.get("type") == "error"), ""),
        # `fala` no tool_start, `text` no evento de turno: as duas fontes.
        "exemplo_de_fala": (falas[0].get("fala") or falas[0].get("text") or "") if falas else "",
        "exemplo_de_titulo": titulos[0] if titulos else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--modo", default="router", help="router, ultra ou ultra_max")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--tarefas", type=int, default=len(TAREFAS))
    args = ap.parse_args()

    linhas: List[Dict[str, Any]] = []
    for i, tarefa in enumerate(TAREFAS[: args.tarefas], 1):
        print(f"[{i}/{args.tarefas}] {tarefa}", flush=True)
        comeco = time.monotonic()
        try:
            medida = _medir(_eventos(args.base, tarefa, args.modo, args.timeout))
        except (urllib.error.URLError, TimeoutError) as causa:
            medida = {"ferramentas": 0, "falas": 0, "titulos_genericos": 0,
                      "com_alvo": 0, "vazou_json": False, "erro": f"{type(causa).__name__}: {causa}"[:120],
                      "exemplo_de_fala": "", "exemplo_de_titulo": ""}
        medida["segundos"] = round(time.monotonic() - comeco, 1)
        medida["tarefa"] = tarefa
        linhas.append(medida)
        print(f"    {medida['ferramentas']} ferramentas · {medida['falas']} falas · "
              f"{medida['titulos_genericos']} títulos genéricos · {medida['segundos']}s"
              + (f" · ERRO {medida['erro']}" if medida["erro"] else ""), flush=True)
        if medida["exemplo_de_fala"]:
            print(f"    fala: {medida['exemplo_de_fala'][:110]}", flush=True)
        if medida["exemplo_de_titulo"]:
            print(f"    título: {medida['exemplo_de_titulo'][:110]}", flush=True)

    ferramentas = sum(l["ferramentas"] for l in linhas)
    falas = sum(l["falas"] for l in linhas)
    genericos = sum(l["titulos_genericos"] for l in linhas)
    com_alvo = sum(l["com_alvo"] for l in linhas)
    print("\n" + "=" * 62)
    print(f"turnos            : {len(linhas)}")
    print(f"ferramentas        : {ferramentas}")
    print(f"passos com fala    : {falas} de {ferramentas}")
    print(f"títulos genéricos  : {genericos} de {ferramentas}")
    print(f"execuções com alvo : {com_alvo} de {ferramentas}")
    print(f"tempo total        : {round(sum(l['segundos'] for l in linhas), 1)}s")
    vazaram = [l for l in linhas if l["vazou_json"]]
    print(f"JSON na resposta   : {len(vazaram)} de {len(linhas)}")
    erros = [l for l in linhas if l["erro"]]
    if erros:
        print(f"turnos com erro    : {len(erros)}")
    return 1 if (erros or vazaram or (ferramentas and falas == 0)) else 0


if __name__ == "__main__":
    sys.exit(main())
