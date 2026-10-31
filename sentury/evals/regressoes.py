"""Evals nascidas de defeitos que aconteceram de verdade.

Todo caso aqui corresponde a algo que quebrou e passou despercebido (em
alguns casos por semanas) porque nenhuma medida olhava para aquilo. Um eval
escrito depois do defeito é barato e vale mais que dez casos inventados: ele
já provou uma vez que a garantia pode cair.

A regra para entrar aqui: **o defeito tem que ter acontecido**. Não é lugar
para o que talvez um dia quebre.

Rodam sem LLM real, então servem em CI.
"""
from __future__ import annotations

import json
from typing import Any, Callable, List

from .golden import EvalResult


# ---------------------------------------------------------------------------
# Contexto: o que viaja em cada turno
# ---------------------------------------------------------------------------

def _historico_com_turnos() -> List[dict]:
    """A forma da conversa que motivou este eval: seis turnos, cada um com
    pergunta, resultado bruto de ferramenta e resposta.

    O tamanho importa. Com dois resultados só, o piso de proteção cobre os
    dois e a poda corretamente não faz nada: foi assim que este eval falhou
    na primeira escrita, testando o cenário errado. O custo aparece na
    conversa que já andou, que é justamente onde ele dói.
    """
    def resultado(indice: int, ferramenta: str, corpo: dict) -> dict:
        return {"role": "system", "content": (
            f"ID DO RESULTADO NA SESSÃO: 'resultado_{indice:03d}'\n"
            f'RESULTADO DA FERRAMENTA "{ferramenta}" (ja executada): '
            + str({**corpo, "_dump": "x" * 2500})
        )}

    analises = [
        ("analyze_nps", {"nps": -31.2, "volume": 5000}),
        ("root_cause", {"regiao": "Sudeste", "nps": -49.3}),
        ("analyze_tickets", {"volume": 3381, "pct_backlog": 100.0}),
        ("analyze_segments", {"regiao": "Sul", "nps": 30.3}),
        ("compare_periods", {"nps": -28.0, "volume": 900}),
    ]
    historico: List[dict] = []
    for i, (ferramenta, corpo) in enumerate(analises, start=1):
        historico.append({"role": "user", "content": f"pergunta {i} sobre os dados"})
        historico.append(resultado(i, ferramenta, corpo))
        historico.append({"role": "assistant", "content": f"resposta {i}, com a conclusão."})
    historico.append({"role": "user", "content": "e o que dizem por ai sobre isso?"})
    return historico


async def _eval_poda_economiza_de_verdade() -> EvalResult:
    """A poda existia e economizava ZERO: protegia os 6 últimos resultados
    (numa conversa comum, todos) e só resumia acima de 4.000 caracteres, teto
    que um resultado de análise nunca alcança. Ninguém percebeu por meses."""
    from ..harness.context_budget import ContextBudgetManager, Contextualizer

    historico = _historico_com_turnos()
    antes = sum(len(m["content"]) for m in historico)
    depois_lista = ContextBudgetManager(Contextualizer(llm_chain=None)).prune_tool_outputs(historico)
    depois = sum(len(m["content"]) for m in depois_lista)

    economia = 100 * (antes - depois) / max(antes, 1)
    ok = economia >= 20
    return EvalResult("poda de contexto economiza de verdade", ok, f"{economia:.1f}% a menos")


async def _eval_poda_preserva_a_procedencia() -> EvalResult:
    """Sem o ID, o resumo vira dado sem fonte e o detalhe some para sempre."""
    from ..harness.context_budget import ContextBudgetManager, Contextualizer

    saida = ContextBudgetManager(Contextualizer(llm_chain=None)).prune_tool_outputs(
        _historico_com_turnos()
    )
    resumidos = [m for m in saida if "resumido para poupar" in m.get("content", "")]
    ok = bool(resumidos) and all("ID DO RESULTADO" in m["content"] for m in resumidos)
    detalhe = resumidos[0]["content"][:90] if resumidos else "nada foi resumido"
    return EvalResult("resumo mantém o ID do resultado", ok, detalhe)


