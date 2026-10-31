"""O inventário do motor fixa a relação entre registro, prompt e política."""
from sentury.harness.policy import KNOWN_TOOLS
from sentury.llm.prompts import SYSTEM_PERSONA
from sentury.tools.registry import TOOL_REGISTRY, ferramenta_exposta, sempre_exposta


def test_registry_matches_known_tools_exactly():
    # toda tool conhecida pela policy está documentada no registro, e vice-versa
    assert set(TOOL_REGISTRY) == set(KNOWN_TOOLS), (
        f"no registro mas não na policy: {set(TOOL_REGISTRY) - set(KNOWN_TOOLS)}; "
        f"na policy mas não no registro: {set(KNOWN_TOOLS) - set(TOOL_REGISTRY)}"
    )


def test_every_known_tool_is_described_in_system_prompt(monkeypatch):
    """O mapa de capacidades, que vai em toda chamada, descreve o motor e
    somente o setor ativo."""
    from sentury.domains import escolha
    from sentury.tools.capability_catalog import build_catalog, render_manifest
    from sentury.tools.registry import setor_da_ferramenta

    def _mapa():
        return render_manifest(build_catalog(TOOL_REGISTRY, []))

    # Com o setor ligado, o mapa cobre as do motor e as que o pacote publica.
    monkeypatch.setattr(escolha, "ler", lambda *a, **k: "setor_teste")
    composto = _mapa()
    faltando = [
        t for t in KNOWN_TOOLS
        if sempre_exposta(TOOL_REGISTRY[t])
        and (not TOOL_REGISTRY[t].get("setor") or TOOL_REGISTRY[t]["setor"] == "setor_teste")
        and t not in composto
    ]
    assert not faltando, f"tools sem descrição no prompt composto: {faltando}"

    # E o do generalista NAO pode descrever ferramenta de setor: descrever o
    # que ele nao tem na mesa e oferecer o que nao existe.
    monkeypatch.setattr(escolha, "ler", lambda *a, **k: "generalista")
    do_motor = _mapa()
    vazadas = [
        t for t in KNOWN_TOOLS
        if setor_da_ferramenta(t) and t in do_motor
    ]
    assert not vazadas, f"ferramenta de setor descrita para o generalista: {vazadas}"


def test_registry_entries_have_category_and_description():
    for nome, meta in TOOL_REGISTRY.items():
        assert meta.get("categoria"), f"{nome} sem categoria"
        assert meta.get("descricao"), f"{nome} sem descrição"


# --- Derivação policy ← registry (passo 1 da plugabilidade) ------------------
# Trava o mapeamento categoria→gate: os conjuntos de gate da policy DEVEM sair
# exatamente destes nomes. Se alguém mudar uma categoria no registro (ou o mapa
# CATEGORIA_TO_GATE) e quebrar um gate, um destes testes pega.

def test_criar_plano_declara_tarefas_como_texto():
    schema = TOOL_REGISTRY["criar_plano"]["parametros"]
    assert schema["properties"]["tarefas"]["items"] == {"type": "string"}
    assert "tarefas" in schema["required"]


def test_workflow_nao_exige_cron():
    schema = TOOL_REGISTRY["criar_workflow"]["parametros"]
    assert "gatilho" in schema["properties"]
    assert "gatilho" not in schema["required"]


