import pytest

from sentury.harness.state import AnalysisState
from sentury.tools.catalog import execute_tool


@pytest.mark.asyncio
async def test_ferramenta_sem_executor_nao_finge_ser_exportacao():
    estado = AnalysisState.new("sessao-sem-executor", "usuario")

    with pytest.raises(
        ValueError,
        match="ferramenta conhecida, mas sem executor no catálogo: perguntar_usuario",
    ):
        await execute_tool(
            None,
            estado,
            "perguntar_usuario",
            {"pergunta": "Qual caminho?"},
        )


@pytest.mark.asyncio
async def test_criar_plano_aceita_titulo_como_nome(monkeypatch, tmp_path):
    from sentury.memory import plano

    monkeypatch.setattr(
        plano,
        "raiz_dos_planos",
        lambda trabalho=None: tmp_path / ".sentury" / "planos",
    )
    estado = AnalysisState.new("sessao-plano", "usuario")

    resultado = await execute_tool(
        None,
        estado,
        "criar_plano",
        {
            "titulo": "Buscar Vagas de TI",
            "tarefas": ["Definir filtros", "Buscar vagas"],
        },
    )

    assert resultado["ok"] is True
    assert resultado["plano"] == "buscar-vagas-de-ti"
    assert resultado["tarefas"] == 2


@pytest.mark.asyncio
async def test_criar_workflow_tambem_registra_o_gatilho(monkeypatch, tmp_path):
    from sentury.external import agendador
    from sentury.memory import workflow

    class RelogioFalso:
        def __init__(self):
            self.jobs = []

        def list_jobs(self, session_id=None):
            return list(self.jobs)

        def remove_job(self, job_id):
            self.jobs = [j for j in self.jobs if j["id"] != job_id]
            return True

        def add_job(self, session_id, user_id, prompt, **kwargs):
            job = {"id": "job-workflow", "session_id": session_id, "prompt": prompt, **kwargs}
            self.jobs.append(job)
            return job

    monkeypatch.setattr(
        workflow, "raiz_dos_workflows",
        lambda trabalho=None: tmp_path / ".sentury" / "workflows",
    )
    relogio = RelogioFalso()
    agendador.registrar(relogio)
    try:
        resultado = await execute_tool(
            None,
            AnalysisState.new("sessao-workflow", "usuario"),
            "criar_workflow",
            {
                "nome": "buscar-vagas",
                "porque": "acompanhar oportunidades",
                "gatilho": "0 8 * * 1",
                "passos": ["Buscar vagas", "Atualizar a base"],
            },
        )
    finally:
        agendador.limpar()

    assert resultado["ok"] is True
    assert resultado["gatilho_registrado"] is True
    assert resultado["aguardando_aprovacao"] is True
    assert resultado["agendamento"]["active"] is False
    assert resultado["agendamento"]["workflow"] == "buscar-vagas"
    assert relogio.jobs[0]["cron_expr"] == "0 8 * * 1"


@pytest.mark.asyncio
async def test_criar_workflow_sem_cron_nao_inventa_agendamento(monkeypatch, tmp_path):
    from sentury.memory import workflow

    monkeypatch.setattr(
        workflow, "raiz_dos_workflows",
        lambda trabalho=None: tmp_path / ".sentury" / "workflows",
    )
    resultado = await execute_tool(
        None,
        AnalysisState.new("sessao-workflow-manual", "usuario"),
        "criar_workflow",
        {
            "nome": "migracao-do-banco",
            "porque": "atravessa etapas e aprovacoes",
            "passos": ["Inventariar", "Migrar", "Validar"],
        },
    )

    assert resultado["ok"] is True
    assert resultado["workflow"] == "migracao-do-banco"
    assert resultado["execucao_manual"] is True
    assert resultado["agendamento"] is None
    assert resultado["gatilho_registrado"] is False


@pytest.mark.asyncio
async def test_gatilho_por_evento_salva_a_receita_e_nao_inventa_horario(tmp_path, monkeypatch):
    """Nem todo workflow tem relogio: "quando chegar o relatorio" nao se agenda.

    Isso nao e falha: recusar a receita inteira por causa do agendador seria
    exigir cron de quem nunca pediu horario. O que a resposta precisa dizer e
    que ainda nao dispara sozinho.
    """
    from sentury.external import agendador
    from sentury.memory import workflow

    monkeypatch.setattr(
        workflow, "raiz_dos_workflows",
        lambda trabalho=None: tmp_path / ".sentury" / "workflows",
    )

    class RelogioVazio:
        def list_jobs(self):
            return []

        def add_job(self, *a, **k):  # pragma: no cover - nao deve ser chamado
            raise AssertionError("gatilho por evento nao deve virar cron")

    agendador.registrar(RelogioVazio())
    try:
        resultado = await execute_tool(
            None,
            AnalysisState.new("sessao-workflow", "usuario"),
            "criar_workflow",
            {
                "nome": "conferir-relatorio",
                "gatilho": "quando chegar o relatorio mensal",
                "passos": ["Abrir o arquivo", "Conferir os totais"],
            },
        )
    finally:
        agendador.limpar()

    assert resultado["ok"] is True
    assert resultado["gatilho_por_evento"] is True
    assert resultado["gatilho_registrado"] is False
    assert "aviso" in resultado


@pytest.mark.asyncio
async def test_workflow_ativo_nao_vira_cron_solto():
    estado = AnalysisState.new("sessao-workflow", "usuario")
    estado.funcoes_ativas = ["workflow"]
    resultado = await execute_tool(
        None,
        estado,
        "schedule_task",
        {"tarefa": "buscar vagas", "cron": "0 8 * * 1"},
    )
    assert resultado["ok"] is False
    assert "criar_workflow" in resultado["erro"]


@pytest.mark.asyncio
async def test_criar_plano_nao_vira_workflow_por_receber_cron_extra(tmp_path, monkeypatch):
    """Cron nao define o tipo: workflow e uma escolha explicita e pode ser manual."""
    from sentury.memory import plano

    monkeypatch.setattr(
        plano, "raiz_dos_planos",
        lambda trabalho=None: tmp_path / ".sentury" / "planos",
    )
    resultado = await execute_tool(
        None,
        AnalysisState.new("sessao-tipos-separados", "usuario"),
        "criar_plano",
        {
            "nome": "migracao-unica",
            "gatilho": "0 8 * * 1",
            "tarefas": ["Migrar", "Validar"],
        },
    )

    assert resultado["ok"] is True
    assert resultado["plano"] == "migracao-unica"
    assert "workflow" not in resultado
    assert "agendamento" not in resultado


@pytest.mark.asyncio
async def test_criar_plano_sem_gatilho_continua_plano(tmp_path, monkeypatch):
    """E o inverso: sem gatilho nada e promovido, senao todo plano viraria cron."""
    from sentury.memory import plano

    monkeypatch.setattr(
        plano, "raiz_dos_planos",
        lambda trabalho=None: tmp_path / ".sentury" / "planos",
    )
    resultado = await execute_tool(
        None,
        AnalysisState.new("sessao-porta-unica", "usuario"),
        "criar_plano",
        {"nome": "mudanca-unica", "tarefas": ["Fazer", "Conferir"]},
    )
    assert "workflow" not in resultado
    assert "gatilho_registrado" not in resultado