# ---------------------------------------------------------------------------
# Custo: o que o usuário vê e paga
# ---------------------------------------------------------------------------

async def _eval_cache_do_provedor_e_medido() -> EvalResult:
    """Cada provedor chama o cache de um nome, e só o do Gemini era lido. Sem
    isso, a mesma entrada podia custar 10% ou 100% sem nada aparecer."""
    from robinbandit.claude_provider import _usage_anthropic
    from robinbandit.gemini_provider import _usage_gemini
    from robinbandit.openai_compat import _normalizar_usage

    gemini = _usage_gemini({"usageMetadata": {
        "promptTokenCount": 21112, "candidatesTokenCount": 675,
        "totalTokenCount": 22894, "cachedContentTokenCount": 19000}})
    openai = _normalizar_usage({
        "prompt_tokens": 21112, "completion_tokens": 675, "total_tokens": 21787,
        "prompt_tokens_details": {"cached_tokens": 19000}})
    anthropic = _usage_anthropic({
        "input_tokens": 1200, "cache_read_input_tokens": 19000,
        "cache_creation_input_tokens": 0, "output_tokens": 675})

    ok = all(u and u.get("cacheado") == 19000 for u in (gemini, openai, anthropic))
    # Ausência de medida não equivale a valor zero.
    sem = _normalizar_usage({"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6})
    ok = ok and "cacheado" not in sem
    return EvalResult("cache é medido em todo provedor que informa", ok,
                      f"gemini={bool(gemini)} openai={bool(openai)} anthropic={bool(anthropic)}")


async def _eval_todo_provedor_publica_o_que_gastou() -> EvalResult:
    """O ClaudeProvider não publicava `last_usage`: turno atendido por ele
    aparecia com ZERO token, e o custo do turno mentia."""
    from robinbandit.claude_provider import ClaudeProvider
    from robinbandit.gemini_provider import GeminiProvider
    from robinbandit.groq_provider import GroqProvider

    faltando = [
        p.__name__ for p in (ClaudeProvider, GeminiProvider, GroqProvider)
        if not hasattr(p("k", ["m"]), "last_usage")
    ]
    return EvalResult("todo provedor publica o que gastou", not faltando,
                      f"sem last_usage: {faltando}" if faltando else "todos publicam")


# ---------------------------------------------------------------------------
# Segurança: o que não pode acontecer nunca
# ---------------------------------------------------------------------------

async def _eval_segredo_nao_e_legivel_por_comando() -> EvalResult:
    """`cat .env` passava na allowlist: o comando era permitido, e ninguém
    olhava o ALVO. Isso despejaria todas as chaves na conversa e no journal."""
    from ..tools.shell import ComandoRecusado, validar

    proibidos = ["cat .env", "type .env", "cat auth.json", "cat ~/.ssh/id_rsa",
                 "cat credentials.json", "cat ~/.aws/credentials"]
    passaram = []
    for comando in proibidos:
        try:
            validar(comando)
            passaram.append(comando)
        except ComandoRecusado:
            pass
    return EvalResult("segredo não é legível por comando", not passaram,
                      f"passaram: {passaram}" if passaram else "todos recusados")


async def _eval_escrita_exige_autorizacao() -> EvalResult:
    """Leitura sempre pôde; o resto passa por decisão de quem é dono da
    máquina: e um hook declarado não contorna isso."""
    from ..tools import permissoes

    sessao = "eval-permissao"
    permissoes.limpar_sessao(sessao)
    for chave in ("rm", "git commit"):
        permissoes.esquecer(chave)
    try:
        decisao = permissoes.avaliar("rm -rf build", sessao)
        pergunta = decisao["precisa_perguntar"] and not decisao["permitido"]

        # Recusar agora não bane para sempre: a pergunta volta.
        permissoes.responder("rm -rf build", "negar", sessao)
        volta = permissoes.avaliar("rm -rf build", sessao)["precisa_perguntar"]

        # Leitura não passa por aqui.
        from ..tools.shell import validar
        validar("git status")
        ok = pergunta and volta
    except Exception as exc:
        return EvalResult("escrita exige autorização", False, str(exc))
    finally:
        permissoes.limpar_sessao(sessao)
        permissoes.esquecer("rm")
    return EvalResult("escrita exige autorização", ok, "pergunta e não bane no 'não'")


async def _eval_politica_ilegivel_fecha_tudo() -> EvalResult:
    """Config quebrada não pode virar config permissiva: sem política legível,
    o certo é NÃO rodar nada."""
    from ..tools.shell import _padrao

    padrao = _padrao()
    ok = not padrao.get("leitura") and not padrao.get("escrita")
    return EvalResult("política ilegível fecha tudo", ok, str(list(padrao)))


# ---------------------------------------------------------------------------
# Capacidade: o que o agente precisa conseguir fazer
# ---------------------------------------------------------------------------

async def _eval_busca_web_funciona_sem_chave() -> EvalResult:
    """A busca nunca funcionava sem chave configurada, e o modelo respondia de
    MEMÓRIA a um pedido explícito de pesquisa: informação sem fonte."""
    from ..tools.web import provedor_de_busca

    class _SemChaveNenhuma:
        pass

    escolhido = provedor_de_busca(_SemChaveNenhuma())
    ok = bool(escolhido) and bool(escolhido.get("endpoint"))
    return EvalResult("busca na web funciona sem chave", ok,
                      str(escolhido.get("nome") if escolhido else "nenhum provedor"))


async def _eval_comando_longo_nao_morre() -> EvalResult:
    """O teto de 60s ENCERRAVA o comando: um build perdia o trabalho feito e
    não havia como saber o resultado depois."""
    import sys

    from ..tools import processos

    try:
        pid = processos.iniciar(
            [sys.executable, "-c", "import time; time.sleep(3); print('terminei')"],
            diretorio=".", comando="tarefa longa",
        )
        parcial = processos.esperar(pid, timeout=0.5)
        continuou = parcial["rodando"]
        final = processos.esperar(pid, timeout=20)
        ok = continuou and not final["rodando"] and "terminei" in final["saida"]
        detalhe = f"desanexou={continuou} colheu={'terminei' in final['saida']}"
    finally:
        processos.limpar_tudo()
    return EvalResult("comando longo desanexa em vez de morrer", ok, detalhe)


async def _eval_diagrama_e_reconhecido() -> EvalResult:
    """O regex de mermaid tinha um `\\b` corrompido em byte de backspace: nunca
    casava, e nenhum diagrama renderizava. Silencioso por semanas."""
    import re
    from pathlib import Path

    fonte = Path("sentury/client/src/domain/markdown.ts")
    if not fonte.exists():
        return EvalResult("diagrama é reconhecido", False, "markdown.ts não encontrado")
    bruto = fonte.read_bytes()
    # 0x08 é backspace: um `\b` que virou caractere de controle no arquivo.
    corrompido = b"\x08" in bruto
    tem_mermaid = b"mermaid" in bruto
    return EvalResult("diagrama é reconhecido", tem_mermaid and not corrompido,
                      "byte de controle no regex" if corrompido else "regex íntegro")


# ---------------------------------------------------------------------------
# Fronteiras: o que não pode se misturar
# ---------------------------------------------------------------------------

async def _eval_plugin_nao_depende_do_host() -> EvalResult:
    """O RobinBandit tem repositório próprio: se importar `sentury.*`, deixa
    de rodar sozinho lá: e isso já aconteceu esta semana."""
    from pathlib import Path

    raiz = Path("sentury/plugins/robinbandit/src")
    if not raiz.is_dir():
        return EvalResult("plugin não depende do host", False, "plugin não encontrado")
    ofensores = [
        arquivo.name for arquivo in raiz.rglob("*.py")
        if "from sentury" in arquivo.read_text(encoding="utf-8", errors="replace")
        or "import sentury" in arquivo.read_text(encoding="utf-8", errors="replace")
    ]
    return EvalResult("plugin não depende do host", not ofensores,
                      f"importam o host: {ofensores}" if ofensores else "independente")


async def _eval_prefixo_estavel_antes_do_variavel() -> EvalResult:
    """O cache do provedor só vale enquanto o prefixo for idêntico. O que muda
    por pedido (o modo, a data) não pode entrar no prefixo estável."""
    import inspect

    from ..harness import chamada_da_volta

    estavel = inspect.getsource(chamada_da_volta.prompt_estavel)
    variavel = inspect.getsource(chamada_da_volta.contexto_do_turno)
    ok = ("build_artifact_prompt()" in estavel and "Catálogo de Skills Procedurais" in estavel
          and "_MODOS" in variavel and "_MODOS" not in estavel
          and "DATA_DE_REFERENCIA" in variavel and "DATA_DE_REFERENCIA" not in estavel)
    return EvalResult("prefixo estável vem antes do variável", ok, "ordem preservada" if ok else "algo variável entrou no prefixo")


async def _eval_hook_nao_e_autorizacao() -> EvalResult:
    """Declarar um hook diz QUANDO um comando roda, não dá o direito de
    rodá-lo. Um gatilho que contorna a permissão seria uma porta dos fundos."""
    from ..harness import hooks

    fonte = hooks.disparar.__doc__ or ""
    # A prova real está no teste unitário; aqui garantimos que o caminho passa
    # pelo shell (que consulta a permissão), e não por subprocess direto.
    import inspect
    corpo = inspect.getsource(hooks.disparar)
    ok = "from ..tools.shell import executar" in corpo and "subprocess" not in corpo
    return EvalResult("hook não contorna a permissão", ok,
                      "usa o shell com política" if ok else "caminho paralelo detectado")


async def _eval_descoberta_nao_depende_do_idioma() -> EvalResult:
    """Pedido chinês misturado com Python escondia `ler_arquivo`: BM25 oferecia
    schemas de código e a rede de segurança repetia a busca que já falhara.
    O manifesto e o carregamento pelo nome precisam dar acesso à ferramenta
    mesmo quando nenhuma palavra do pedido casa com a descrição portuguesa.
    Isto mede o contrato local; a compreensão da LLM é outra bancada.
    """
    from .descoberta_multilingue import medir_acesso

    medidas = [r for r in medir_acesso() if r["acesso"] is not None]
    acertos = sum(bool(r["acesso"]) for r in medidas)
    return EvalResult("capacidade continua acessível entre idiomas", acertos == len(medidas),
                      f"{acertos}/{len(medidas)} acessíveis por manifesto e nome exato")


CASOS_DE_REGRESSAO: List[Callable[[], Any]] = [
    _eval_poda_economiza_de_verdade,
    _eval_poda_preserva_a_procedencia,
    _eval_cache_do_provedor_e_medido,
    _eval_todo_provedor_publica_o_que_gastou,
    _eval_segredo_nao_e_legivel_por_comando,
    _eval_escrita_exige_autorizacao,
    _eval_politica_ilegivel_fecha_tudo,
    _eval_busca_web_funciona_sem_chave,
    _eval_comando_longo_nao_morre,
    _eval_diagrama_e_reconhecido,
    _eval_plugin_nao_depende_do_host,
    _eval_prefixo_estavel_antes_do_variavel,
    _eval_hook_nao_e_autorizacao,
    _eval_descoberta_nao_depende_do_idioma,
]


async def run_regressoes() -> List[EvalResult]:
    resultados = []
    for caso in CASOS_DE_REGRESSAO:
        try:
            resultados.append(await caso())
        except Exception as exc:
            resultados.append(EvalResult(caso.__name__, False, f"exceção: {exc}"))
    return resultados
