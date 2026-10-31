"""Dispatcher de ferramentas do Harness: a LLM PROPÕE um nome de ferramenta e
argumentos, `harness.policy` DECIDE se pode rodar, e só então `execute_tool`
chama o código real. Ferramentas de análise leem o dataset direto; as de
renderização/exportação recomputam o resultado já registrado na sessão a
partir da receita (nunca exportam um número que a LLM tenha inventado)."""
import asyncio
from datetime import date
from typing import Any, Dict, List, Optional

from .. import renderers as _renderers
from ..harness.policy import ACTION_TOOLS, ANALYSIS_TOOLS, EXPORT_TOOLS, KNOWN_TOOLS
from ..harness.state import AnalysisState
from ..renderers.shape import tabela_e_resumo
from .registry import com_propriedade

TOOL_NAMES = KNOWN_TOOLS

# Resultado com TABELA numérica plotável: o "gráfico disso" reaproveita a
# última análise plotável quando o último resultado não tem tabela (plano,
# insights). Quem declara é o `tools.yaml` do setor (`fonte_de_grafico`,
# `fonte_de_export`).
CHARTABLE_SOURCE_TOOLS = com_propriedade("fonte_de_grafico")
EXPORT_SOURCE_TOOLS = CHARTABLE_SOURCE_TOOLS | com_propriedade("fonte_de_export")
HTML_SOURCE_TOOLS = EXPORT_SOURCE_TOOLS


def _public_sandbox_result(result: Any) -> Any:
    """Keep executed sandbox source out of LLM-visible tool context.

    The full source is useful to the sandbox implementation, but it is neither
    analysis data nor a replayable session recipe. Returning it caused large
    HTML/base64-producing programs to be persisted as context anchors.
    """
    if not isinstance(result, dict):
        return result
    return {key: value for key, value in result.items() if key not in {"codigo", "code"}}


def _pasta_do_codigo(tool: str, arguments: Dict[str, Any]):
    """A pasta onde navegar o codigo, pela mesma porta do `ler_arquivo`.
    Sem `pasta`, a pasta de trabalho."""
    from .arquivos import PastaNaoLiberada, _pedir_a_pasta, _resolver, raiz_de_trabalho

    pasta = str(arguments.get("pasta") or arguments.get("diretorio") or "").strip()
    if not pasta:
        return str(raiz_de_trabalho()), None
    try:
        return str(_resolver(pasta)), None
    except PastaNaoLiberada as fora:
        return "", _pedir_a_pasta(fora, tool)
    except Exception as exc:
        return "", {"ok": False, "erro": str(exc)}


def _parse_data(valor: Optional[str]) -> Optional[date]:
    if not valor or str(valor).strip().lower() in ("null", "none", ""):
        return None
    try:
        return date.fromisoformat(str(valor).strip())
    except ValueError:
        return None


async def execute_tool(
    store: Any,
    state: AnalysisState,
    tool: str,
    arguments: Dict[str, Any],
    knowledge: Any = None,
    memory: Any = None,
    experience: Any = None,
    sessions: Any = None,
) -> Any:
    """Executa a ferramenta com o prazo dela. Ver tools/prazo.py."""
    from ..harness.gravacao_do_turno import (
        EM_REPLAY, REPLAY_BLOQUEIOS, REPLAY_FERRAMENTAS, anotar_resultado, resultado_gravado,
    )
    from .registry import TOOL_REGISTRY

    # `determinista` diz se a resposta se repete; nao diz se a ferramenta
    # altera arquivos, agenda ou o computador. No replay so roda de novo a
    # leitura revista no registro; o resto devolve o que a producao gravou,
    # e sem gravacao para o mesmo pedido e recusado antes de qualquer efeito.
    gravado = None
    if EM_REPLAY.get() and TOOL_REGISTRY.get(tool, {}).get("replay_leitura") is not True:
        fila = REPLAY_FERRAMENTAS.get()
        gravado = fila.servir(tool, arguments or {}) if fila is not None else None
        if gravado is None:
            bloqueios = REPLAY_BLOQUEIOS.get()
            if bloqueios is not None:
                bloqueios.append(tool)
            raise RuntimeError(f"replay recusou ferramenta sem leitura aprovada nem resultado gravado: {tool}")

    from ..harness import registro_do_turno as registro
    from ..harness.instrucoes_do_projeto import ao_tocar
    from ..harness.turno_em_curso import na_ferramenta
    from .prazo import com_prazo
    from .registry import interrompivel

    # O Parar do chat sabe o que roda: escrita não é cortada no meio, o turno
    # para na saída dela. Ver harness/turno_em_curso.py. E cada ferramenta é
    # um passo do registro do turno (harness/registro_do_turno.py).
    sessao, pode_cortar = getattr(state, "session_id", ""), interrompivel(tool, arguments)
    with na_ferramenta(sessao, tool, pode_cortar):
        registro.passo_comecou(sessao, tool, arguments, efeito_colateral=not pode_cortar)
        try:
            if gravado is not None:
                resultado = resultado_gravado(gravado)
            else:
                resultado = await com_prazo(tool, _executar_ferramenta(
                    store, state, tool, arguments, knowledge, memory, experience, sessions,
                ), arguments)
        except asyncio.CancelledError:
            registro.passo_acabou(sessao, "cortado")
            raise
        except Exception as exc:
            registro.passo_acabou(sessao, "erro")
            anotar_resultado(tool, arguments, erro=str(exc), tipo_erro=type(exc).__name__)
            raise
        registro.passo_acabou(sessao, registro.status_do_resultado(resultado))
    anotar_resultado(tool, arguments, resultado)
    # O diff de arquivo criado ou editado vai para a tela, e nao para o
    # modelo. Ver tools/diff_de_arquivo.py.
    if isinstance(resultado, dict) and "diff_para_a_tela" in resultado:
        diff = resultado.pop("diff_para_a_tela")
        if diff:
            from ..harness.emissor import emitir

            emitir({"type": "diff", "ferramenta": tool, **diff})
    # Comando, script e codigo: a saida inteira vai ao card como terminal, e
    # as linhas em ordem nao vao ao modelo. Ver tools/saida_da_tela.py.
    from .saida_da_tela import emitir_final

    emitir_final(tool, resultado)
    # Tocou numa pasta de projeto: o Sentury.md, CLAUDE.md ou AGENTS.md dela
    # entra na conversa. Ver harness/instrucoes_do_projeto.py.
    from ..residentes.destino import caixa_obrigatoria
    from ..residentes.escopo import agente_do_turno

    if not (caixa_obrigatoria() and agente_do_turno()) and (
        not isinstance(resultado, dict) or resultado.get("modo") != "caixa"
    ):
        ao_tocar(state, arguments or {})
    return resultado


