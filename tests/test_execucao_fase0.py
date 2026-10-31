"""Camada de execucao: sandbox com excecoes, anexo sem varredura e
classificacao de falha que enxerga recusa."""
import asyncio

import pytest

from sentury.exec import python_exec
from sentury.harness.classificacao import falhou


def _rodar(codigo, store=None):
    return asyncio.run(python_exec.executar_python(store, codigo))


class TestExcecoesNoSandbox:
    def test_try_except_exception_nao_morre_com_nameerror(self):
        codigo = "\n".join([
            "try:",
            "    1 / 0",
            "except Exception as e:",
            "    resultado = str(e)",
        ])
        saida = _rodar(codigo)
        assert "NameError" not in str(saida.get("erro") or "")
        assert "division by zero" in str(saida.get("resultado") or "")

    def test_raise_de_classe_padrao(self):
        saida = _rodar(
            "try:\n"
            "    raise ValueError('vazio')\n"
            "except ValueError as e:\n"
            "    resultado = str(e)\n"
        )
        assert saida.get("resultado") == "vazio"

    def test_excecao_nao_trouxe_nome_de_sistema(self):
        # A varredura pega so subclasses de BaseException; nada de os/open cru.
        for proibido in ("__import__", "eval", "exec", "getattr"):
            assert python_exec._SAFE_BUILTINS.get(proibido) is not __builtins__.get(
                proibido) if isinstance(__builtins__, dict) else True


class TestClassificacaoDeFalha:
    @pytest.mark.parametrize("resultado", [
        {"erro": "estourou"},
        {"ok": False, "recusado": True, "motivo": "comando negado"},
        {"timeout": True},
        {"ok": True, "codigo_saida": 2},
    ])
    def test_falha(self, resultado):
        assert falhou(resultado) is True

    @pytest.mark.parametrize("resultado", [
        {"ok": True, "codigo_saida": 0, "stdout": "pronto"},
        {"arquivos_gerados": ["x.png"]},
        {"linhas": []},
        "texto solto",
        None,
    ])
    def test_sucesso(self, resultado):
        assert falhou(resultado) is False

    def test_permissao_pendente_nao_e_falha(self):
        # Pergunta ao dono nao pode queimar o teto de falhas do turno.
        pendente = {"ok": False, "precisa_permissao": True, "chave": "python x.py"}
        assert falhou(pendente) is False

    def test_motivo_da_recusa_chega_ao_agente_sem_resposta_pronta(self):
        from sentury.llm.prompts import build_tool_result_instruction

        texto = build_tool_result_instruction(
            "executar_comando", {"ok": False, "recusado": True, "motivo": "comando negado"})
        assert "comando negado" in texto
        assert "Posso tentar novamente" not in texto

    def test_browser_com_motivo_tambem_chega_ao_agente(self):
        from sentury.llm.prompts import build_tool_result_instruction

        texto = build_tool_result_instruction(
            "browser", {"ok": False, "fase": "execucao", "motivo": "ref desconhecida: e99"})
        assert "FALHOU" in texto and "ref desconhecida: e99" in texto
        assert "Reavalie o erro" in texto


class TestAnexoSemVarredura:
    def test_nao_ha_mais_janela_de_dez_segundos(self):
        # A janela "modificado nos ultimos 10s" entregava artefato de uma
        # requisicao para outra. O `stat` que sobrou so ordena o que o sandbox
        # declarou ter criado.
        fonte = (python_exec.Path(__file__).resolve().parents[1]
                 / "sentury" / "harness" / "anexo_do_resultado.py").read_text(encoding="utf-8")
        assert "now - mtime < 10" not in fonte
        assert "time.time() - mtime" not in fonte
        assert "os.getcwd()" not in fonte


class TestStderrNaoEFalha:
    def test_comando_ok_com_aviso_no_stderr(self):
        # `erro` carrega o stderr; git e pip escrevem aviso ali ao terminar bem.
        ok = {"ok": True, "codigo": 0, "saida": "feito", "erro": "warning: CRLF"}
        assert falhou(ok) is False

    def test_codigo_diferente_de_zero_e_falha_mesmo_com_ok(self):
        assert falhou(
            {"ok": True, "codigo": 1, "erro": ""}) is True

    def test_erro_sem_codigo_continua_falha(self):
        assert falhou({"erro": "estourou"}) is True
