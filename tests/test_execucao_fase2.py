"""A costura da execucao: resultado, ambiente e saida."""
from pathlib import Path
import os

import pytest

from sentury.exec.ambiente import bandeiras_de_processo, preparar_env
from sentury.exec.contrato import CodigoDeErro, Resultado, pendente, recusa
from sentury.exec.saida import limpar_ansi, preparar, redigir_segredos, truncar_pelas_pontas
from sentury.tools import shell


class TestContrato:
    def test_sucesso_exige_codigo_zero(self):
        assert Resultado(codigo_saida=0).ok is True
        assert Resultado(codigo_saida=1).ok is False
        assert Resultado().ok is False, "sem codigo nao ha prova de sucesso"

    def test_stderr_nao_derruba_sucesso(self):
        # git e pip escrevem aviso no stderr ao terminar bem.
        assert Resultado(codigo_saida=0, stderr="warning: CRLF").ok is True

    def test_recusa_e_pendencia_nao_sao_sucesso(self):
        assert recusa("rm -rf /", "negado").ok is False
        assert pendente("python x.py", "aprove").ok is False

    def test_pendencia_se_identifica_para_a_rota(self):
        assert pendente("python x.py", "aprove").codigo_erro == CodigoDeErro.PRECISA_PERMISSAO

    def test_formato_antigo_preservado(self):
        # Mudar o nome dos campos e mudar o contrato com o orquestrador inteiro.
        d = Resultado(comando="ls", codigo_saida=0, stdout="a", stderr="b").para_dict()
        assert {"ok", "comando", "codigo", "saida", "erro", "truncado"} <= set(d)

    def test_campos_de_excecao_so_aparecem_quando_valem(self):
        assert "timeout" not in Resultado(codigo_saida=0).para_dict()
        assert Resultado(timeout=True).para_dict()["timeout"] is True


class TestAmbiente:
    def test_credencial_nao_atravessa(self, monkeypatch):
        monkeypatch.setenv("MINHA_API_KEY", "segredo")
        monkeypatch.setenv("TELEGRAM_TOKEN", "segredo")
        env = preparar_env()
        assert not any(("KEY" in k.upper() or "TOKEN" in k.upper()) for k in env)

    def test_nome_com_pass_nao_e_confundido_com_senha(self, monkeypatch):
        # `PASS` pegaria BYPASS_CACHE e COMPASS_DIR sem motivo.
        monkeypatch.setenv("PATH_BYPASS_CACHE", "1")
        assert "senha" not in str(preparar_env()).lower()

    def test_utf8_sempre(self):
        env = preparar_env()
        assert env["PYTHONUTF8"] == "1" and env["PYTHONIOENCODING"] == "utf-8"

    @pytest.mark.skipif(os.name != "nt", reason="essenciais do Windows")
    def test_windows_recebe_o_que_precisa_para_rodar(self):
        env = {k.upper() for k in preparar_env()}
        # Sem SystemRoot o filho nem abre socket (WinError 10106).
        assert {"SYSTEMROOT", "COMSPEC", "PATHEXT"} <= env

    def test_extra_vence_a_base(self):
        assert preparar_env({"PYTHONUTF8": "0"})["PYTHONUTF8"] == "0"

    def test_bandeiras_por_sistema(self):
        b = bandeiras_de_processo()
        assert ("creationflags" in b) if os.name == "nt" else ("start_new_session" in b)


class TestSaida:
    def test_guarda_comeco_e_fim(self):
        texto, truncado = truncar_pelas_pontas("INICIO" + "x" * 900 + "FIM", 120)
        assert truncado and texto.startswith("INICIO") and texto.endswith("FIM")
        assert "omitidos no meio" in texto

    def test_saida_curta_passa_inteira(self):
        assert truncar_pelas_pontas("curto", 100) == ("curto", False)

    def test_redige_valor_e_mantem_o_nome(self):
        saida = redigir_segredos("OPENAI_API_KEY=sk-abcdefghijklmnop")
        assert "OPENAI_API_KEY" in saida and "sk-abcdefghijklmnop" not in saida

    def test_redige_bearer_e_token_de_provedor(self):
        assert "abcdefghijklmnopqr" not in redigir_segredos("Bearer abcdefghijklmnopqr")
        assert "ghp_" not in redigir_segredos("ghp_" + "a" * 24).replace("[redigido]", "")

    def test_limpa_cor_do_terminal(self):
        assert limpar_ansi("\x1b[31mvermelho\x1b[0m") == "vermelho"

    def test_caminho_completo(self):
        texto, _ = preparar("\x1b[32mTOKEN=abc123def456\x1b[0m", 200)
        assert "\x1b" not in texto and "abc123def456" not in texto


class TestShellUsaACostura:
    def test_ambiente_informa_os_interpretadores(self):
        assert isinstance(shell.ambiente()["interpretadores"], list)

    def test_comando_real_roda_com_ambiente_limpo(self, monkeypatch):
        monkeypatch.setenv("SENHA_SECRETA_DE_TESTE", "nao-deve-vazar")
        r = shell.executar("git rev-parse --abbrev-ref HEAD", diretorio=str(Path(__file__).resolve().parent.parent),
                           habilitado=True, segundo_plano=False, timeout=30)
        assert r["ok"] is True and r["codigo"] == 0
        assert "nao-deve-vazar" not in str(r)