_EXPECTED_GATE = {
    "analysis": {"executar_python"},
    "action": {"kill_command", "processos",
               "schedule_task", "cancel_schedule", "agenda",
               "escrever_arquivo", "editar_arquivo",
               # Criar e marcar alteram o plano em disco; ver so le.
               "criar_plano", "status_da_tarefa",
               # A missao grava em disco em registrar/abrir/fechar; `ver` vem
               # junto porque e a mesma ferramenta, como o `browser`.
               "missao",
               # O goal grava em disco em propor/marco/cumprido.
               "goal",
               # Definir uma rotina que dispara sozinha altera o disco tanto
               # quanto criar um plano: e vale mais, porque ela volta.
               "criar_workflow",
               # Restaurar sobrescreve o arquivo: mesmo portao de escrever.
               "restaurar_versao",
               # `executar_comando` fica no portao de LEITURA porque roda uma
               # linha da lista permitida. `executar_script` escreve um arquivo
               # e roda o que estiver dentro: portao de acao, com aprovacao.
               "executar_script",
               # Mouse e teclado de verdade. A policy barra sem `@computador`
               # antes deste portao; o gesto ainda pede o cartao.
               "computador",
               # Agentes residentes: criar grava o manifesto (com cartao na
               # hora), pedir poe tarefa na fila da HQ e ferramenta nova muda
               # o manifesto (tambem com cartao na hora).
               "criar_agente", "pedir_ao_agente", "pedir_ferramenta", "falar_na_mesa", "abrir_assunto"},
    "export": {"generate_chart", "export_xlsx", "export_csv",
               "export_pdf", "export_html", "save_analysis", "gerar_imagem", "entregar_arquivo"},
    "read": {"buscar_conhecimento", "consultar_experiencia", "buscar_conversas",
             "buscar_web", "ler_pagina", "subagentes", "executar_comando", "usar_mcp", "checar_pacote",
             "command_status", "running_commands", "list_schedules",
             "ler_arquivo", "listar_arquivos",
             "codigo", "onde_definido", "quem_usa", "mapa_do_arquivo",
             # Nucleo: vao em toda chamada, fora do corte por relevancia.
             "search_tools", "perguntar_usuario",
             # A ponte vira a ferramenta de dentro antes da policy; sozinha, nada roda.
             "usar_ferramenta",
             # O plano: ver e leitura; criar e marcar alteram estado.
             "ver_plano", "ver_workflow",
             # Diagnostico e navegacao: leem, nao alteram.
             "diagnosticos", "percorrer_chamadas",
             # Historico le; restaurar escreve, e por isso NAO entra aqui.
             "historico_do_arquivo", "inspecionar_ambiente",
             # Lê a web; instalar pede o cartão dentro da própria ferramenta.
             "find_skills"},
    "memory": {"memoria", "salvar_memoria", "esquecer_memoria", "listar_memorias", "aprender_skill",
               # So existe no turno do agente residente.
               "memoria_do_agente",
               # Decisoes da equipe, para o Sentury e todo residente.
               "decisao"},
    "skill": {"salvar_skill", "executar_skill", "listar_skills", "esquecer_skill"},
    "browser": {"browser"},
}


def test_policy_sets_derivam_do_registry_exatamente():
    from sentury.harness.policy import (
        ANALYSIS_TOOLS, ACTION_TOOLS, BROWSER_TOOLS, EXPORT_TOOLS, READ_TOOLS,
        MEMORY_TOOLS, SKILL_TOOLS,
    )
    got = {
        "analysis": ANALYSIS_TOOLS, "action": ACTION_TOOLS, "export": EXPORT_TOOLS,
        "read": READ_TOOLS, "memory": MEMORY_TOOLS, "skill": SKILL_TOOLS,
        "browser": BROWSER_TOOLS,
    }
    # O inventário fixa o motor; setores e extensões validam seus próprios gates.
    got = {gate: {t for t in nomes if "." not in t and not TOOL_REGISTRY[t].get("setor")}
           for gate, nomes in got.items()}
    for gate, esperado in _EXPECTED_GATE.items():
        assert got[gate] == esperado, (
            f"gate {gate}: falta={esperado - got[gate]} sobra={got[gate] - esperado}"
        )


def test_toda_tool_do_registry_mapeia_para_um_gate():
    # se uma categoria de exibição não estiver em CATEGORIA_TO_GATE, a tool some
    # de KNOWN_TOOLS silenciosamente: este teste impede isso.
    from sentury.tools.registry import gate_of, all_tool_names
    sem_gate = [n for n in all_tool_names() if gate_of(n) is None]
    assert not sem_gate, f"tools sem gate (categoria não mapeada): {sem_gate}"


def test_alias_antigo_de_busca_nao_volta_ao_catalogo_publico():
    from sentury.tools.registry import ferramentas_do_setor_ativo

    assert "pesquisar_web" not in ferramentas_do_setor_ativo()
