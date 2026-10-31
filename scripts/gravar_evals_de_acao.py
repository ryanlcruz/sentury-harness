"""Grava um caso real isolado; a tela é atendida pelo cliente MCP do Tato."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def carregar_casos():
    import yaml
    return yaml.safe_load((RAIZ / "sentury/evals/casos_de_acao.yaml").read_text(encoding="utf-8"))


def preparar(casa):
    casa = Path(casa).resolve()
    casa.mkdir(parents=True, exist_ok=True)
    if any(casa.iterdir()):
        raise ValueError("Escolha uma casa vazia para a bancada.")
    trabalho = casa / "trabalho"
    trabalho.mkdir()
    os.environ.update({
        "SENTURY_HOME": str(casa), "SENTURY_WORKSPACE": str(trabalho),
        "SENTURY_TRACOS_DIR": str(casa / "tracos"),
        "ROBINBANDIT_HOME": str(casa / "robin"),
        "ROBINBANDIT_VAULT_PATH": str(casa / "robin/cofre.json"),
        "ROBINBANDIT_ACCOUNTS_PATH": str(casa / "robin/contas.json"),
        "SENTURY_VAULT_PATH": str(casa / "robin/cofre.json"),
        "SENTURY_ACCOUNTS_PATH": str(casa / "robin/contas.json"),
        "SENTURY_DOMAIN": "generalista", "SENTURY_GRAVAR_TRACOS": "true",
        "SENTURY_AUTOLEARN": "false", "SENTURY_EMBEDDINGS": "false",
        "SENTURY_GEMINI_EMBEDDINGS": "false", "PYTHONUTF8": "1",
    })
    return casa


def validar_chamada(caso, ferramenta, argumentos, trabalho):
    if ferramenta != caso["ferramenta"]:
        raise ValueError("Esta bancada só executa a ferramenta do cenário escolhido.")
    permitidos = set(caso["argumentos"]) | set(caso.get("extras_permitidos") or [])
    if set(argumentos) - permitidos:
        raise ValueError("O cenário não autoriza esses parâmetros extras.")
    for chave, valor in caso["argumentos"].items():
        if argumentos.get(chave) != valor:
            raise ValueError("A chamada não corresponde à ação autorizada no cenário.")
    if argumentos.get("arquivo") or argumentos.get("argumentos") or argumentos.get("args"):
        raise ValueError("O cenário não autoriza arquivo executável ou argumentos extras.")
    if argumentos.get("diretorio") and Path(argumentos["diretorio"]).resolve() != trabalho.resolve():
        raise ValueError("O cenário só executa na pasta isolada.")


async def pelo_tato(pasta, ferramenta, argumentos):
    ident = uuid.uuid4().hex
    pedido, resposta = pasta / f"{ident}.pedido.json", pasta / f"{ident}.resposta.json"
    pedido.write_text(json.dumps({"ferramenta": ferramenta, "argumentos": argumentos}, ensure_ascii=False), encoding="utf-8")
    inicio = time.monotonic()
    while not resposta.exists():
        if time.monotonic() - inicio > 120:
            raise TimeoutError("O cliente MCP não devolveu o resultado do Tato.")
        await asyncio.sleep(0.2)
    return json.loads(resposta.read_text(encoding="utf-8"))


async def rodar(args, casa):
    from sentury import main as app
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState
    from sentury.llm.effort import use_effort, clear_effort
    from sentury.mutation import replay
    from sentury.tools import catalog, permissoes
    from robinbandit.providers import ReinforcedProvider
    from robinbandit.providers.codex_provider import CodexProvider
    from robinbandit.routing.sentury import ChainProvider, use_ultra_provider, clear_ultra_provider

    caso = carregar_casos()[args.caso]
    ipc = casa / "tato"
    ipc.mkdir()
    original = catalog._executar_ferramenta
    async def executar(store, state, ferramenta, argumentos, *extras):
        validar_chamada(caso, ferramenta, argumentos, casa / "trabalho")
        if caso["atendimento"] == "tato":
            return await pelo_tato(ipc, ferramenta, argumentos)
        return await original(store, state, ferramenta, argumentos, *extras)
    catalog._executar_ferramenta = executar
    conta = CodexProvider([args.modelo])
    grupo = ReinforcedProvider([conta], name="ultra_max")
    cadeia = ChainProvider([conta], active_effort=lambda: "low")
    orq = SenturyOrchestrator(planner=cadeia, responder=cadeia, store=app.data_store,
                              knowledge=app.knowledge_base, memory=None, skills=None)
    state = AnalysisState.new("acao-" + args.caso, "bancada")
    state.funcoes_ativas = caso["funcoes"]
    permissoes.definir_permitir_tudo(True)
    token = use_ultra_provider(grupo)
    esforco = use_effort("low")
    try:
        saida = await orq.handle_message(state, caso["pedido"])
    finally:
        clear_ultra_provider(token)
        clear_effort(esforco)
        catalog._executar_ferramenta = original
    tracos = replay.listar("desenvolvimento")
    dados = {"caso": args.caso, "mensagem": saida["message"], "telemetry": saida.get("telemetry"),
             "tracos": [{"id": t.id, "determinista": t.determinista,
                         "ferramentas": t.resultado_observado.get("ferramentas"),
                         "provedores": sorted({r.get("provedor", "") for r in t.respostas_llm if isinstance(r, dict)})}
                        for t in tracos]}
    (casa / "resultado.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dados, ensure_ascii=False))
    executadas = [r for t in tracos for r in t.resultados_ferramentas
                  if r.get("tool") == caso["ferramenta"] and isinstance(r.get("resultado"), dict)
                  and r["resultado"].get("ok") is True]
    return 0 if executadas and all(t.lower() in saida["message"].lower() for t in caso["contem"]) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caso", choices=tuple(carregar_casos()), required=True)
    parser.add_argument("--modelo", required=True)
    parser.add_argument("--casa", required=True)
    args = parser.parse_args()
    return asyncio.run(rodar(args, preparar(args.casa)))


if __name__ == "__main__":
    raise SystemExit(main())
