"""Seis passos na tela, os seis dizendo "Executando ferramenta…".

A tabela de títulos em `_tool_title` cobria uma dúzia de ferramentas de CX; as
outras sessenta caíam no genérico. E nenhuma linha dizia em CIMA DE QUÊ a
ferramenta rodou: qual pasta, qual consulta.
"""
import pytest

from sentury.harness.orchestrator import SenturyOrchestrator as O
from sentury.harness.titulo_de_ferramenta import TETO_DO_VALOR, alvo, titulo


class TestAlvo:
    def test_pega_o_parametro_declarado_primeiro(self):
        """A ordem em `parametros.properties` é da própria ferramenta: o
        primeiro declarado é o principal, sem lista escrita à mão aqui."""
        assert alvo("listar_arquivos", {"padrao": "**/*", "caminho": "C:/x"}) == "caminho: C:/x"

    def test_sem_argumento_nao_inventa(self):
        assert alvo("listar_arquivos", {}) is None
        assert alvo("listar_arquivos", None) is None

    def test_ignora_vazio_e_booleano(self):
        assert alvo("listar_arquivos", {"caminho": "", "padrao": "*.py"}) == "padrao: *.py"
        assert alvo("qualquer_coisa", {"universal": True, "nome": "x"}) == "nome: x"

    def test_ferramenta_fora_do_registro_usa_a_ordem_que_chegou(self):
        assert alvo("nao_existe", {"a": "1"}) == "a: 1"

    def test_caminho_longo_guarda_o_fim(self):
        """O começo de um caminho do Windows é igual em todos; o fim identifica."""
        longo = "C:/Users/alguem/" + "p/" * 60 + "OCI-Relay"
        saida = alvo("listar_arquivos", {"caminho": longo})
        assert saida.endswith("OCI-Relay") and len(saida) < len(longo)
        assert len(saida) <= TETO_DO_VALOR + len("caminho: ")


class TestTitulo:
    def test_e_so_a_descricao(self):
        """O alvo vai no corpo do cartao de execucao: o caminho nos dois
        lugares fazia o titulo quebrar em tres linhas com a mesma informacao."""
        assert titulo("listar_arquivos", {"caminho": "C:/x"}) == (
            "Lista o que existe numa pasta do projeto")

    def test_corta_na_primeira_frase(self):
        """A segunda frase da descrição é instrução de uso, não rótulo."""
        assert titulo("ler_arquivo", {"caminho": "README.md"}) == (
            "Le um arquivo de texto do projeto")

    def test_sem_registro_nao_responde(self):
        assert titulo("nao_existe_mesmo", {"a": "1"}) is None


class TestNoOrquestrador:
    def test_o_generico_saiu_do_caminho_comum(self):
        assert "Executando ferramenta" not in O._tool_title("listar_arquivos", {"caminho": "C:/x"})

    def test_o_processo_analitico_tambem_perdeu_o_generico(self):
        """O canal antigo de string tem a propria tabela: consertar so o titulo
        deixava o historico com "Executando ferramenta..." cinco vezes."""
        assert O._progress_label_for_tool("listar_arquivos", {"caminho": "C:/x"}) == (
            "Lista o que existe numa pasta do projeto")
        assert O._progress_label_for_tool("nao_existe", {}) == "Executando ferramenta…"

    def test_titulo_autoral_continua_ganhando(self, setor_teste):
        """Isto entra no lugar do genérico, não por cima da voz que já existe."""
        assert O._tool_title("consultar_medida", {}).startswith(
            "Consultando a medida")

    def test_toda_execucao_mostra_em_cima_de_que_rodou(self):
        """O cartao de execucao e a caixa que ja existe; fechado, e uma linha."""
        assert O._tool_command("listar_arquivos", {"caminho": "C:/x"}) == "caminho: C:/x"
        assert O._tool_command("executar_python", {"codigo": "print(1)"}) == "print(1)"


class TestDeclaradoNoYaml:
    """O texto de cada passo mora no `tools.yaml`; o orquestrador só despacha."""

    def test_titulo_com_argumento(self):
        from sentury.harness.titulo_de_ferramenta import titulo_do_passo

        assert titulo_do_passo("executar_skill", {"nome": "pdf"}) == "Ativando a skill pdf"

    def test_argumento_ausente_cai_na_descricao_e_nao_mostra_a_chave(self):
        from sentury.harness.titulo_de_ferramenta import titulo_do_passo

        texto = titulo_do_passo("executar_skill", {})
        assert "{nome}" not in texto and texto != "Ativando a skill "

    def test_titulo_pelo_trecho_do_codigo(self):
        from sentury.harness.titulo_de_ferramenta import titulo_do_passo

        assert titulo_do_passo("executar_python", {"codigo": "df = pd.read_csv('x.csv')"}) == "Lendo o arquivo"
        assert titulo_do_passo("executar_python", {"codigo": "print(1)"}) == "Executando o passo em código"

    def test_recorte_dos_argumentos_vai_junto(self):
        from sentury.harness.titulo_de_ferramenta import titulo_do_passo

        assert titulo_do_passo("export_pdf", {"regiao": "sul", "periodo_inicio": "2026-01"}) == (
            "Gerando o PDF · Sul · 2026-01")

    def test_o_orquestrador_nao_guarda_texto_de_passo(self):
        from pathlib import Path

        fonte = Path("sentury/harness/orchestrator.py").read_text(encoding="utf-8")
        for texto in ("Montando a apresentação", "Procurando o gif", "Gerando o PDF"):
            assert texto not in fonte, texto
