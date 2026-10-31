"""Pipe e `&&` no executar_comando, trecho por trecho pela politica.

Recusar o comando composto inteiro empurra o modelo para um script que para
pedindo autorizacao. Cada trecho passa pela politica por conta propria.
"""
import pytest

from sentury.tools import script, shell


@pytest.fixture(autouse=True)
def _politica():
    shell.politica(recarregar=True)
    yield


@pytest.mark.parametrize("comando,leitura", [
    ('cd "C:/a b" && git log -1 --format="%h %s"', True),
    ("git log | head -5", True),
    ("git log 2>&1 | head", True),
    ("cat a.txt > b.txt", False),
    ("echo $(whoami)", False),
    ("git log; git commit -m x", False),
])
def test_cada_trecho_passa_pela_politica(comando, leitura):
    trechos, arriscado = shell.composto(comando)
    assert (not arriscado and all(shell._e_leitura(t) for t in trechos)) is leitura


def test_simples_e_aspas_nao_viram_composto():
    assert shell.composto("git log -1") is None
    assert shell.composto('grep "a|b" f.txt') is None


def test_programa_negado_escondido_e_recusado_sem_pergunta():
    saida = shell.executar("ls; rm -rf pasta", habilitado=True)
    assert saida["recusado"] and "nenhum modo" in saida["motivo"]


def test_leitura_roda_sem_pergunta_e_escrita_pede_pelo_conteudo(monkeypatch):
    vistos = []

    def falso(conteudo, linguagem, **kw):
        vistos.append((conteudo, kw.get("leitura_validada")))
        return {"ok": True}

    monkeypatch.setattr(script, "executar_script", falso)
    shell.executar("git log | head -5", habilitado=True)
    shell.executar("cat a.txt > b.txt", habilitado=True)
    assert vistos == [("git log | head -5", True), ("cat a.txt > b.txt", False)]


def test_descricao_diz_o_shell_ativo_desta_maquina(monkeypatch):
    """A descricao traz o shell padrao e a busca de texto que existe na maquina."""
    from sentury.llm.tool_schemas import build_tool_schemas

    monkeypatch.setattr(shell, "_DICA_DO_SHELL", None)
    monkeypatch.setattr(script, "linguagem_padrao", lambda: "bash")
    monkeypatch.setattr(shell.shutil, "which", lambda b: "/usr/bin/grep" if b == "grep" else None)
    desc = next(e["function"]["description"] for e in build_tool_schemas({"executar_comando"})
                if e["function"]["name"] == "executar_comando")
    assert "shell padrao e bash" in desc and "grep -c" in desc and "rg -c" not in desc
    monkeypatch.setattr(shell, "_DICA_DO_SHELL", None)


@pytest.mark.parametrize("comando,pedido,esperado", [
    ("Get-ChildItem . -Force | Select-Object -ExpandProperty Name", "", "powershell"),
    ("Get-Content a.txt", "", "powershell"),
    ("echo $env:USERPROFILE", "", "powershell"),
    ("apt-get install x", "", "bash"),
    ("docker-compose ps", "", "bash"),
    ("git log | head -5", "", "bash"),
    ("ls", "pwsh", "powershell"),
    ("Get-Content a.txt", "bash", "bash"),
    ("(Get-Content a.txt).Count", "", "powershell"),
])
def test_dialeto_segue_o_pedido_ou_a_escrita(monkeypatch, comando, pedido, esperado):
    monkeypatch.setattr(script, "linguagem_padrao", lambda: "bash")
    assert shell.dialeto(comando, pedido) == esperado


def _script_falso(monkeypatch, disponiveis=("bash", "powershell", "python")):
    vistos = []

    def falso(conteudo, linguagem, **kw):
        vistos.append((conteudo, linguagem, kw.get("leitura_validada")))
        return {"ok": True}

    monkeypatch.setattr(script, "executar_script", falso)
    monkeypatch.setattr(script, "linguagens_disponiveis", lambda: list(disponiveis))
    monkeypatch.setattr(script, "linguagem_padrao", lambda: "bash")
    return vistos


def test_powershell_roda_no_powershell_mesmo_com_bash_padrao(monkeypatch):
    """Cmdlet de leitura roda sem pergunta, simples ou com pipe, no PowerShell."""
    vistos = _script_falso(monkeypatch)
    shell.executar("Get-ChildItem . -Force | Select-Object -ExpandProperty Name", habilitado=True)
    shell.executar("Get-Content notas.txt", habilitado=True)
    shell.executar("git log | head -5", habilitado=True)
    assert vistos == [
        ("Get-ChildItem . -Force | Select-Object -ExpandProperty Name", "powershell", True),
        ("Get-Content notas.txt", "powershell", True),
        ("git log | head -5", "bash", True),
    ]