async def _executar_ferramenta(
    store, state, tool, arguments, knowledge=None, memory=None, experience=None, sessions=None,
):
    from ..residentes.escopo import agente_do_turno
    from ..residentes.controle_da_tela import passo

    agente = agente_do_turno()
    if agente:
        if tool == "browser" and arguments.get("acao") != "encerrar":
            from ..residentes.controle_da_tela import esperar_devolucao
            await esperar_devolucao(agente.nome)
            return await _executar_no_destino(store, state, tool, arguments, knowledge, memory, experience, sessions)
        async with passo(agente.nome):
            return await _executar_no_destino(store, state, tool, arguments, knowledge, memory, experience, sessions)
    return await _executar_no_destino(store, state, tool, arguments, knowledge, memory, experience, sessions)


async def _executar_no_destino(
    store, state, tool, arguments, knowledge=None, memory=None, experience=None, sessions=None,
):
    from .registry import TOOL_REGISTRY
    from ..residentes.caixa import tentar
    from ..residentes.destino import recusa as recusa_do_destino
    from .porta_do_plano import desvio

    meta = TOOL_REGISTRY.get(tool, {})
    bloqueio = recusa_do_destino(meta)
    if bloqueio is not None:
        return bloqueio
    recusa = desvio(tool, arguments)
    if recusa is not None:
        return recusa
    if meta.get("operacao_caixa") == "browser":
        from ..residentes.escopo import agente_do_turno

        if agente_do_turno():
            from ..residentes.browser_da_caixa import despachar
            return await despachar(arguments, state)
    resultado, aviso = await tentar(meta.get("operacao_caixa"), arguments)
    if resultado is not None:
        return resultado
    resultado = await _executar_local(store, state, tool, arguments, knowledge, memory, experience, sessions)
    if aviso and isinstance(resultado, dict):
        resultado = {**resultado, "aviso": aviso, "modo": "local"}
    return resultado


