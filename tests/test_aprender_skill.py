"""O agente escreve as próprias skills sem tocar nas que vêm no repositório.

A escrita mora na casa do Sentury; skill embutida vira cópia do usuário na
primeira correção; criar avisa quando já existe uma parecida; toda escrita se
desfaz.
"""
from pathlib import Path

import pytest

from sentury.skills import escrita

EMBUTIDA = Path(escrita.pasta_embutida()) / "creative" / "grafico" / "SKILL.md"


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    return tmp_path


def test_criar_escreve_na_casa(casa):
    r = escrita.executar({"acao": "criar", "nome": "revisao-de-contrato",
                          "descricao": "revisa cláusulas de prestação de serviço",
                          "corpo": "## Quando usar\nContrato novo.\n\n## Passos\n1. Ler as cláusulas."})
    assert r["status"] == "criada"
    skill = casa / "skills" / "revisao-de-contrato" / "SKILL.md"
    assert skill.is_file() and "Ler as cláusulas" in skill.read_text(encoding="utf-8")


def test_nome_de_um_dia_e_recusado():
    r = escrita.executar({"acao": "criar", "nome": "fix-relatorio-julho", "descricao": "x", "corpo": "y"})
    assert "erro" in r


def test_criar_avisa_quando_ja_existe_parecida(casa):
    pedido = {"acao": "criar", "nome": "grafico-de-barras",
              "descricao": "gráfico de barras em png a partir de csv", "corpo": "1. Desenhar."}
    r = escrita.executar(pedido)
    assert r["status"] == "não criada"
    assert "grafico" in [p["nome"] for p in r["parecidas"]]
    assert not (casa / "skills" / "grafico-de-barras").exists()
    assert escrita.executar({**pedido, "mesmo_assim": True})["status"] == "criada"


def test_corrigir_embutida_cria_copia_e_nao_mexe_no_repositorio(casa):
    original = EMBUTIDA.read_text(encoding="utf-8")
    r = escrita.executar({"acao": "corrigir", "nome": "grafico",
                          "trecho": "# Gráfico em PNG", "novo": "# Gráfico em PNG\n\nUse eixo a partir do zero."})
    assert r["status"] == "corrigida" and r["copia_do_usuario"] is True
    assert EMBUTIDA.read_text(encoding="utf-8") == original
    copia = casa / "skills" / "grafico" / "SKILL.md"
    assert "eixo a partir do zero" in copia.read_text(encoding="utf-8")
    # A cópia do usuário vale sobre a embutida.
    assert Path(escrita._carregador().load_skill("grafico").path) == copia.parent.resolve()

    assert escrita.executar({"acao": "desfazer", "nome": "grafico"})["status"] == "desfeito"
    assert not copia.exists()
    assert Path(escrita._carregador().load_skill("grafico").path) == EMBUTIDA.parent.resolve()


def test_trecho_que_nao_aparece_uma_vez_nao_muda_nada(casa):
    r = escrita.executar({"acao": "corrigir", "nome": "grafico", "trecho": "texto que não existe", "novo": "x"})
    assert "erro" in r
    assert not (casa / "skills" / "grafico").exists()


def test_script_anexado_fica_na_skill_e_se_desfaz(casa):
    escrita.executar({"acao": "criar", "nome": "conversao-de-moeda", "descricao": "converte valores",
                      "corpo": "1. Rodar scripts/converter.py."})
    r = escrita.executar({"acao": "anexar", "nome": "conversao-de-moeda",
                          "arquivo": "scripts/converter.py", "conteudo": "print('ok')\n"})
    script = casa / "skills" / "conversao-de-moeda" / "scripts" / "converter.py"
    assert r["status"] == "anexado" and script.read_text(encoding="utf-8") == "print('ok')\n"
    escrita.executar({"acao": "desfazer", "nome": "conversao-de-moeda"})
    assert not script.exists()
    assert (casa / "skills" / "conversao-de-moeda" / "SKILL.md").is_file()