def test_bloco_de_codigo_pede_aprovacao(monkeypatch):
    """Chave fora de aspas e codigo (bloco do PowerShell, alvo do `find -exec`)."""
    vistos = _script_falso(monkeypatch)
    shell.executar("Get-ChildItem | Where-Object { $_.Length -gt 0 }", habilitado=True)
    assert vistos[-1][1:] == ("powershell", False)
    assert not shell.so_leitura("find . -name x -exec cat {} +")
    assert shell.so_leitura('git log --format="{%h}"')


def test_remocao_do_powershell_e_negada_como_rm(monkeypatch):
    _script_falso(monkeypatch)
    saida = shell.executar("Remove-Item pasta -Recurse", habilitado=True)
    assert saida["recusado"] and "nenhum modo" in saida["motivo"]
    assert shell.executar("(Remove-Item pasta)", habilitado=True)["recusado"]


def test_parentese_de_agrupamento_nao_muda_o_programa(monkeypatch):
    """A contagem que a dica recomenda roda como leitura, sem aprovação."""
    vistos = _script_falso(monkeypatch)
    shell.executar("(Get-Content notas.txt).Count", habilitado=True)
    assert vistos == [("(Get-Content notas.txt).Count", "powershell", True)]


def test_dica_do_shell_avisa_da_contagem_do_powershell(monkeypatch):
    monkeypatch.setattr(shell, "_DICA_DO_SHELL", None)
    monkeypatch.setattr(script, "linguagem_padrao", lambda: "powershell")
    assert "(Get-Content arquivo).Count" in shell.dica_do_shell()
    monkeypatch.setattr(shell, "_DICA_DO_SHELL", None)


def test_shell_ausente_vira_fato_e_nao_script(monkeypatch):
    vistos = _script_falso(monkeypatch, disponiveis=("bash", "python"))
    saida = shell.executar("Get-ChildItem", habilitado=True)
    assert saida["recusado"] and "powershell nao existe" in saida["motivo"]
    assert vistos == []


def test_ambiente_do_turno_continua_um_dicionario():
    """`ambiente()` e a dica do shell sao funcoes diferentes; o turno le `amb['sistema']`."""
    amb = shell.ambiente()
    assert isinstance(amb, dict) and "sistema" in amb
    assert isinstance(shell.dica_do_shell(), str)


def test_composto_pede_pelo_script_real_sem_duas_aprovacoes(tmp_path, monkeypatch):
    """A consulta não pode pedir por uma chave diferente da execução."""
    from sentury.exec.politica import comando_a_autorizar
    from sentury.tools import permissoes

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.setattr(permissoes, "_carregar", lambda: {
        "sempre": [], "negados": [], "permitir_tudo": False,
    })
    monkeypatch.setattr(permissoes, "_CREDITO_UNICO", {})
    monkeypatch.setattr(permissoes, "_DA_SESSAO", {})

    assert comando_a_autorizar("executar_comando", {"comando": 'find "C:/a b" -name "*.py" | wc -l'}) == ""
    comando = "git log > saida.txt"
    assert comando_a_autorizar("executar_comando", {"comando": comando}) == ""
    resultado = shell.executar(comando, habilitado=True, session_id="composto")
    assert resultado["precisa_permissao"]
    assert resultado["conteudo"] == comando
    assert resultado["chave"] == permissoes.assinatura(resultado["comando"])
    assert not (tmp_path / "saida.txt").exists()


@pytest.mark.skipif("powershell" not in script.linguagens_disponiveis(), reason="sem PowerShell")
def test_powershell_acha_caminho_com_acento_e_devolve_texto_legivel(tmp_path, monkeypatch):
    """O script vai com BOM e saida em UTF-8: caminho com acento e achado e o
    nome volta como foi escrito."""
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    pasta = tmp_path / "Área de Teste"
    pasta.mkdir()
    (pasta / "ação.txt").write_text("um\n", encoding="utf-8")
    saida = shell.executar(f"Get-ChildItem -LiteralPath '{pasta}' | Select-Object -ExpandProperty Name",
                           habilitado=True, session_id="acento")
    assert saida["ok"], saida
    assert saida["saida"].strip() == "ação.txt"