async def _executar_local(
    store: Any,
    state: AnalysisState,
    tool: str,
    arguments: Dict[str, Any],
    knowledge: Any = None,
    memory: Any = None,
    experience: Any = None,
    sessions: Any = None,
) -> Any:
    # Escrever um plano por codigo produz o arquivo e nao produz o estado.
    # Antes de qualquer despacho porque vale para todas as portas de escrita.
    from .porta_do_plano import desvio as _desvio_do_plano

    recusa = _desvio_do_plano(tool, arguments)
    if recusa is not None:
        return recusa

    if tool in _FUSOES:
        # Uma ferramenta com acao. As antigas continuam despachando para traco
        # gravado e chamada antiga.
        acoes = _FUSOES[tool]
        tool = acoes.get(str(arguments.get("acao") or "").strip().lower(), "")
        if not tool:
            nomes = list(acoes)
            return {"erro": f"acao deve ser {', '.join(nomes[:-1])} ou {nomes[-1]}"}

    # Ferramenta publicada por um pacote de setor. O prefixo (`coder.algo`) e
    # o que impede um pacote de sequestrar o nome de uma ferramenta nativa.
    if "." in tool:
        from ..domains.extensao import ContextoDoPacote
        from ..domains.extensao import executar as executar_do_setor, publicadas

        if tool in publicadas():
            # O store vai junto. Sem isto o pacote publicava ferramenta que nao
            # consultava nada: e ficava so o placeholder do exemplo.
            return await executar_do_setor(tool, arguments, ContextoDoPacote(
                setor=tool.split(".", 1)[0],
                store=store,
                session_id=str(getattr(state, "session_id", "") or ""),
            ))

    if tool not in KNOWN_TOOLS:
        raise ValueError(f"ferramenta desconhecida: {tool}")

    if tool == "inspecionar_ambiente":
        from .ambiente import inspecionar

        return await asyncio.to_thread(inspecionar, **arguments)

    if tool == "diagnosticos":
        # O feedback mais barato do ciclo: milissegundos contra os minutos da
        # suite, e apontando a linha em vez de um teste que falha longe.
        from .arquivos import raiz_de_trabalho
        from .diagnostico import de_muitos, do_arquivo

        raiz = str(raiz_de_trabalho())
        alvos = arguments.get("arquivos") or arguments.get("caminhos")
        if isinstance(alvos, str):
            alvos = [alvos]
        if alvos:
            return de_muitos([str(a) for a in alvos], raiz)
        unico = str(arguments.get("caminho") or arguments.get("arquivo") or "").strip()
        if not unico:
            return {"erro": "diga o caminho do arquivo a diagnosticar"}
        return do_arquivo(unico, raiz)

    if tool in ("historico_do_arquivo", "restaurar_versao"):
        sessao = str(getattr(state, "session_id", "") or "")

    if tool == "historico_do_arquivo":
        from ..memory import versoes as _versoes
        from .arquivos import _resolver

        caminho = str(arguments.get("caminho") or arguments.get("arquivo") or "").strip()
        if not caminho:
            # Sem caminho, a pergunta é a outra: "o que eu já mexi aqui?". O
            # `git status` não separa o que foi o agente do que foi o usuário,
            # e é essa separação que interessa antes de desfazer algo.
            tocados = _versoes.tocados(sessao)
            return {
                "ok": True, "arquivos": tocados,
                "nota": (
                    "peca caminho=<arquivo> para ver as versoes de um deles"
                    if tocados else "nenhum arquivo alterado nesta sessao"
                ),
            }
        try:
            alvo = _resolver(caminho)
        except Exception as exc:
            return {"erro": str(exc)}

        de = int(arguments.get("versao") or arguments.get("de") or 0)
        if de:
            return _versoes.diferenca(
                alvo, de, int(arguments.get("comparar_com") or 0), session_id=sessao,
            )
        lista = _versoes.versoes(alvo, session_id=sessao)
        return {
            "ok": True, "caminho": str(alvo), "versoes": lista,
            "nota": (
                "peca versao=<n> para ver o diff daquela versao ate agora"
                if lista else
                "nenhuma versao guardada: este arquivo nao foi alterado pelo agente"
            ),
        }

    if tool == "restaurar_versao":
        # Restaurar e uma escrita, e passa pelo mesmo portao que qualquer
        # escrita: em vez de abrir uma segunda porta que ninguem lembraria de
        # fechar junto com a primeira.
        from ..memory import versoes as _versoes
        from .arquivos import _resolver, escrever

        caminho = str(arguments.get("caminho") or arguments.get("arquivo") or "").strip()
        versao = int(arguments.get("versao") or 0)
        if not caminho or not versao:
            return {"erro": "diga o caminho e o numero da versao"}
        try:
            alvo = _resolver(caminho)
        except Exception as exc:
            return {"erro": str(exc)}
        dados = _versoes.conteudo(alvo, versao, session_id=sessao)
        if dados is None:
            return {"erro": f"versao {versao} nao existe para este arquivo"}
        feito = escrever(
            str(alvo), dados.decode("utf-8", errors="replace"), session_id=sessao,
        )
        if feito.get("ok"):
            feito["restaurado_de"] = versao
        return feito

    if tool == "percorrer_chamadas":
        from .codigo import percorrer

        nome = str(arguments.get("nome") or arguments.get("simbolo") or "").strip()
        if not nome:
            return {"erro": "diga o nome da funcao a percorrer"}
        raiz, recusa = _pasta_do_codigo(tool, arguments)
        if recusa:
            return recusa
        return percorrer(
            nome,
            raiz,
            sentido=str(arguments.get("sentido") or "chamado_por").strip().lower(),
            profundidade=int(arguments.get("profundidade") or 2),
        )

    # Plano e workflow tem formatos parecidos, mas ciclos de vida diferentes.
    # Workflow nao e definido por cron: pode ser manual e persistente. Por isso
    # a ferramenta explicita decide o tipo; `gatilho` apenas acrescenta um
    # agendamento opcional ao workflow.
    _gatilho = ""
    if isinstance(arguments, dict):
        _gatilho = str(arguments.get("gatilho") or arguments.get("cron") or "").strip()
    if tool in ("criar_workflow", "ver_workflow"):
        from ..memory import workflow as _workflow

        nome = str(
            arguments.get("nome") or arguments.get("workflow")
            or arguments.get("plano") or arguments.get("titulo") or ""
        ).strip()
        if tool == "ver_workflow":
            return _workflow.resumo(nome) if nome else {"workflows": _workflow.listar()}
        # `tarefas` e o nome que `criar_plano` usa: quem entrou por aquela
        # porta nao deve ter o argumento recusado por causa do sinonimo.
        passos = arguments.get("passos") or arguments.get("tarefas") or []
        if isinstance(passos, str):
            passos = [linha for linha in passos.splitlines() if linha.strip()]
        criado = _workflow.criar(
            nome,
            str(arguments.get("porque") or arguments.get("motivo")
                or arguments.get("contexto") or ""),
            _gatilho,
            [str(p) for p in passos],
        )
        if not criado.get("ok"):
            return criado

        # Workflow nao implica cron. Sem gatilho ele e um processo persistente
        # iniciado manualmente; nao invente horario nem trate isso como falha.
        if not criado.get("gatilho"):
            return {
                **criado,
                "agendamento": None,
                "gatilho_registrado": False,
                "execucao_manual": True,
                "aguardando_aprovacao": True,
            }

        # Gatilho de relógio fecha o contrato inteiro aqui: receita no projeto
        # + cron persistente. Exigir que o modelo descubra e chame também
        # `schedule_task` produzia workflow sem disparo e cron sem receita,
        # dependendo de qual ferramenta ele escolhesse primeiro.
        #
        # Gatilho de evento ("quando chegar o relatório") não vira agendamento
        # e isso não é falha: agendar um evento seria inventar um horário que
        # ninguém pediu. A receita fica gravada e a resposta diz, em vez de
        # deixar a pessoa achar que aquilo dispara sozinho.
        from ..external import agendador

        agenda = agendador.agendar_workflow(
            session_id=str(getattr(state, "session_id", "") or ""),
            user_id=str(getattr(state, "user_id", "") or ""),
            workflow=criado["workflow"],
            gatilho=criado["gatilho"],
            ativo=False,
        )
        if agenda.get("ok"):
            return {
                **criado,
                "agendamento": agenda,
                "gatilho_registrado": True,
                "aguardando_aprovacao": True,
            }
        if agenda.get("por_evento"):
            return {
                **criado,
                "gatilho_registrado": False,
                "gatilho_por_evento": True,
                "aviso": (
                    "receita salva. O gatilho é por evento, não por relógio: "
                    "nada dispara sozinho ainda — rode com `ver_workflow` e "
                    "peça a execução, ou dê um horário para eu agendar."
                ),
            }
        return {
            **criado,
            "ok": False,
            "receita_criada": True,
            "erro": f"receita salva, mas o gatilho nao foi registrado: {agenda.get('erro')}",
        }

    if tool in ("criar_plano", "ver_plano", "status_da_tarefa"):
        # O plano e o que atravessa a sessao. Sem uma tool para marca-lo, o
        # arquivo em disco vira um documento que alguem escreveu uma vez.
        from ..memory import plano as _plano

        titulo = str(arguments.get("titulo") or "").strip()
        # Modelos usam `titulo` como identidade do plano mesmo com `nome`
        # obrigatório no schema. Recusar essa variação custou duas chamadas e
        # 142 s num workflow real; o módulo de plano já produz o slug seguro.
        nome = str(arguments.get("plano") or arguments.get("nome") or titulo).strip()

        if tool == "ver_plano":
            if not nome:
                return {"planos": _plano.listar()}
            return _plano.resumo(nome)

        if not nome:
            return {"erro": "diga o nome do plano"}

        if tool == "criar_plano":
            tarefas = arguments.get("tarefas") or []
            if isinstance(tarefas, str):
                tarefas = [l for l in tarefas.splitlines() if l.strip()]
            if not tarefas:
                return {"erro": "um plano sem tarefas nao e um plano"}
            return _plano.criar(
                nome,
                titulo or nome,
                [str(x) for x in tarefas],
                contexto=str(arguments.get("contexto") or ""),
            )

        return _plano.marcar(
            nome,
            str(arguments.get("tarefa") or arguments.get("id") or ""),
            str(arguments.get("estado") or "feito").strip().lower(),
            session_id=str(getattr(state, "session_id", "") or ""),
            nota=str(arguments.get("nota") or ""),
        )

    if tool == "missao":
        return _missao(arguments, state)

    if tool == "goal":
        return _goal(arguments, state)

    if tool in ("criar_agente", "pedir_ao_agente", "memoria_do_agente", "pedir_ferramenta", "falar_na_mesa",
                "abrir_assunto", "decisao"):
        from ..residentes.ferramentas import executar as _residentes

        return await _residentes(tool, arguments, state)

    if tool == "computador":
        from .computador import executar as _computador

        return await _computador(arguments, state)

    if tool == "search_tools":
        from ..harness.descoberta import consultar

        return consultar(state, arguments)

    if tool == "gerar_imagem":
        from ..config import settings as _settings
        from .imagem import gerar_imagem

        return await gerar_imagem(
            str(arguments.get("prompt") or arguments.get("descricao") or ""),
            _settings,
        )

    if tool == "browser":
        from .browser_contracts import Action
        from .browser_registry import despachar

        try:
            action = Action.de_argumentos(arguments)
        except ValueError as exc:
            return {"ok": False, "executado": False, "fase": "contrato", "motivo": str(exc)}
        from ..memory.estrategia import apos_browser

        return apos_browser(arguments, await despachar(
            action,
            state,
            provider_name=str(arguments.get("provider") or "").strip() or None,
        ), sessao=str(getattr(state, "session_id", "") or ""))

    if tool == "usar_mcp":
        from ..external import mcp_registry

        alvo = str(arguments.get("servidor") or "").strip()
        # Aceita id ou nome: o modelo le o nome na lista, nao o id opaco.
        spec = mcp_registry.obter(alvo) or next(
            (s for s in mcp_registry.listar() if str(s.get("nome", "")).lower() == alvo.lower()),
            None,
        )
        if spec is None:
            return {"ok": False, "erro": f"servidor MCP '{alvo}' nao esta registrado"}
        return await mcp_registry.chamar(
            spec,
            str(arguments.get("ferramenta") or arguments.get("tool") or ""),
            arguments.get("argumentos") or arguments.get("arguments") or {},
        )

    if tool == "buscar_web":
        from ..config import settings as _settings
        from .web import buscar, pesquisar

        consulta = str(arguments.get("consulta") or arguments.get("query") or "")
        profundidade = str(arguments.get("profundidade") or "rapida").strip().lower()
        profunda = profundidade == "profunda"

        def _inteiro_limitado(nome: str, padrao: int, minimo: int, maximo: int) -> int:
            try:
                return max(minimo, min(int(arguments.get(nome)), maximo))
            except (TypeError, ValueError):
                return padrao

        limite = _inteiro_limitado("limite", 15 if profunda else 5, 1, 20)
        paginas = _inteiro_limitado("paginas", 8 if profunda else 0, 0, 10)
        paginas = min(paginas, limite)
        if paginas:
            return await pesquisar(consulta, _settings, paginas=paginas, limite=limite)
        return await buscar(consulta, _settings, limite=limite)

    if tool == "subagentes":
        from .subagentes import consultar

        return await consultar(state, arguments or {})

    if tool == "ler_pagina":
        from ..memory.estrategia import apos_ler_pagina
        from .web import ler_pagina

        url = str(arguments.get("url") or "")
        try:
            parte = int(arguments.get("parte") or 1)
        except (TypeError, ValueError):
            parte = 1
        resultado = await ler_pagina(url, parte=parte, procurar=str(arguments.get("procurar") or ""))
        return apos_ler_pagina(url, resultado, sessao=str(getattr(state, "session_id", "") or ""))

    if tool == "executar_comando":
        from ..config import settings as _settings
        from .shell import executar

        from .saida_da_tela import AoVivo

        # Escrita nunca vem do plano: exige aprovacao explicita no passo, que
        # o plano sozinho nao carrega. Roda numa thread: esperar o comando no
        # laco de eventos travava o servidor inteiro, e a saida ao vivo nao
        # tinha como sair.
        ao_vivo = AoVivo(tool)
        try:
            return await asyncio.to_thread(
                executar,
                str(arguments.get("comando") or arguments.get("command") or ""),
                habilitado=bool(getattr(_settings, "SENTURY_SHELL", False)),
                permitir_escrita=False,
                timeout=float(arguments.get("timeout") or 60.0),
                session_id=str(getattr(state, "session_id", "") or ""),
                ao_linha=ao_vivo,
                shell=str(arguments.get("shell") or ""),
            )
        finally:
            ao_vivo.encerrar()

    if tool == "executar_script":
        from ..config import settings as _settings
        from .script import executar_script

        from .saida_da_tela import AoVivo

        argumentos = arguments.get("argumentos") or arguments.get("args") or []
        ao_vivo = AoVivo(tool)
        try:
            return await asyncio.to_thread(
                executar_script,
                str(arguments.get("conteudo") or arguments.get("content") or arguments.get("codigo") or ""),
                str(arguments.get("linguagem") or arguments.get("language") or ""),
                arquivo=str(arguments.get("arquivo") or arguments.get("file") or "") or None,
                argumentos=list(argumentos) if isinstance(argumentos, (list, tuple)) else [],
                diretorio=str(arguments.get("diretorio") or arguments.get("cwd") or "") or None,
                timeout=float(arguments.get("timeout") or 120.0),
                habilitado=bool(getattr(_settings, "SENTURY_SHELL", False)),
                session_id=str(getattr(state, "session_id", "") or ""),
                ao_linha=ao_vivo,
            )
        finally:
            ao_vivo.encerrar()

    if tool in ("schedule_task", "list_schedules", "cancel_schedule"):
        from ..external import agendador

        sessao = str(getattr(state, "session_id", "") or "")
        if tool == "list_schedules":
            return agendador.listar(sessao)
        if tool == "cancel_schedule":
            return agendador.cancelar(str(arguments.get("id") or arguments.get("job_id") or ""))
        if "workflow" in (getattr(state, "funcoes_ativas", None) or []):
            return {
                "ok": False,
                "erro": (
                    "@workflow esta ativo: use criar_workflow com nome e passos. "
                    "So envie gatilho quando o usuario tambem pediu agendamento"
                ),
            }
        bruto = arguments.get("intervalo_seg") or arguments.get("interval_sec")
        return agendador.agendar(
            session_id=sessao,
            user_id=str(getattr(state, "user_id", "") or ""),
            tarefa=str(arguments.get("tarefa") or arguments.get("prompt") or ""),
            cron=str(arguments.get("cron") or arguments.get("cron_expr") or ""),
            intervalo_seg=int(bruto) if bruto else None,
            quando=str(arguments.get("quando") or ""),
            executar_em=str(arguments.get("executar_em") or arguments.get("run_at") or ""),
        )

    if tool in ("onde_definido", "quem_usa", "mapa_do_arquivo"):
        from . import codigo

        alvo_nome = str(arguments.get("nome") or arguments.get("simbolo") or "")
        if tool in ("onde_definido", "quem_usa"):
            raiz, recusa = _pasta_do_codigo(tool, arguments)
            if recusa:
                return recusa
            buscar = codigo.definicoes if tool == "onde_definido" else codigo.referencias
            return buscar(alvo_nome, raiz)
        return codigo.mapa(str(arguments.get("caminho") or arguments.get("arquivo") or ""))

    if tool == "checar_pacote":
        from . import dependencias

        return await dependencias.verificar(
            str(arguments.get("pacote") or ""),
            str(arguments.get("ecossistema") or "PyPI"),
            str(arguments.get("versao") or ""),
        )

    if tool == "entregar_arquivo":
        from . import arquivos

        return arquivos.entregar(str(arguments.get("caminho") or arguments.get("path") or ""))

    if tool in ("ler_arquivo", "listar_arquivos", "escrever_arquivo", "editar_arquivo"):
        from . import arquivos

        sessao = str(getattr(state, "session_id", "") or "")
        caminho = str(arguments.get("caminho") or arguments.get("path") or "")
        if tool == "ler_arquivo":
            return arquivos.ler(
                caminho,
                inicio=int(arguments.get("inicio") or 1),
                linhas=int(arguments.get("linhas") or 0),
            )
        if tool == "listar_arquivos":
            return arquivos.listar(caminho or ".", padrao=str(arguments.get("padrao") or "*"))
        if tool == "escrever_arquivo":
            return arquivos.escrever(
                caminho, str(arguments.get("conteudo") or ""), session_id=sessao,
            )
        return arquivos.editar(
            caminho,
            str(arguments.get("antes") or ""),
            str(arguments.get("depois") or ""),
            session_id=sessao,
            todas=bool(arguments.get("todas")),
        )

    if tool == "command_status":
        from .processos import estado

        return estado(str(arguments.get("id") or arguments.get("processo") or ""))

    if tool == "running_commands":
        from .processos import listar

        return {"processos": listar(apenas_rodando=bool(arguments.get("apenas_rodando", True)))}

    if tool == "kill_command":
        from .processos import encerrar

        return encerrar(str(arguments.get("id") or arguments.get("processo") or ""))

    if tool == "buscar_conhecimento":
        # Leitura de corpus conceitual (RAG/FAQ). Não toca o dataset e não vira
        # um "resultado" exportável: não registramos na sessão.
        consulta = arguments.get("consulta") or arguments.get("pergunta") or ""
        # O manual (ferramentas e skills) vem primeiro: e o que o modelo busca
        # quando trava ("como rodo git aqui?"). A base de conceitos vem junto.
        from ..knowledge.manual import manual

        achados = manual().buscar(consulta)
        if knowledge is not None:
            achados += knowledge.buscar(consulta)
        if experience is not None and hasattr(experience, "buscar"):
            achados += await experience.buscar(consulta)
        return achados

    if tool == "consultar_experiencia":
        # O modelo consulta experiências quando a tarefa pede esse contexto.
        if experience is None:
            return {"encontrada": False, "motivo": "biblioteca de experiencia indisponivel"}
        exp = await experience.find_similar(
            arguments.get("intent") or "ANALYSIS",
            arguments.get("consulta") or arguments.get("pergunta") or "",
        )
        if not exp:
            return {"encontrada": False}
        return {"encontrada": True, "fluxo": exp.get("flow"), "intent": exp.get("intent")}

    if tool == "buscar_conversas":
        # Busca conversas anteriores, não procedimentos aprendidos.
        # O escopo por usuário exclui outras pessoas e a sessão corrente.
        if sessions is None:
            return {"encontrou": False, "motivo": "indice de sessoes indisponivel"}
        achados = await sessions.search(
            state.user_id,
            arguments.get("consulta") or arguments.get("pergunta") or "",
            limite=int(arguments.get("limite", 5)),
            excluir=state.session_id,
        )
        return {"encontrou": bool(achados), "conversas": achados}

    if tool == "memoria":
        # Uma ferramenta com acao. As tres antigas continuam despachando para
        # traco gravado e chamada antiga.
        acao = str(arguments.get("acao") or "").strip().lower()
        if acao == "ler":
            if memory is None or not hasattr(memory, "ler"):
                return {"erro": "memória indisponível"}
            item = await memory.ler(state.user_id, str(arguments.get("nome") or ""))
            return item or {"erro": "não há item com esse nome; `listar` mostra os nomes"}
        tool = _ACOES_DA_MEMORIA.get(acao, "")
        if not tool:
            return {"erro": "acao deve ser salvar, ler, listar ou esquecer"}
    if tool in {"salvar_memoria", "esquecer_memoria", "listar_memorias"}:
        return await _executar_memoria(memory, state.user_id, tool, arguments, sessao=state.session_id)

    if tool == "aprender_skill":
        from ..skills.escrita import executar as _aprender

        return _aprender(arguments)

    if tool == "find_skills":
        from ..skills.de_fora import executar as _de_fora

        return await _de_fora(arguments, getattr(state, "session_id", ""))

    if tool in ANALYSIS_TOOLS:
        result = await _executar_analise(store, tool, arguments)
        if tool == "executar_python":
            return _public_sandbox_result(result)
        _registrar_se_houver_dados(state, tool, arguments, result)
        return result

    if tool == "save_analysis":
        return _salvar_analise(state, arguments)

    if tool in EXPORT_TOOLS:
        return await _executar_exportacao(store, state, tool, arguments)

    # Estar no registro não significa ter executor neste dispatcher: ferramenta
    # que o harness intercepta (como `perguntar_usuario`) e chega aqui indica
    # costura ausente, e o erro precisa dizer isso.
    raise ValueError(f"ferramenta conhecida, mas sem executor no catálogo: {tool}")


