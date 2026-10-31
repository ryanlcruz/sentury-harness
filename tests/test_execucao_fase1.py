"""O interpretador exige aprovacao do conteudo, e "liberar tudo" nao
desliga a protecao do codigo."""
import asyncio

import pytest

from sentury.exec import python_exec as px
from sentury.tools import arquivos, permissoes
from sentury.tools.shell import ComandoRecusado, comandos_de_execucao, comandos_de_leitura, validar


class TestInterpretadorNaoELeitura:
    @pytest.mark.parametrize("programa", ["python", "pytest", "node", "powershell", "bash"])
    def test_fora_da_lista_de_leitura(self, programa):
        assert programa not in comandos_de_leitura()
        assert programa in comandos_de_execucao()

    def test_rodar_script_recusa_como_leitura(self):
        with pytest.raises(ComandoRecusado, match="conteudo do script"):
            validar("python x.py")

    def test_rodar_script_passa_com_aprovacao(self):
        assert validar("python x.py", permitir_escrita=True) == ["python", "x.py"]

    def test_pip_list_continua_leitura(self):
        assert validar("pip list") == ["pip", "list"]


class TestAssinaturaPorConteudo:
    def test_scripts_diferentes_sao_decisoes_diferentes(self, tmp_path):
        a, b = tmp_path / "a.py", tmp_path / "b.py"
        a.write_text("print(1)\n", encoding="utf-8")
        b.write_text("print(2)\n", encoding="utf-8")
        assert permissoes.assinatura(f"python {a}") != permissoes.assinatura(f"python {b}")

    def test_reescrever_o_script_invalida_a_aprovacao(self, tmp_path):
        alvo = tmp_path / "a.py"
        alvo.write_text("print(1)\n", encoding="utf-8")
        antes = permissoes.assinatura(f"python {alvo}")
        alvo.write_text("import shutil; shutil.rmtree('/')\n", encoding="utf-8")
        assert permissoes.assinatura(f"python {alvo}") != antes

    def test_fim_de_linha_do_windows_nao_cria_outra_decisao(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sentury.exec.criticas.remoto", lambda: False)
        unix, win = tmp_path / "u.py", tmp_path / "w.py"
        unix.write_bytes(b"print(1)\n")
        win.write_bytes(b"print(1)\r\n")
        u = permissoes.assinatura(f"python {unix}").split("#")[-1]
        w = permissoes.assinatura(f"python {win}").split("#")[-1]
        assert u == w

    def test_git_continua_por_verbo(self):
        assert permissoes.assinatura("git commit -m oi") == "git commit"


class TestConfinamentoComUniversal:
    def _rodar(self, codigo):
        return asyncio.run(px.executar_python(None, codigo))

    @pytest.fixture
    def universal(self, monkeypatch):
        monkeypatch.setattr(px, "_tudo_liberado", lambda: True)

    def test_nao_grava_dentro_do_codigo_do_sentury(self, universal):
        alvo = arquivos.instalacao_do_sentury() / "sentury" / "invadido.py"
        erro = str(self._rodar(f"open(r'{alvo}','w').write('x')").get("erro") or "")
        assert "PermissionError" in erro, erro
        assert not alvo.exists()

    def test_nao_grava_na_raiz_da_instalacao(self, universal):
        alvo = arquivos.instalacao_do_sentury() / "invadido.md"
        erro = str(self._rodar(f"open(r'{alvo}','w').write('x')").get("erro") or "")
        assert "PermissionError" in erro, erro
        assert not alvo.exists()

    def test_grava_script_no_rascunho(self, universal):
        r = self._rodar("open('fase1_ok.py','w').write('print(1)')")
        assert not r.get("erro"), r
        gerados = r.get("arquivos_gerados") or []
        assert gerados and gerados[0].endswith("fase1_ok.py")
        px.Path(gerados[0]).unlink(missing_ok=True)
