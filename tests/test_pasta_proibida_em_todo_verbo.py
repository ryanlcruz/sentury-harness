"""`.ssh` e credencial sao recusados em TODA ferramenta de arquivo.

Antes, as ferramentas de arquivo perguntavam: `ler_arquivo`, `escrever_arquivo`
e `editar_arquivo` num `~/.ssh` mostravam o cartao "liberar a pasta?", e so a
leitura recusava depois do clique. `listar_arquivos`, o historico e a
restauracao nem checavam: com a maquina toda liberada, listavam o `.ssh`.
Um "sim" distraido no cartao deixava o agente gravar no `authorized_keys`.
"""
import pytest

from sentury.harness.state import AnalysisState
from sentury.tools import arquivos
from sentury.tools.catalog import execute_tool


@pytest.fixture
def casa(tmp_path, monkeypatch):
    """Um HOME falso com `.ssh` dentro. Nada aqui toca a maquina de verdade."""
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / ".sentury"))
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    (ssh / "id_rsa").write_text("SEGREDO", encoding="utf-8")
    (ssh / "authorized_keys").write_text("", encoding="utf-8")
    return tmp_path


async def _chamar(tool, argumentos):
    return await execute_tool(None, AnalysisState.new("s", "u"), tool, argumentos)


@pytest.mark.parametrize("liberado", [False, True], ids=["pasta-fechada", "maquina-toda-liberada"])
@pytest.mark.parametrize("tool,argumentos", [
    ("ler_arquivo", {"caminho": "{casa}/.ssh/id_rsa"}),
    ("listar_arquivos", {"caminho": "{casa}/.ssh"}),
    ("escrever_arquivo", {"caminho": "{casa}/.ssh/authorized_keys", "conteudo": "ssh-rsa AAA intruso"}),
    ("editar_arquivo", {"caminho": "{casa}/.ssh/id_rsa", "antes": "SEGREDO", "depois": "X"}),
    ("historico_do_arquivo", {"caminho": "{casa}/.ssh/id_rsa"}),
])
async def test_recusa_sem_oferecer_liberar(casa, monkeypatch, liberado, tool, argumentos):
    monkeypatch.setattr(arquivos, "tudo_liberado", lambda: liberado)
    argumentos = {k: v.replace("{casa}", str(casa)) for k, v in argumentos.items()}

    resultado = await _chamar(tool, argumentos)

    assert not resultado.get("precisa_permissao"), f"{tool} ofereceu liberar o .ssh"
    assert "credencial" in str(resultado.get("erro") or ""), resultado
    assert "SEGREDO" not in str(resultado)
    assert (casa / ".ssh" / "id_rsa").read_text(encoding="utf-8") == "SEGREDO"
    assert (casa / ".ssh" / "authorized_keys").read_text(encoding="utf-8") == ""


def test_a_pasta_proibida_nao_se_libera(casa):
    resultado = arquivos.liberar_pasta(str(casa / ".ssh"))
    assert resultado["ok"] is False and "politica" in resultado["erro"]
    assert str(casa / ".ssh") not in [str(p) for p in arquivos.pastas_extras()]


def test_pasta_comum_continua_pedindo_para_liberar(casa, monkeypatch):
    """A recusa e so para credencial: o resto segue o fluxo de liberar."""
    monkeypatch.setattr(arquivos, "tudo_liberado", lambda: False)
    (casa / "Documentos").mkdir()
    resultado = arquivos.listar(str(casa / "Documentos"))
    assert resultado.get("precisa_permissao") is True