async def _executar_analise(store: Any, tool: str, arguments: Dict[str, Any]) -> Any:
    if tool == "executar_python":
        from ..exec.python_exec import executar_python

        return await executar_python(store, arguments.get("codigo") or arguments.get("code", ""))
    # As análises são do setor: quem conhece os argumentos delas é o pacote.
    from ..domains.do_setor import executar_analise

    return await executar_analise(store, tool, arguments)


def _row_count(result: Any) -> int:
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        for chave in ("volume", "n_pontos"):
            if chave in result:
                return int(result[chave])
        return 1
    return 0


def _registrar_se_houver_dados(state: AnalysisState, tool: str, arguments: Dict[str, Any], result: Any) -> None:
    # Código de sandbox pode produzir arquivos, mas não é uma receita segura de
    # análise/exportação. Nunca deve virar âncora de sessão ou voltar ao modelo.
    if tool == "executar_python":
        return
    # Falhas de ferramenta não viram resultado de referência da sessão.
    # Assim pedidos posteriores de gráfico ou exportação não usam um erro como fonte.
    if isinstance(result, dict) and result.get("erro"):
        try:
            from ..observability import record_intervention
            record_intervention("tool_error", detail=f"{tool}: {str(result.get('erro'))[:80]}")
        except Exception:
            pass
        return
    row_count = _row_count(result)
    if row_count == 0:
        return
    _, resumo = tabela_e_resumo(tool, result)
    state.register_result(tool, arguments, resumo, row_count)


