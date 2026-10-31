"""A regua: apagado o pacote, o motor nao fala de area nenhuma.

Removidos os DomainPacks, nada relacionado a CX ou a qualquer area chega ao
modelo. Sem este teste, cada limpeza volta sozinha: alguem acrescenta um exemplo util no
prompt do motor, ninguem percebe, e seis meses depois o generalista abre a
conversa falando de NPS.

**O numero que importa nao e quantas vezes a palavra aparece no codigo**: e
quanto chega ao MODELO. Um comentario com "NPS" e divida; a mesma
palavra no prompt composto e defeito.
"""
import re

import pytest

# Nomes proprios e jargao que so existem porque o Sentury nasceu em CX. Sao
# palavras que um agente generalista nao tem motivo para conhecer.
VOCABULARIO_DE_SETOR = (
    "nps", "nls", "csat", "ces",
    "detrator", "promotor", "chamados", "sla", "touchpoint",
    "dmaic", "ishikawa", "six sigma",
)

# "chamado" fica de fora de proposito: em portugues e o particípio de chamar
# ("sem ter chamado a ferramenta"), e barrar isso seria barrar a lingua.


def _sem_acento(texto: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def _achados(texto: str):
    baixo = _sem_acento(str(texto or "").lower())
    return sorted({t for t in VOCABULARIO_DE_SETOR
                   if re.search(r"\b" + _sem_acento(t) + r"\b", baixo)})


@pytest.fixture
def generalista(monkeypatch):
    from sentury.domains import escolha

    monkeypatch.setattr(escolha, "ler", lambda *a, **k: "generalista")
    return None


class TestOPromptDoMotor:
    def test_nao_carrega_vocabulario_de_setor(self, generalista):
        from sentury.llm import prompts

        composto = prompts.system_persona_do_dominio()
        assert not _achados(composto), (
            "o generalista recebeu vocabulario de setor no prompt. "
            "Se a frase e util, ela pertence ao `responder.md` do pacote."
        )

    def test_nao_da_exemplos(self, generalista):
        """Exemplo puxa o motor para um dominio por definicao.

        A excecao e o contrato de EMISSAO (o formato exato que o modelo tem
        que escrever) que nao e ilustracao e sem o qual o codigo sai
        quebrado. Hoje ha um: o Python que gera HTML.
        """
        from sentury.llm import prompts

        composto = prompts.system_persona_do_dominio()
        exemplos = re.findall(r"ex\.:", composto)
        assert len(exemplos) <= 3, (
            f"{len(exemplos)} exemplos no prompt do generalista. "
            "O nucleo nao tem exemplo, nem neutro."
        )


class TestAsFerramentasDoMotor:
    def test_nenhuma_descricao_fala_de_setor(self, generalista):
        """O prompt limpo nao basta: a descricao da ferramenta tambem vai
        para o modelo, e ela vive noutro arquivo."""
        from sentury.tools.registry import (
            TOOL_REGISTRY, ferramenta_exposta, setor_da_ferramenta,
        )

        sujas = {}
        for nome, meta in TOOL_REGISTRY.items():
            if setor_da_ferramenta(nome) or not ferramenta_exposta(meta):
                continue
            texto = " ".join(str(meta.get(campo) or "")
                             for campo in ("descricao", "orientacao", "quando_usar"))
            if (achados := _achados(texto)):
                sujas[nome] = achados
        assert not sujas, f"ferramentas do motor com vocabulario de setor: {sujas}"


class TestADescoberta:
    def test_nao_oferece_o_que_nao_existe(self, generalista):
        """Sugerir o que o gate vai recusar e o jeito mais caro de dizer nao.

        Ferramenta de setor no catalogo do generalista e oferecida, chamada e
        barrada, e a volta do laco vai embora sem nada observado.
        """
        from sentury.tools.capability_catalog import build_catalog
        from sentury.tools.registry import TOOL_REGISTRY, setor_da_ferramenta

        catalogo = build_catalog(TOOL_REGISTRY)
        de_setor = [c.name for c in catalogo if setor_da_ferramenta(c.name)]
        assert not de_setor, f"descoberta oferecendo ao generalista: {de_setor}"

    def test_recusa_de_ferramenta_inexistente_instrui(self):
        """Instruir custa uma frase; obrigar custa um turno.

        A recusa de ferramenta inexistente devolvia a instrucao do gate de
        EXPORTACAO ("rode a analise certa primeiro"), que nao se aplica: o
        modelo nao tinha como se corrigir e tentava de novo.
        """
        from sentury.llm.prompts import build_block_instruction

        texto = build_block_instruction("analyze_nps", ["ferramenta_valida"], None)
        assert "nao existe" in texto and "search_tools" in texto
        assert "resultado computado" not in texto


class TestOQueOUsuarioRecebe:
    def test_o_nome_antigo_nao_assina_artefato(self):
        """PDF, dashboard e PPTX assinam "Sentury", sem o nome antigo do produto."""
        from sentury.renderers import html_dashboard

        fonte = __import__("inspect").getsource(html_dashboard)
        assert "Sentury Intelligence" not in fonte

    def test_o_nome_antigo_nao_volta_no_que_o_agente_le(self):
        """O nome é Sentury. O README, as skills, os setores e o cabeçalho que
        o Robin manda aos provedores chegam ao modelo ou a quem abre o
        projeto; os registros históricos em `docs/` ficam como estão."""
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[1]
        alvos = [raiz / "README.md", raiz / "sentury/plugins/robinbandit/config/sentury.yaml"]
        for pasta in ("sentury/skills", "sentury/domains/setores"):
            alvos += [p for p in (raiz / pasta).rglob("*") if p.suffix in (".md", ".yaml", ".yml")]
        com_o_nome = [str(p.relative_to(raiz)) for p in alvos
                      if "Sentury Intelligence" in p.read_text(encoding="utf-8")]
        assert com_o_nome == []


def test_prompt_de_compactacao_nao_fala_de_setor_nem_da_exemplo():
    """Ele roda em toda conversa longa; o exemplo de CX ensinava o resumo a
    falar de NPS em conversa sobre qualquer outra coisa."""
    from sentury.harness.context_budget import CONTEXTUALIZER_PROMPT

    assert not _achados(CONTEXTUALIZER_PROMPT)
    assert "ex:" not in CONTEXTUALIZER_PROMPT.lower()
    assert not re.search(r"\b(sudeste|regi[aã]o|filial)\b", CONTEXTUALIZER_PROMPT.lower())


def test_as_skills_do_motor_nao_falam_de_setor():
    """A skill entra no prompt quando e usada. Um exemplo de NPS numa skill de
    grafico ensina o generalista a desenhar NPS."""
    from pathlib import Path

    import sentury.skills as skills

    raiz = Path(skills.__file__).parent
    sujas = {}
    for arquivo in sorted(raiz.rglob("SKILL.md")):
        if (achados := _achados(arquivo.read_text(encoding="utf-8"))):
            sujas[str(arquivo.relative_to(raiz))] = achados
    assert not sujas, f"skills do motor com vocabulario de setor: {sujas}"


class TestAVoz:
    """A ligacao e o lugar onde a promessa custa mais caro: nao da para reler."""

    def test_o_generalista_nao_oferece_consulta_de_setor(self, generalista):
        from sentury.external import live_gateway

        assert live_gateway._tool_declarations() == []
        assert not _achados(live_gateway.LIVE_PERSONA)

    def test_a_voz_do_motor_nao_fala_de_setor(self):
        import inspect

        from sentury.external import live_gateway

        fonte = inspect.getsource(live_gateway).split('"""', 2)[2]  # sem a docstring do modulo
        assert not _achados(fonte), _achados(fonte)

    @pytest.mark.asyncio
    async def test_consulta_de_setor_e_recusada_no_generalista(self, generalista):
        from sentury.external import live_gateway

        resposta = await live_gateway.execute_live_tool("consultar_nps", None, {})
        assert "não faz parte" in resposta


def test_o_nucleo_nao_fala_do_dado_de_um_setor():
    """O nucleo entra em todo turno: o periodo do dataset de CX, a "acao
    corretiva" e "a analista que a lideranca consulta sobre o cliente" eram
    do pacote."""
    from sentury.llm.prompts import NUCLEO_DO_AGENTE

    baixo = NUCLEO_DO_AGENTE.lower()
    for termo in ("2026-", "ação corretiva", "duas fontes", "o cliente e a operação"):
        assert termo not in baixo, termo
