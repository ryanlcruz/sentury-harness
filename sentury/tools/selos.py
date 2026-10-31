"""Classifica a capacidade e a intenção de cada ferramenta para a interface.

Nomes exatos prevalecem sobre prefixos, que podem confundir casos especiais.
"""
from __future__ import annotations


# Remover, mover e buscar conteúdo externo têm efeitos distintos na interface.
TOOL_KINDS = ("read", "execute", "edit", "delete", "move", "search", "fetch", "other")

# Onde o prefixo nao alcanca. Nao e para virar catalogo: e a lista curta do
# que a tela mostra toda hora e o prefixo classificava errado.
_KIND_POR_NOME = {
    # A policy decide o risco pela acao interna; para a linha do tempo, a
    # capability continua sendo acesso a uma pagina, nao um comando local.
    "browser": "fetch",
    "ler_arquivo": "read",
    "listar_arquivos": "read",
    "listar_memorias": "read",
    # A ação interna determina o risco; este selo indica a capacidade geral.
    "memoria": "edit",
    "listar_skills": "read",
    "list_schedules": "read",
    "running_commands": "read",
    "command_status": "read",
    "mapa_do_arquivo": "read",
    "onde_definido": "read",
    "quem_usa": "read",
    "diagnosticos": "read",
    "percorrer_chamadas": "read",
    "historico_do_arquivo": "read",
    "restaurar_versao": "edit",
    "ver_plano": "read",
    "ver_workflow": "read",
    "checar_pacote": "read",
    "compare_periods": "read",
    "escrever_arquivo": "edit",
    "editar_arquivo": "edit",
    "status_da_tarefa": "edit",
    # Registrar, abrir e fechar gravam o lote em disco: o mesmo selo do plano.
    "missao": "edit",
    # Propor, marcar e declarar gravam o goal em disco; ligar o executor nao
    # passa por aqui (e da pessoa, pela tela).
    "goal": "edit",
    # Mouse e teclado de verdade: o gesto executa, mesmo quando so le a tela.
    "computador": "execute",
    "schedule_task": "edit",
    "cancel_schedule": "delete",
    "entregar_arquivo": "execute",
    "executive_summary": "execute",
    "usar_mcp": "fetch",
    # Perguntar nao le, nao altera e nao executa: e o unico que para o
    # turno e espera gente. `other` aqui e o valor certo, e esta escrito
    # para ninguem "consertar" depois.
    "perguntar_usuario": "other",
}

# O que a acao SIGNIFICA, independente de qual funcao a executou. `kind`
# responde "como desenho isto"; o intent responde "o que o agente estava
# tentando fazer", e sao perguntas diferentes: `export_pdf` e `export_xlsx`
# tem kinds iguais e sao a mesma intencao, enquanto `executar_python` e
# `analyze_nps` executam de formas opostas com a mesma intencao de medir.
ACTION_INTENTS = (
    "medir", "investigar", "recomendar", "entregar", "consultar",
    "alterar", "executar", "perguntar", "pensar", "outro",
)

# Nome exato vence prefixo.
_INTENT_POR_NOME = {
    "browser": "executar",
    "correlate": "investigar",
    "generate_insights": "investigar",
    "generate_recommendations": "recomendar",
    "executive_summary": "recomendar",
    "executar_python": "executar",
    "executar_comando": "executar",
    "executar_script": "executar",
    "executar_skill": "executar",
    "perguntar_usuario": "perguntar",
    "search_tools": "consultar",
    "entregar_arquivo": "entregar",
    "gerar_imagem": "entregar",
    "generate_chart": "entregar",
    "save_analysis": "alterar",
    "schedule_task": "alterar",
    "cancel_schedule": "alterar",
    "kill_command": "alterar",
    "checar_pacote": "consultar",
    "memoria": "alterar",
    # O plano: ver e consultar; criar e marcar alteram o que esta em disco.
    "diagnosticos": "consultar",
    "percorrer_chamadas": "consultar",
    "historico_do_arquivo": "consultar",
    "restaurar_versao": "alterar",
    "ver_plano": "consultar",
    "ver_workflow": "consultar",
    "criar_plano": "alterar",
    "criar_workflow": "alterar",
    "status_da_tarefa": "alterar",
    "missao": "alterar",
    "goal": "alterar",
    "computador": "executar",
    "usar_mcp": "executar",
}

