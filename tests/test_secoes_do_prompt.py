"""A orientação de cada ferramenta viaja com a ferramenta.

Um prompt que descreve todas as ferramentas, estejam ou não na mesa, vaza
ferramenta de setor desligado e gasta contexto com o que não existe. Cada
ferramenta traz a própria seção: se ela não está montada, a seção não existe.
"""
import pytest

from sentury.domains import escolha
from sentury.llm.secoes import (
    Secao,
    bloco_de_ferramentas,
    montar,
    ordem_de,
    prompt_do_planejador,
    secoes_das_ferramentas,
)


# ------------------------------------------------------- a montagem

def test_a_ordem_manda():
    texto = montar([
        Secao("b", 100, "segundo"),
        Secao("a", 10, "primeiro"),
    ])
    assert texto == "primeiro\n\nsegundo"


def test_secao_vazia_nao_deixa_buraco():
    assert montar([Secao("a", 1, "x"), Secao("vazia", 2, "  "), Secao("b", 3, "y")]) == "x\n\ny"


def test_texto_pode_ser_calculado_na_hora():
    """Seção dinâmica é o que permite a persona mudar com o setor sem recarregar."""
    assert montar([Secao("a", 1, lambda: "calculado")]) == "calculado"


def test_secao_que_falha_nao_derruba_o_prompt():
    def explode():
        raise RuntimeError("fonte indisponivel")

    assert montar([Secao("ok", 1, "fica"), Secao("ruim", 2, explode)]) == "fica"


def test_nome_repetido_e_erro():
    """Duas seções com o mesmo nome = alguém registrou duas vezes, e a segunda
    venceria em silêncio."""
    with pytest.raises(ValueError, match="duplicada"):
        montar([Secao("a", 1, "x"), Secao("a", 2, "y")])


def test_a_ordem_de_um_papel_tem_folga():
    """Esparsa de propósito: cabe coisa no meio sem renumerar tudo."""
    assert ordem_de("PERSONA") < ordem_de("FERRAMENTAS") < ordem_de("SETOR")
    assert ordem_de("FERRAMENTAS", 3) == ordem_de("FERRAMENTAS") + 3


# ------------------------------------- só o que está na mesa entra

def test_ferramenta_fora_da_mesa_nao_contribui():
    nomes = [s.nome for s in secoes_das_ferramentas(["listar_arquivos"])]
    assert nomes == ["tool:listar_arquivos"]


def test_ferramenta_sem_orientacao_nao_vira_secao(monkeypatch):
    """Nem toda ferramenta precisa de orientação; a descrição do esquema basta."""
    from sentury.tools.registry import TOOL_REGISTRY

    monkeypatch.setitem(TOOL_REGISTRY, "sem_orientacao", {
        "categoria": "conhecimento", "descricao": "Consulta de teste.",
    })
    assert secoes_das_ferramentas(["sem_orientacao"]) == []


def test_nome_desconhecido_e_ignorado():
    assert secoes_das_ferramentas(["ferramenta_que_nao_existe"]) == []


def test_sem_ferramenta_nenhuma_o_bloco_some():
    """Bloco vazio com título seria um cabeçalho solto no prompt."""
    assert bloco_de_ferramentas([]) == ""


# ----------------------------------- as orientações que o benchmark ditou

@pytest.mark.parametrize("ferramenta,trecho", [
    ("listar_arquivos", "**/*"),
    ("listar_arquivos", "pasta de trabalho"),
    ("executar_python", "sqlite3"),
    ("executar_python", "script escrito só na resposta não roda"),
    ("entregar_arquivo", "nunca diga que entregou"),
])
def test_a_orientacao_cobre_o_erro_medido(ferramenta, trecho):
    bloco = bloco_de_ferramentas([ferramenta])
    assert trecho in bloco, bloco


# ------------------------------------------------- no prompt de verdade

def test_o_prompt_ganha_as_orientacoes():
    montado = prompt_do_planejador("BASE.")
    assert montado.startswith("BASE.")
    assert "QUANDO USAR CADA FERRAMENTA" in montado


def test_o_setor_entra_depois_das_ferramentas(monkeypatch):
    monkeypatch.setattr(escolha, "ler", lambda *a, **k: "setor_teste")
    montado = prompt_do_planejador("BASE.")
    i_ferramentas = montado.find("QUANDO USAR CADA FERRAMENTA")
    assert i_ferramentas > 0
    # O texto do setor é o último bloco: o específico vem depois do geral.
    assert montado.rfind("QUANDO USAR CADA FERRAMENTA") == i_ferramentas


def test_base_sem_nada_mais_continua_valendo(monkeypatch):
    """Falha aberta: sem setor e sem orientação, o prompt base ainda sai inteiro."""
    monkeypatch.setattr("sentury.llm.secoes.bloco_de_ferramentas", lambda *a, **k: "")
    monkeypatch.setattr(escolha, "ler", lambda *a, **k: "generalista")
    montado = prompt_do_planejador("SO A BASE.")
    assert montado.strip() == "SO A BASE."


def test_o_generalista_nao_recebe_orientacao_de_ferramenta_de_setor(monkeypatch):
    """A prosa sobre a ferramenta de setor some junto com ela."""
    monkeypatch.setattr(escolha, "ler", lambda *a, **k: "generalista")
    from sentury.llm.tool_schemas import build_tool_schemas
    from sentury.tools.registry import TOOL_REGISTRY

    na_mesa = [e["function"]["name"] for e in build_tool_schemas() if "function" in e]
    de_setor = [n for n in na_mesa if (TOOL_REGISTRY.get(n) or {}).get("setor")]
    assert de_setor == [], de_setor


def test_dica_do_shell_chega_ao_plano_em_texto(monkeypatch):
    """O plano em texto lê a orientação, não a descrição do esquema nativo."""
    from sentury.tools import shell

    monkeypatch.setattr(shell, "_DICA_DO_SHELL", "DICA-DO-SHELL-AQUI")
    texto = montar(secoes_das_ferramentas(["executar_comando"]))
    assert "DICA-DO-SHELL-AQUI" in texto