_FUSOES = {
    "codigo": {"mapa": "mapa_do_arquivo", "definicao": "onde_definido",
               "referencias": "quem_usa", "chamadas": "percorrer_chamadas"},
    "processos": {"listar": "running_commands", "ver": "command_status", "encerrar": "kill_command"},
    "agenda": {"agendar": "schedule_task", "listar": "list_schedules", "cancelar": "cancel_schedule"},
}
_ACOES_DA_MEMORIA = {"salvar": "salvar_memoria", "listar": "listar_memorias",
                     "esquecer": "esquecer_memoria"}


async def _executar_memoria(
    memory: Any, user_id: str, tool: str, arguments: Dict[str, Any], sessao: Optional[str] = None,
) -> Any:
    if memory is None:
        return {"status": "memória indisponível"}
    if tool == "listar_memorias":
        return await memory.all(user_id)
    if tool == "esquecer_memoria":
        removidos = await memory.forget(user_id, arguments.get("termo"))
        return {"removidos": removidos}
    # salvar_memoria
    fato = (arguments.get("fato") or arguments.get("texto") or "").strip()
    if not fato:
        raise ValueError("fato é obrigatório para salvar na memória")
    extras = {k: str(arguments[k]).strip() for k in ("tipo", "nome", "descricao") if arguments.get(k)}
    if not extras.get("nome") and hasattr(memory, "parecido"):
        # Parecido já guardado: o modelo decide se é atualização ou outro assunto.
        perto = await memory.parecido(user_id, fato)
        if perto is not None:
            return {"status": "não salvo", "parecido": {"nome": perto["nome"], "texto": perto["texto"]},
                    "saida": (f"se é atualização, salve de novo com nome '{perto['nome']}'; "
                              "se é outro assunto, salve com um nome próprio")}
    salvo = await memory.remember(user_id, fato, sessao=sessao, **extras)
    return {"status": "salvo" if salvo else "já estava na memória", "fato": fato}