_INTENT_POR_PREFIXO = (
    ("analyze_", "medir"),
    ("compare_", "medir"),
    ("export_", "entregar"),
    ("buscar_", "consultar"),
    ("consultar_", "consultar"),
    ("listar_", "consultar"),
    ("ler_", "consultar"),
    ("mapa_", "consultar"),
    ("onde_", "consultar"),
    ("quem_", "consultar"),
    ("pesquisar", "consultar"),
    ("command_", "consultar"),
    ("running_", "consultar"),
    ("list_", "consultar"),
    ("criar_", "alterar"),
    ("atualizar_", "alterar"),
    ("escrever_", "alterar"),
    ("editar_", "alterar"),
    ("salvar_", "alterar"),
    ("esquecer_", "alterar"),
)

def _do_registro(nome: str, campo: str) -> str:
    """Propriedade declarada no tools.yaml, o do setor inclusive: ferramenta de
    setor nao entra nas tabelas daqui."""
    try:
        from .registry import TOOL_REGISTRY

        return str((TOOL_REGISTRY.get(nome) or {}).get(campo) or "")
    except Exception:
        return ""


def intent_da_ferramenta(tool: str) -> str:
    """A intencao da acao, em vocabulario fechado.

    Deriva do nome, com o mapa explicito vencendo o prefixo: os casos em que
    o nome mente sobre a intencao sao poucos e cabem numa tabela, e uma
    tabela e auditavel de um jeito que heuristica nao e.
    """
    nome = str(tool or "").strip().lower()
    if not nome:
        return "outro"
    # Ferramenta de pacote de setor (`coder.algo`) herda pelo sufixo.
    if "." in nome:
        nome = nome.split(".", 1)[1]
    if nome in _INTENT_POR_NOME:
        return _INTENT_POR_NOME[nome]
    declarada = _do_registro(nome, "intencao")
    if declarada:
        return declarada
    for prefixo, intencao in _INTENT_POR_PREFIXO:
        if nome.startswith(prefixo):
            return intencao
    return "outro"


def kind_da_ferramenta(tool: str) -> str:
    """Devolve um tipo validado pelo mesmo vocabulário usado no client.

    Um valor novo não deve chegar à tela sem representação visual.
    """
    n = str(tool or "").lower()
    # Nome antes de prefixo. O prefixo acerta a familia e erra o caso: as
    # tres ferramentas de arquivo que mais aparecem na tela: ler, escrever
    # e editar: nao tem prefixo em comum com nada e caiam todas em
    # `other`, ou seja a tela desenhava escrita igual a leitura.
    na_mao = _KIND_POR_NOME.get(n) or _do_registro(n, "tipo_na_tela")
    if na_mao:
        return na_mao
    # Apagar antes de editar: `esquecer_memoria` comeca com "esquecer_" e
    # nao e edicao, e a ordem dos prefixos e o que decide.
    if n.startswith(("esquecer_", "apagar_", "remover_", "delete_")) or n == "kill_command":
        return "delete"
    if n.startswith(("mover_", "renomear_", "move_", "rename_")):
        return "move"
    if n.startswith(("buscar_web", "ler_pagina", "fetch_", "web_")):
        return "fetch"
    if n.startswith(("executar_", "gerar_", "export", "generate_", "save_", "render_")):
        return "execute"
    if n.startswith(("buscar_", "consultar_", "search_", "pesquisar")):
        return "search"
    if n.startswith(("atualizar_", "criar_", "registrar_", "salvar_")):
        return "edit"
    if n.startswith(("analyze_", "analisar_", "comparar_", "correlate", "priorizar_")):
        return "read"
    return "other"


__all__ = [
    "ACTION_INTENTS", "TOOL_KINDS", "intent_da_ferramenta", "kind_da_ferramenta",
]
