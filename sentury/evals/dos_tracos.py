"""Evals de casos reais: turnos gravados, escolhidos e rotulados por capacidade.

O corpus gravado não vira golden inteiro. Um traço entra quando alguém diz o
que ele prova: a capacidade e o que o resultado precisa ter. O replay repete o
turno com as respostas do modelo gravadas, então a eval mede o harness (o que
ele faz com a mesma resposta do modelo), e roda sem gastar chamada.

    python -m sentury.evals.dos_tracos candidatos
    python -m sentury.evals.dos_tracos promover T-1234abcd conversa --sem-ferramenta
    python -m sentury.evals.dos_tracos rodar
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from ..mutation import replay
from .golden import EvalResult

# O que um caso pode exigir do resultado. Lista fechada: expectativa com nome
# errado passaria sempre, porque ninguém a conferiria.
EXPECTATIVAS = (
    "sem_ferramenta",        # bool: o turno responde sem chamar ferramenta
    "ferramentas_incluem",   # list: cada uma tem de rodar
    "ferramentas_excluem",   # list: nenhuma pode rodar
    "mensagem_contem",       # list: trechos que a resposta precisa ter
    "mensagem_nao_contem",   # list: trechos que não podem aparecer
    "falha_esperada",        # bool: o caso é justamente a frase de erro
)


def _validar_rotulo(capacidade: str, esperado: Dict[str, Any]) -> None:
    if not isinstance(esperado, dict):
        raise ValueError("as expectativas precisam ser um objeto")
    desconhecidas = sorted(set(esperado) - set(EXPECTATIVAS))
    if desconhecidas:
        raise ValueError(f"expectativa desconhecida: {', '.join(desconhecidas)}; use {', '.join(EXPECTATIVAS)}")
    if not isinstance(capacidade, str) or not capacidade.strip():
        raise ValueError("diga a capacidade que o caso prova (conversa, esclarecimento, leitura...)")
    for chave, valor in esperado.items():
        if chave in ("sem_ferramenta", "falha_esperada"):
            if not isinstance(valor, bool):
                raise ValueError(f"{chave} precisa ser true ou false")
        elif not isinstance(valor, list) or not all(isinstance(v, str) and v.strip() for v in valor):
            raise ValueError(f"{chave} precisa ser uma lista de textos não vazios")
    if not any(esperado.values()):
        raise ValueError("diga ao menos uma expectativa que o caso precisa cumprir")
    incluem = set(esperado.get("ferramentas_incluem") or [])
    excluem = set(esperado.get("ferramentas_excluem") or [])
    if incluem & excluem or esperado.get("sem_ferramenta") and incluem:
        raise ValueError("as expectativas de ferramentas se contradizem")
    from ..tools.registry import TOOL_REGISTRY

    desconhecidas = sorted((incluem | excluem) - set(TOOL_REGISTRY))
    if desconhecidas:
        raise ValueError(f"ferramenta desconhecida nas expectativas: {', '.join(desconhecidas)}")


def promover(traco_id: str, capacidade: str, **esperado: Any) -> replay.Traco:
    """Move o traço para `avaliacao` com o que ele precisa provar."""
    desconhecidas = sorted(set(esperado) - set(EXPECTATIVAS))
    if desconhecidas:
        raise ValueError(f"expectativa desconhecida: {', '.join(desconhecidas)}; use {', '.join(EXPECTATIVAS)}")
    if not str(capacidade or "").strip():
        raise ValueError("diga a capacidade que o caso prova (conversa, esclarecimento, leitura...)")
    traco = replay.carregar(traco_id)
    if traco is None:
        raise ValueError(f"traço {traco_id} não existe em {replay.pasta()}")
    if traco.conjunto == "holdout":
        raise ValueError("traço de holdout não pode voltar ao conjunto de avaliação")
    from ..harness.state import is_transient_failure_message

    mensagem = str((traco.resultado_observado or {}).get("mensagem") or "")
    if (not traco.respostas_llm and is_transient_failure_message({"role": "assistant", "content": mensagem})
            and not esperado.get("falha_esperada")):
        raise ValueError("o modelo falhou neste turno e nada foi gravado: o caso só repetiria a frase de erro")
    _validar_rotulo(capacidade, esperado)
    traco.conjunto = "avaliacao"
    traco.resultado_esperado = {"capacidade": capacidade.strip(), **esperado}
    replay.salvar(traco)
    return traco


def conferir(esperado: Dict[str, Any], resultado: Dict[str, Any]) -> List[str]:
    """O que o resultado deixou de cumprir. Vazio é passou."""
    from ..harness.state import is_transient_failure_message

    falhas: List[str] = []
    mensagem = str(resultado.get("mensagem") or "")
    ferramentas = list(resultado.get("ferramentas") or [])
    baixa = mensagem.lower()

    falhou = is_transient_failure_message({"role": "assistant", "content": mensagem})
    if falhou and not esperado.get("falha_esperada"):
        falhas.append("o turno terminou na frase de erro")
    if esperado.get("falha_esperada") and not falhou:
        falhas.append("o turno não apresentou a falha esperada")
    if resultado.get("respostas_sobraram"):
        falhas.append("sobraram respostas gravadas do modelo")
    if resultado.get("resultados_sobraram"):
        falhas.append("sobraram resultados gravados de ferramenta")
    if resultado.get("respostas_faltaram"):
        falhas.append("o replay pediu ao modelo uma resposta que não foi gravada")
    if esperado.get("sem_ferramenta") and ferramentas:
        falhas.append(f"chamou ferramenta: {', '.join(ferramentas)}")
    for nome in esperado.get("ferramentas_incluem") or []:
        if nome not in ferramentas:
            falhas.append(f"não chamou {nome}")
    for nome in esperado.get("ferramentas_excluem") or []:
        if nome in ferramentas:
            falhas.append(f"chamou {nome}")
    for trecho in esperado.get("mensagem_contem") or []:
        if str(trecho).lower() not in baixa:
            falhas.append(f"a resposta não tem {trecho!r}")
    for trecho in esperado.get("mensagem_nao_contem") or []:
        if str(trecho).lower() in baixa:
            falhas.append(f"a resposta tem {trecho!r}")
    return falhas


def _nome(traco: replay.Traco) -> str:
    esperado = traco.resultado_esperado
    capacidade = esperado.get("capacidade") if isinstance(esperado, dict) else None
    capacidade = capacidade or "sem capacidade"
    pedido = " ".join(str(traco.mensagem or "").split())[:60]
    return f"{capacidade}: {pedido} ({traco.id})"


def _falhas_do_caso(traco: replay.Traco) -> List[str]:
    from ..harness.gravacao_do_turno import sem_resultado_gravado

    esperado = traco.resultado_esperado
    try:
        if not isinstance(esperado, dict):
            raise ValueError("as expectativas precisam ser um objeto")
        _validar_rotulo(esperado.get("capacidade"), {k: v for k, v in esperado.items() if k != "capacidade"})
    except ValueError as exc:
        return [str(exc)]
    falhas = []
    if not traco.determinista:
        falhas.append("o traço não é determinista e precisa de avaliação ao vivo")
    if not traco.resultado_observado:
        falhas.append("o traço não tem resultado observado da produção")
    ferramentas = (traco.resultado_observado or {}).get("ferramentas") or []
    faltam = sem_resultado_gravado(ferramentas, traco.resultados_ferramentas)
    if faltam:
        falhas.append(f"faltam resultados gravados de ferramenta: {', '.join(faltam)}")
    return falhas


async def rodar(construir_orquestrador, conjunto: str = "avaliacao") -> List[EvalResult]:
    resultados: List[EvalResult] = []
    for traco in replay.listar(conjunto):
        esperado = traco.resultado_esperado
        falhas = _falhas_do_caso(traco)
        if falhas:
            resultados.append(EvalResult(_nome(traco), False, "; ".join(falhas)))
            continue
        repetido = await replay.repetir(traco, construir_orquestrador)
        if not repetido.get("ok"):
            resultados.append(EvalResult(_nome(traco), False, repetido.get("erro") or "o replay falhou"))
            continue
        falhas = conferir(esperado, repetido)
        resultados.append(EvalResult(_nome(traco), not falhas, "; ".join(falhas)))
    return resultados


def cobertura(conjunto: str = "avaliacao", capacidades: List[str] | None = None) -> Dict[str, Any]:
    """Conta casos rotulados e repetíveis; não substitui a execução da avaliação."""
    por_capacidade: Dict[str, Dict[str, int]] = {}
    invalidos = []
    ferramentas = set()
    tracos = replay.listar(conjunto)
    for traco in tracos:
        esperado = traco.resultado_esperado
        capacidade = esperado.get("capacidade") if isinstance(esperado, dict) else None
        capacidade = capacidade.strip() if isinstance(capacidade, str) else ""
        falhas = _falhas_do_caso(traco)
        if capacidade:
            contagem = por_capacidade.setdefault(capacidade, {"casos": 0, "repetiveis": 0})
            contagem["casos"] += 1
            contagem["repetiveis"] += not falhas
        if falhas:
            invalidos.append({"traco": traco.id, "motivos": falhas})
        else:
            ferramentas.update((traco.resultado_observado or {}).get("ferramentas") or [])
    faltam = sorted({nome.strip() for nome in capacidades or [] if nome.strip()} - {
        nome for nome, contagem in por_capacidade.items() if contagem["repetiveis"]
    })
    return {
        "conjunto": conjunto, "tracos": len(tracos), "repetiveis": len(tracos) - len(invalidos),
        "capacidades": dict(sorted(por_capacidade.items())), "capacidades_sem_casos": faltam,
        "ferramentas": sorted(ferramentas), "invalidos": invalidos,
    }


def candidatos() -> List[Dict[str, Any]]:
    """Traços que o replay consegue repetir e ainda não foram rotulados."""
    from ..harness.gravacao_do_turno import sem_resultado_gravado

    saida = []
    for traco in replay.listar("desenvolvimento"):
        observado = traco.resultado_observado or {}
        ferramentas = observado.get("ferramentas") or []
        if not traco.determinista or not traco.respostas_llm or not observado:
            continue
        if sem_resultado_gravado(ferramentas, traco.resultados_ferramentas):
            continue
        saida.append({
            "traco": traco.id,
            "pedido": " ".join(str(traco.mensagem or "").split())[:80],
            "ferramentas": ferramentas,
            "resposta": " ".join(str(observado.get("mensagem") or "").split())[:80],
        })
    return saida


def _main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="acao", required=True)
    sub.add_parser("candidatos", help="traços repetíveis ainda sem rótulo")
    c = sub.add_parser("cobertura", help="capacidades cobertas e casos que não podem ser repetidos")
    c.add_argument("--capacidade", action="append", default=[], help="capacidade cuja presença precisa ser conferida")
    p = sub.add_parser("promover", help="rotula um traço e o põe em avaliacao")
    p.add_argument("traco")
    p.add_argument("capacidade")
    p.add_argument("--sem-ferramenta", action="store_true")
    p.add_argument("--falha-esperada", action="store_true")
    p.add_argument("--inclui", action="append", default=[], help="ferramenta que tem de rodar")
    p.add_argument("--exclui", action="append", default=[], help="ferramenta que não pode rodar")
    p.add_argument("--contem", action="append", default=[], help="trecho que a resposta precisa ter")
    p.add_argument("--nao-contem", action="append", default=[], help="trecho que não pode aparecer")
    sub.add_parser("rodar", help="repete os casos de avaliacao e confere")
    args = parser.parse_args(argv)

    if args.acao == "candidatos":
        print(json.dumps(candidatos(), ensure_ascii=False, indent=2))
        return 0
    if args.acao == "cobertura":
        resultado = cobertura(capacidades=args.capacidade)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0 if resultado["repetiveis"] and not resultado["invalidos"] and not resultado["capacidades_sem_casos"] else 1
    if args.acao == "promover":
        esperado: Dict[str, Any] = {}
        if args.sem_ferramenta:
            esperado["sem_ferramenta"] = True
        if args.falha_esperada:
            esperado["falha_esperada"] = True
        for chave, valor in (("ferramentas_incluem", args.inclui), ("ferramentas_excluem", args.exclui),
                             ("mensagem_contem", args.contem), ("mensagem_nao_contem", args.nao_contem)):
            if valor:
                esperado[chave] = valor
        traco = promover(args.traco, args.capacidade, **esperado)
        print(f"{traco.id} em avaliacao: {traco.resultado_esperado}")
        return 0

    import subprocess
    from pathlib import Path

    # O processo filho escolhe a casa descartável antes de carregar a configuração.
    script = Path(__file__).resolve().parents[2] / "scripts" / "replay_bateria.py"
    return subprocess.run([sys.executable, str(script), "--avaliar"], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