_MOSTRAR_PROXIMAS = 10


def _unidades_do_argumento(bruto: Any) -> List[tuple]:
    """`[{alvo, item}]` ou `["alvo::item"]`: o modelo escreve dos dois jeitos."""
    pares = []
    for u in bruto or []:
        if isinstance(u, dict):
            alvo, item = str(u.get("alvo") or "").strip(), str(u.get("item") or "").strip()
        else:
            alvo, _, item = str(u).partition("::")
            alvo, item = alvo.strip(), item.strip()
        if alvo:
            pares.append((alvo, item))
    return pares


def _situacao_da_missao(missao: Any) -> Dict[str, Any]:
    proximas = missao.proximas()
    return {
        **missao.resumo(),
        "faltam": len(proximas),
        # So as primeiras: com 20 unidades, a lista inteira em todo resultado
        # ocupa o contexto que o turno precisa para a unidade da vez.
        "proximas": [
            {k: r.get(k) for k in ("alvo", "item", "estado", "tentativas")}
            for r in proximas[:_MOSTRAR_PROXIMAS]
        ],
    }


def _missao(arguments: Dict[str, Any], state: AnalysisState) -> Dict[str, Any]:
    """A `Missao` de `memory/unidades.py`, exposta ao modelo.

    Ela existia e nenhuma ferramenta a usava: o case da vaga tem 5 vagas x 4
    fontes = 20 unidades, que nao cabem num turno, e sem registrar/abrir/fechar
    o turno seguinte nao sabe onde o anterior parou.
    """
    from ..memory import unidades as _unidades

    acao = str(arguments.get("acao") or "ver").strip().lower()
    if acao not in ("registrar", "abrir", "fechar", "ver"):
        return {"erro": f"acao '{acao}' nao existe: use registrar, abrir, fechar ou ver"}
    nome = str(arguments.get("missao") or arguments.get("nome") or "").strip()
    if acao == "ver" and not nome:
        return {"missoes": _unidades.listar()}
    if not nome:
        return {"erro": "diga o nome da missao"}
    missao = _unidades.Missao(nome)

    if acao == "registrar":
        pares = _unidades_do_argumento(arguments.get("unidades"))
        if not pares:
            return {"erro": "registrar precisa de `unidades: [{alvo, item}]`"}
        return {"ok": True, "entraram": missao.registrar(pares), **_situacao_da_missao(missao)}

    if acao == "ver":
        return _situacao_da_missao(missao)

    alvo = str(arguments.get("alvo") or "").strip()
    item = str(arguments.get("item") or "").strip()
    if not alvo:
        return {"erro": f"{acao} precisa de `alvo` (e `item`, quando a unidade tem)"}

    if acao == "abrir":
        aberta = missao.abrir(alvo, item, sessao=str(getattr(state, "session_id", "") or ""))
        if aberta is not None:
            return {"ok": True, "unidade": aberta}
        # None tem tres razoes, e cada uma pede uma reacao diferente.
        atual = next((r for r in missao.unidades()
                      if r["alvo"] == alvo and r["item"] == item), None)
        if atual is None:
            return {"ok": False, "erro": "unidade nao registrada: use `registrar` antes"}
        if atual["estado"] == _unidades.REVISAR:
            return {"ok": False, "erro": "unidade esgotou as tentativas e foi para revisao; siga para a proxima",
                    "unidade": atual}
        return {"ok": False, "erro": f"unidade ja fechada ({atual['estado']}); siga para a proxima",
                "unidade": atual}

    if acao == "fechar":
        estado = str(arguments.get("estado") or _unidades.FEITO).strip().lower()
        evidencia = arguments.get("evidencia")
        if estado == _unidades.FEITO and not (str(evidencia).strip() if evidencia is not None else ""):
            # "Feito" sem o que prova e o que o dossie depois nao consegue
            # conferir. Descartar ou pedir ao usuario nao precisa de prova.
            return {"ok": False, "erro": "fechar como `feito` exige `evidencia` (URL, trecho ou arquivo)"}
        confianca = arguments.get("confianca")
        try:
            fechada = missao.fechar(
                alvo, item, estado, evidencia=evidencia,
                confianca=float(confianca) if confianca is not None else None,
                nota=str(arguments.get("nota") or ""),
            )
        except KeyError:
            return {"ok": False, "erro": "unidade nao registrada: use `registrar` antes"}
        except ValueError as exc:
            return {"ok": False, "erro": str(exc)}
        return {"ok": True, "unidade": fechada, **_situacao_da_missao(missao)}

    return {"erro": f"acao '{acao}' sem tratamento"}  # pragma: no cover - validada no topo


