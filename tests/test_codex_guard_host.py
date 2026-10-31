"""A guarda do CLI não deve proibir ações que o Sentury executa fora dele."""
from types import SimpleNamespace

import pytest

from robinbandit.providers.codex_provider import CodexAppServerClient


@pytest.mark.parametrize("pedido", ["Leia resumo.txt", "请读取 resumo.txt", "Read resumo.txt"])
async def test_guarda_distingue_cli_e_host_sem_abrir_sandbox(monkeypatch, pedido):
    client = CodexAppServerClient()
    requests = {}

    async def request(process, method, params, *, on_notification=None):
        requests[method] = params
        if method == "thread/start":
            return {"thread": {"id": "thread-test"}}
        if method == "turn/start":
            on_notification({"method": "item/completed", "params": {"item": {
                "type": "agentMessage", "text": '{"plan":[{"tool":"ler_arquivo"}]}'}}})
            on_notification({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
        return {}

    async def send(*args):
        pass

    monkeypatch.setattr(client, "_request", request)
    monkeypatch.setattr(client, "_send", send)
    await client._drive(SimpleNamespace(stdout=object()), [
        {"role": "system", "content": "Devolva um plano JSON de ferramentas do Sentury."},
        {"role": "user", "content": pedido},
    ], "gpt-5.5", "low")
    thread = requests["thread/start"]
    guard = thread["developerInstructions"]
    assert "Não execute ferramentas locais do Codex" in guard
    assert "selecionar essas ferramentas pelo formato solicitado na conversa" in guard
    assert "quem executa e autoriza é o hospedeiro" in guard
    assert thread["sandbox"] == "read-only" and thread["approvalPolicy"] == "never"
    assert requests["turn/start"]["sandboxPolicy"] == {"type": "readOnly"}
    assert requests["turn/start"]["input"] == [{"type": "text", "text": pedido}]


def test_o_codex_nao_executa_nada_por_conta_propria():
    """O 0.159 ligou o `code_mode_host` por padrão: sem o executável dele, o turno
    morria antes de a ferramenta do Sentury rodar."""
    comando = CodexAppServerClient()._command("codex")
    desligadas = {comando[i + 1] for i, parte in enumerate(comando) if parte == "--disable"}
    assert {"code_mode_host", "unified_exec", "shell_tool", "browser_use_external"} <= desligadas


def test_servidores_mcp_da_pessoa_ficam_desligados(tmp_path, monkeypatch):
    """O app desktop deixa `node_repl` (e o Tato) na config; no modo provedor o
    modelo não pode chamá-los, porque quem executa é o hospedeiro."""
    (tmp_path / "config.toml").write_text(
        '[mcp_servers.node_repl]\ncommand = "x"\n\n[mcp_servers.tato]\ncommand = "y"\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    comando = CodexAppServerClient()._command("codex")
    assert "mcp_servers.node_repl.enabled=false" in comando
    assert "mcp_servers.tato.enabled=false" in comando
