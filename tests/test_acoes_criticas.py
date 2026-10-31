"""Aprovação pontual cobre a ação crítica concreta, sem ampliar permissões."""
import copy
import sys

import pytest

from sentury.exec import criticas, politica
from sentury.tools import arquivos, permissoes, script, shell
from sentury.harness.pausa_do_turno import autorizacao_pendente

_REMOTO_REAL = criticas.remoto

@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path / "casa"))
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(arquivos, "_configuracao", lambda: {})
    monkeypatch.setattr(permissoes, "_CREDITO_UNICO", {})
    monkeypatch.setattr(permissoes, "_DA_SESSAO", {})
    monkeypatch.setattr(criticas, "remoto", lambda: False)
    tabela = copy.deepcopy(shell.politica(recarregar=True))
    tabela["confirmar_na_hora"]["caminhos"].append(str(tmp_path / "critico"))
    monkeypatch.setattr(shell, "politica", lambda **kw: tabela)
    permissoes.definir_permitir_tudo(True)
    return tabela


@pytest.mark.parametrize("comando", [
    'mkdir "/etc/systemd/system/novo"',
    'escrever_arquivo "/etc/ssh/sshd_config"',
    'editar_arquivo "/etc/docker/daemon.json"',
    'mkdir "/etc/ufw/regra"',
])
def test_caminho_critico_pergunta_no_pc_com_tudo_liberado(comando):
    decisao = politica.avaliar(comando, "teste")
    assert not decisao["permitido"] and decisao["precisa_perguntar"]
    assert decisao["so_desta_vez"]


@pytest.mark.parametrize("comando", [
    "docker stop sentury", "podman restart hq", "tailscale down",
    "ufw disable", "systemctl restart sentury.service", "systemctl stop sshd",
])
def test_infraestrutura_remota_pergunta(comando, monkeypatch):
    monkeypatch.setattr(criticas, "remoto", lambda: True)
    assert politica.avaliar(comando, "teste")["so_desta_vez"]
    assert politica.avaliar(comando, "teste")["precisa_perguntar"]


def test_leitura_declarada_continua_livre(isolado, monkeypatch):
    monkeypatch.setattr(criticas, "remoto", lambda: True)
    isolado["leitura"]["docker"] = ["ps"]
    assert not criticas.motivo("docker ps")
    assert politica.avaliar("docker ps")["permitido"]
    assert not criticas.motivo("cat /etc/systemd/system/sentury.service")
    assert not criticas.motivo("python --version")


def test_trabalho_comum_no_pc_nao_ganha_aprovacao_pontual():
    assert politica.avaliar("git commit -m ajuste")["permitido"]
    assert not criticas.motivo("mkdir projeto")


@pytest.mark.parametrize("resposta", ["sempre", "sessao"])
def test_permissoes_amplas_nao_substituem_confirmacao(resposta, monkeypatch):
    monkeypatch.setattr(criticas, "remoto", lambda: True)
    permissoes.responder("docker stop hq", resposta, "teste")
    assert politica.avaliar("docker stop hq", "teste")["precisa_perguntar"]


def test_credito_nao_e_gasto_na_pre_checagem_e_nao_libera_outro_alvo(monkeypatch):
    monkeypatch.setattr(criticas, "remoto", lambda: True)
    permissoes.responder("docker stop hq", "uma_vez", "teste")
    assert not politica.avaliar("docker stop outro", "teste")["permitido"]
    assert not politica.avaliar("docker restart hq", "teste")["permitido"]
    assert politica.avaliar("docker stop hq", "teste", consumir=False)["permitido"]
    assert politica.avaliar("docker stop hq", "teste")["permitido"]
    assert politica.avaliar("docker stop hq", "teste")["precisa_perguntar"]


def test_negativa_por_verbo_continua_valendo(monkeypatch):
    permissoes.responder("docker stop hq", "negar_sempre", "teste")
    monkeypatch.setattr(criticas, "remoto", lambda: True)
    decisao = politica.avaliar("docker stop outro", "teste")
    assert not decisao["permitido"] and not decisao["precisa_perguntar"]


@pytest.mark.parametrize("comando", ["ssh host", "reboot", "rm -rf /"])
def test_recusa_permanente_nao_vira_cartao(comando, monkeypatch):
    monkeypatch.setattr(criticas, "remoto", lambda: True)
    decisao = politica.avaliar(comando)
    assert not decisao["permitido"] and not decisao["precisa_perguntar"]
    assert decisao["sem_apelacao"]
    resultado = shell.executar(comando, habilitado=True)
    assert resultado["recusado"] and not resultado.get("precisa_permissao")