def _goal(arguments: Dict[str, Any], state: AnalysisState) -> Dict[str, Any]:
    """O goal da conversa (`memory/goals.py`), do lado do modelo.

    O modelo propoe, registra marco e declara cumprido: sempre com evidencia.
    Aprovar, pausar e confirmar sao da pessoa, pela tela: nao ha acao aqui que
    ligue o executor ou encerre o goal sozinha.
    """
    from ..memory import goals as _goals

    acao = str(arguments.get("acao") or "ver").strip().lower()
    if acao not in ("propor", "marco", "cumprido", "ver"):
        return {"erro": f"acao '{acao}' nao existe: use propor, marco, cumprido ou ver"}
    sessao = str(getattr(state, "session_id", "") or "")
    aberto = _goals.em_aberto(sessao)
    try:
        if acao == "propor":
            marcos = arguments.get("marcos") or []
            if isinstance(marcos, str):
                marcos = [m for m in marcos.splitlines() if m.strip()]
            goal = _goals.propor(
                sessao, str(getattr(state, "user_id", "") or ""),
                str(arguments.get("objetivo") or ""), str(arguments.get("criterio") or ""),
                [str(m) for m in marcos],
                limite_turnos=arguments.get("limite_turnos"),
                limite_horas=arguments.get("limite_horas"),
            )
            return {"ok": True, "goal": goal.publico(),
                    "proximo_passo": "a pessoa aprova na tela; ate la, nada roda sozinho. "
                                     "Diga em uma frase o que vai perseguir e como sabera que terminou."}
        if aberto is None:
            return {"ok": False, "erro": "esta conversa nao tem goal aberto"} if acao != "ver" \
                else {"goal": None}
        if acao == "ver":
            return {"goal": aberto.publico()}
        if aberto.estado not in (_goals.ATIVO, _goals.PAUSADO):
            return {"ok": False, "erro": f"o goal esta '{aberto.estado}': so ativo ou pausado aceita {acao}",
                    "goal": aberto.publico()}
        if acao == "marco":
            goal = _goals.marcar(aberto.id, str(arguments.get("titulo") or ""), arguments.get("evidencia"))
            return {"ok": True, "goal": goal.publico()}
        goal = _goals.declarar_cumprido(aberto.id, arguments.get("evidencia"))
        return {"ok": True, "goal": goal.publico(),
                "proximo_passo": "a pessoa confere a evidencia e confirma; mostre o que prova o criterio."}
    except _goals.GoalInvalido as exc:
        return {"ok": False, "erro": str(exc)}