@pytest.mark.parametrize("arquivo", ["../fora.py", "scripts/../../fora.py", "outro/x.py", "SKILL.md"])
def test_anexo_fora_das_pastas_de_apoio_e_recusado(casa, arquivo):
    escrita.executar({"acao": "criar", "nome": "conversao-de-moeda", "descricao": "converte valores",
                      "corpo": "1. Passo."})
    assert "erro" in escrita.executar({"acao": "anexar", "nome": "conversao-de-moeda",
                                       "arquivo": arquivo, "conteudo": "x"})


async def test_o_catalogo_despacha_a_ferramenta(casa):
    from sentury.harness.state import AnalysisState
    from sentury.tools.catalog import execute_tool

    r = await execute_tool(None, AnalysisState.new("s", "u"), "aprender_skill",
                           {"acao": "criar", "nome": "revisao-de-contrato", "descricao": "revisa contrato",
                            "corpo": "1. Ler."})
    assert r["status"] == "criada"


def test_acrescentar_poe_a_licao_sob_a_secao_sem_copiar_trecho(casa):
    r = escrita.executar({"acao": "acrescentar", "nome": "grafico", "secao": "Armadilhas",
                          "novo": "- Gráfico de barras começa o eixo y no zero."})
    assert r["status"] == "acrescentada" and r["copia_do_usuario"] is True
    texto = (casa / "skills" / "grafico" / "SKILL.md").read_text(encoding="utf-8")
    assert "## Armadilhas\n\n- Gráfico de barras começa o eixo y no zero." in texto
    repetido = escrita.executar({"acao": "acrescentar", "nome": "grafico", "secao": "Armadilhas",
                                 "novo": "- Gráfico de barras começa o eixo y no zero."})
    assert repetido["status"] == "nada a mudar"
    escrita.executar({"acao": "desfazer", "nome": "grafico"})
    assert not (casa / "skills" / "grafico").exists()


def test_trecho_que_nao_bate_devolve_o_texto_atual(casa):
    r = escrita.executar({"acao": "corrigir", "nome": "grafico", "trecho": "texto inventado", "novo": "x"})
    assert "Texto atual de SKILL.md" in r["erro"] and "# Gráfico em PNG" in r["erro"]


def _duas_parecidas():
    escrita.executar({"acao": "criar", "nome": "conversao-de-moeda", "descricao": "converte valores entre moedas pela cotacao",
                      "corpo": "1. Use a PTAX."})
    escrita.executar({"acao": "criar", "nome": "cambio-de-valores", "descricao": "converte valores entre moedas pela cotacao do dia",
                      "corpo": "1. Arredonde em 2 casas.", "mesmo_assim": True})


def test_sobrepostas_acha_so_entre_as_skills_do_usuario(casa):
    _duas_parecidas()
    pares = escrita.sobrepostas()
    assert [p["skills"] for p in pares] == [["cambio-de-valores", "conversao-de-moeda"]]


def test_aposentar_guarda_a_pasta_e_desfazer_traz_de_volta(casa):
    _duas_parecidas()
    assert escrita.executar({"acao": "aposentar", "nome": "cambio-de-valores"})["status"] == "aposentada"
    assert not (casa / "skills" / "cambio-de-valores").exists()
    assert escrita._pasta_da_skill("cambio-de-valores") is None
    assert escrita.sobrepostas() == []
    assert escrita.executar({"acao": "desfazer", "nome": "cambio-de-valores"})["status"] == "desfeito"
    assert "Arredonde" in (casa / "skills" / "cambio-de-valores" / "SKILL.md").read_text(encoding="utf-8")


def test_skill_que_vem_pronta_nao_se_aposenta():
    assert "erro" in escrita.executar({"acao": "aposentar", "nome": "grafico"})
    assert EMBUTIDA.is_file()


def test_a_pausa_avisa_das_sobrepostas(casa):
    from sentury.harness.aprendizado import pergunta

    assert "parecem tratar quase da mesma tarefa" not in pergunta()
    _duas_parecidas()
    texto = pergunta()
    assert "cambio-de-valores e conversao-de-moeda" in texto and "`aposentar`" in texto
    assert "Use a PTAX" in texto and "Arredonde em 2 casas" in texto