def test_arquivo_relativo_e_conteudo_casam_entre_plano_e_execucao(tmp_path):
    argumentos = {"caminho": "critico/config.txt", "conteudo": "primeiro"}
    comando = politica.comando_a_autorizar("escrever_arquivo", argumentos)
    pendente = arquivos.escrever(**argumentos, session_id="teste")
    assert pendente["comando"] == comando
    assert pendente["so_desta_vez"] and not (tmp_path / argumentos["caminho"]).exists()
    permissoes.responder(comando, "uma_vez", "teste")
    trocado = arquivos.escrever(argumentos["caminho"], "outro", session_id="teste")
    assert trocado["precisa_permissao"]
    assert politica.avaliar(comando, "teste", consumir=False)["permitido"]
    assert arquivos.escrever(**argumentos, session_id="teste")["ok"]
    assert (tmp_path / argumentos["caminho"]).read_text(encoding="utf-8") == "primeiro"
    assert arquivos.escrever(**argumentos, session_id="teste")["precisa_permissao"]


def test_edicao_critica_cobre_trechos_e_opcao_todas(tmp_path):
    alvo = tmp_path / "critico" / "config.txt"
    alvo.parent.mkdir()
    alvo.write_text("um um", encoding="utf-8")
    args = {"caminho": str(alvo), "antes": "um", "depois": "dois", "todas": True}
    comando = politica.comando_a_autorizar("editar_arquivo", args)
    assert arquivos.editar(**args, session_id="teste")["comando"] == comando
    permissoes.responder(comando, "uma_vez", "teste")
    assert arquivos.editar(str(alvo), "um", "tres", todas=True, session_id="teste")["precisa_permissao"]
    assert arquivos.editar(**args, session_id="teste")["ok"]
    assert alvo.read_text(encoding="utf-8") == "dois dois"


def test_diretorio_da_execucao_entra_na_aprovacao(tmp_path):
    args = {"comando": "mkdir config", "diretorio": str(tmp_path / "critico")}
    comando = politica.comando_a_autorizar("executar_comando", args)
    pendente = shell.executar(**args, habilitado=True, session_id="teste")
    assert pendente["comando"] == comando and pendente["so_desta_vez"]
    permissoes.responder(comando, "uma_vez", "teste")
    outra = criticas.no_diretorio("mkdir config", str(tmp_path / "critico" / "outra"))
    assert politica.avaliar(outra, "teste")["precisa_perguntar"]
    assert politica.avaliar(comando, "teste")["permitido"]


def test_script_com_espacos_no_caminho_considera_conteudo(tmp_path):
    alvo = tmp_path / "pasta com espaco" / "script.py"
    alvo.parent.mkdir()
    alvo.write_text("print('/etc/systemd/system')", encoding="utf-8")
    comando = f'python "{alvo}"'
    assert politica.avaliar(comando)["so_desta_vez"]
    permissoes.responder(comando, "uma_vez", "teste")
    alvo.write_text("print('/etc/docker')", encoding="utf-8")
    assert politica.avaliar(comando, "teste")["precisa_perguntar"]


def test_script_remoto_retomado_executa_so_uma_vez(monkeypatch):
    monkeypatch.setattr(criticas, "remoto", lambda: True)
    monkeypatch.setattr(script, "_interpretador", lambda nome: sys.executable)
    args = {"conteudo": "print('confirmado')", "linguagem": "python", "habilitado": True, "session_id": "teste"}
    pendente = script.executar_script(**args)
    assert pendente["so_desta_vez"]
    permissoes.responder(pendente["comando"], "uma_vez", "teste")
    resultado = script.executar_script(**args)
    assert resultado["ok"] and "confirmado" in resultado["saida"]
    assert script.executar_script(**args)["precisa_permissao"]


def test_script_local_em_caminho_critico_pergunta_sem_executar(monkeypatch, tmp_path):
    monkeypatch.setattr(script, "_interpretador", lambda nome: sys.executable)
    conteudo = "from pathlib import Path\nPath('config').write_text('novo')"
    saida = script.executar_script(
        conteudo, "python", diretorio=str(tmp_path / "critico"),
        habilitado=True, session_id="teste",
    )
    assert saida["precisa_permissao"] and saida["so_desta_vez"]
    assert not (tmp_path / "critico" / "config").exists()


def test_pre_checagem_nao_pergunta_por_credencial_ou_pasta_fora_da_area(tmp_path):
    permissoes.definir_permitir_tudo(False)
    for caminho in (str(tmp_path / ".env"), str(tmp_path.parent / "fora" / "arquivo.txt")):
        assert politica.comando_a_autorizar("escrever_arquivo", {"caminho": caminho}) == ""


def test_composto_critico_pede_aprovacao_do_script_que_vai_rodar(monkeypatch):
    monkeypatch.setattr(script, "_interpretador", lambda nome: sys.executable)
    comando = "echo novo > /etc/systemd/system/exemplo.service"
    assert politica.comando_a_autorizar("executar_comando", {"comando": comando}) == ""
    resultado = shell.executar(comando, habilitado=True, session_id="teste")
    assert resultado["precisa_permissao"] and resultado["so_desta_vez"]
    assert resultado["conteudo"] == comando