def _salvar_analise(state: AnalysisState, arguments: Dict[str, Any]) -> Dict[str, Any]:
    result_id = state.resolve_source(arguments.get("source"))
    if result_id is None:
        raise ValueError("nenhum resultado disponível para salvar")
    nome = (arguments.get("nome") or "").strip() or result_id
    state.results[result_id]["nome"] = nome
    return {"source": result_id, "nome": nome}


async def _executar_exportacao(store: Any, state: AnalysisState, tool: str, arguments: Dict[str, Any]) -> Any:
    if tool in {"export_html", "export_xlsx", "export_csv", "export_pdf"}:
        multi_ids = _resolve_export_sources(state, arguments.get("fontes") or arguments.get("source"))
        if len(multi_ids) > 1:
            items = await _collect_export_items(store, state, multi_ids)
            if items:
                if tool == "export_html":
                    return _renderers.export_html_multi_dashboard(
                        items,
                        presentation_style=str(arguments.get("presentation_style") or "dashboard"),
                        request=str(arguments.get("request") or ""),
                    )
                if tool == "export_xlsx":
                    return _renderers.export_xlsx_multi(items, title="Analise integrada")
                if tool == "export_csv":
                    return _renderers.export_csv_multi(items)
                if tool == "export_pdf":
                    return _renderers.export_pdf_multi(items, title="Analise integrada")

    result_id = state.resolve_source(arguments.get("source"))
    if result_id is None:
        raise ValueError("nenhum resultado disponível para exportar/renderizar")

    # Se o resultado atual não contém tabela, busca a última análise plotável
    # para atender pedidos de gráfico ou representação textual.
    if tool in ("generate_chart", "export_html"):
        origem = state.results.get(result_id, {}).get("tool")
        if origem not in CHARTABLE_SOURCE_TOOLS:
            candidatos = [rid for rid, r in state.results.items() if r.get("tool") in CHARTABLE_SOURCE_TOOLS]
            if candidatos:
                result_id = max(candidatos, key=lambda r: state.results[r].get("created_at", 0))

    receita = state.results[result_id]
    tool_origem = receita["tool"]
    result = await _executar_analise(store, tool_origem, receita["arguments"])

    if tool == "generate_chart":
        png_bytes = await _renderers.generate_chart(tool_origem, result, tipo=arguments.get("tipo"))
        chart_data = _renderers.generate_chart_data(tool_origem, result, tipo=arguments.get("tipo"))
        return {
            "png_bytes": png_bytes,
            "chart_data": chart_data
        }

    if tool == "export_xlsx":
        return _renderers.export_xlsx(tool_origem, result)
    if tool == "export_csv":
        return _renderers.export_csv(tool_origem, result)
    if tool == "export_pdf":
        return _renderers.export_pdf(tool_origem, result)
    if tool == "export_html":
        return _renderers.export_html_dashboard(
            tool_origem,
            result,
            presentation_style=str(arguments.get("presentation_style") or "dashboard"),
            request=str(arguments.get("request") or ""),
        )
    raise ValueError(f"ferramenta desconhecida: {tool}")


def _resolve_export_sources(state: AnalysisState, source: Any) -> List[str]:
    if isinstance(source, (list, tuple)):
        resolved: List[str] = []
        for item in source:
            rid = state.resolve_source(item)
            if rid and rid not in resolved:
                resolved.append(rid)
        return resolved
    rid = state.resolve_source(source)
    return [rid] if rid else []


async def _collect_export_items(store: Any, state: AnalysisState, ids: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for rid in ids:
        receita_multi = state.results.get(rid) or {}
        tool_multi = receita_multi.get("tool")
        if tool_multi not in EXPORT_SOURCE_TOOLS:
            continue
        result_multi = await _executar_analise(store, tool_multi, receita_multi.get("arguments") or {})
        items.append({"result_id": rid, "tool": tool_multi, "result": result_multi})
    return items