def test_cartao_previo_preserva_credito_e_opcoes(monkeypatch):
    from tests.test_retomada_de_permissao import _orquestrador
    from sentury.harness.state import AnalysisState

    monkeypatch.setattr(criticas, "remoto", lambda: True)
    orq = _orquestrador()
    state = AnalysisState.new("teste", "u")
    plano = [{"tool": "executar_comando", "arguments": {"comando": "docker stop hq"}}]
    pendente = autorizacao_pendente(orq, plano, state)
    assert pendente["so_desta_vez"]
    assert pendente["argumentos"] == plano[0]["arguments"]
    permissoes.responder(pendente["comando"], "uma_vez", "teste")
    assert autorizacao_pendente(orq, plano, state) is None
    assert politica.avaliar(pendente["comando"], "teste")["permitido"]
    assert politica.avaliar(pendente["comando"], "teste")["precisa_perguntar"]


@pytest.mark.asyncio
async def test_turno_real_para_e_retoma_a_acao_critica(tmp_path, monkeypatch):
    from tests.test_browser_permissao_ponta_a_ponta import _orq
    from sentury.config import settings
    from sentury.harness.state import AnalysisState

    monkeypatch.setattr(settings, "SENTURY_SHELL", True)
    pasta = tmp_path / "critico" / "nova"
    pasta.parent.mkdir()
    argumentos = {"comando": f'mkdir "{pasta}"'}
    orq = _orq([{"tool": "executar_comando", "arguments": argumentos}])
    state = AnalysisState.new("critica-ponta-a-ponta", "u")
    resultado = await orq.handle_message(state, "crie a pasta indicada")
    assert resultado["permissao"]["so_desta_vez"]
    assert state.tarefa_pendente["argumentos"] == argumentos
    assert state.tarefa_pendente["so_desta_vez"]
    assert not pasta.exists()
    permissoes.responder(resultado["permissao"]["comando"], "uma_vez", state.session_id)
    retomado = await orq.handle_message(state, "pode seguir")
    assert not retomado.get("permissao")
    assert state.tarefa_pendente is None
    assert pasta.is_dir()
    assert shell.executar(**argumentos, habilitado=True, session_id=state.session_id)["precisa_permissao"]


def test_retomada_critica_preserva_argumentos_aprovados():
    from sentury.harness.retomada import guardar, injetar_passo

    aprovado = {"ferramenta": "executar_comando", "argumentos": {"comando": "docker stop hq"}, "so_desta_vez": True}
    pendente = guardar("pare a hq", aprovado, "docker stop hq")
    outro = {"tool": "executar_comando", "arguments": {"comando": "docker stop outro"}}
    passo = {"tool": "executar_comando", "arguments": aprovado["argumentos"]}
    assert injetar_passo([outro], pendente) == [passo, outro]
    assert injetar_passo([passo], pendente) == [passo]


def test_chaves_opacas_nao_perdem_o_identificador():
    assert permissoes.assinatura("browser_roteiro#primeiro") == "browser_roteiro#primeiro"
    assert permissoes.assinatura("browser_roteiro#segundo") == "browser_roteiro#segundo"
    assert shell.partes_do_comando('git log --format="%h#%s"')[-1] == "--format=%h#%s"


@pytest.mark.parametrize("onde,container,nuvem,systemd", [
    ("container", True, False, False), ("VM de nuvem", False, True, False),
    ("serviço systemd", False, False, True), ("computador pessoal", False, False, False),
    ("indisponível aqui", False, False, False),
])
def test_contexto_informa_sinais_sem_conceder_permissao(onde, container, nuvem, systemd, monkeypatch):
    from sentury.harness.contexto_do_mundo import ambiente_do_turno
    from sentury.tools import ambiente

    monkeypatch.setattr(ambiente, "_sistema", lambda: {
        "onde_roda": onde, "container": container, "vm_de_nuvem": nuvem, "servico_systemd": systemd,
    })
    texto = ambiente_do_turno("teste")
    assert _REMOTO_REAL() is (onde != "computador pessoal")
    assert f"localização pelos sinais locais: {onde}" in texto
    assert "localização não concede permissão" in texto
    assert "Tudo liberado" in texto


def test_sinais_desconhecidos_nao_liberam_infraestrutura(monkeypatch):
    from sentury.tools import ambiente

    monkeypatch.setattr(criticas, "remoto", _REMOTO_REAL)
    monkeypatch.setattr(ambiente, "_sistema", lambda: {
        "container": False, "vm_de_nuvem": False, "servico_systemd": False,
        "onde_roda": "indisponível aqui",
    })
    assert criticas.remoto()
