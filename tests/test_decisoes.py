"""Decisões da equipe: um .md por decisão, lembradas por quem precisa."""
import time

import pytest

from sentury.harness.state import AnalysisState
from sentury.memory import decisoes


@pytest.fixture(autouse=True)
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    return tmp_path


def test_cada_decisao_e_um_md_e_reabrir_reescreve_o_mesmo(casa):
    """O arquivo é a decisão: legível por quem abre a pasta, e o assunto
    reaberto atualiza o mesmo arquivo em vez de deixar duas versões."""
    primeiro = decisoes.registrar("mesa:m1", "Corte no time", "Demitir 3 pessoas do suporte.", ["bruno", "nina"])
    assert primeiro.parent == casa / "decisoes" and primeiro.suffix == ".md"
    assert "# Corte no time" in primeiro.read_text(encoding="utf-8")
    de_novo = decisoes.registrar("mesa:m1", "Corte no time", "Demitir 2 pessoas, não 3.", ["bruno", "nina"])
    assert de_novo == primeiro and len(list((casa / "decisoes").glob("*.md"))) == 1
    assert decisoes.listar()[0]["resumo"] == "Demitir 2 pessoas, não 3."


def test_o_turno_ve_uma_linha_por_decisao_com_o_caminho():
    """Entra o essencial e onde ler o resto: o contexto não cresce com o acervo."""
    caminho = decisoes.registrar("mesa:m1", "Corte no time", "Demitir 3 pessoas do suporte. " * 20, ["bruno"])
    secao = decisoes.para_o_turno("abrimos 3 vagas no suporte")
    assert secao.startswith("### DECISÕES ANTERIORES")
    linha = secao.splitlines()[1]
    assert "Corte no time" in linha and str(caminho) in linha and len(linha) < 400


def test_residente_lembra_so_do_que_viveu():
    """Quem não estava na decisão não a carrega: quem lembra conta aos colegas."""
    decisoes.registrar("mesa:m1", "Corte no time", "Demitir 3 pessoas.", ["bruno", "nina"])
    assert "Corte no time" in decisoes.para_o_turno("vagas", agente="bruno")
    assert decisoes.para_o_turno("vagas", agente="vera") is None
    assert "Corte no time" in decisoes.para_o_turno("vagas")


def test_decisao_antiga_volta_quando_o_pedido_se_parece_com_ela():
    antes = time.time() - 400 * 86400
    decisoes.registrar("mesa:velha", "Fornecedor do almoço", "Trocar o fornecedor do almoço de boas-vindas.",
                       ["nina"], em=antes)
    assert decisoes.para_o_turno("qual era o problema com o fornecedor do almoço?") is not None
    assert decisoes.para_o_turno("configurar o servidor de e-mail") is None


def test_mesa_fechada_vira_decisao_e_chega_ao_contexto_do_turno():
    from sentury.harness.contexto_do_mundo import decisoes as do_turno
    from sentury.residentes import mesa, registro

    registro.criar({"nome": "atlas", "papel": "planejador", "objetivo": "organizar",
                    "ferramentas": ["ler_arquivo"]})
    assunto = mesa.abrir("Corte no time", "pessoa", "@atlas")
    mesa.falar(assunto.id, "atlas", "proposta: 3 pessoas")
    mesa.fechar(assunto.id, "Demitir 3 pessoas do suporte.", por="atlas")
    state = AnalysisState(session_id="s", user_id="u")
    state.history = [{"role": "user", "content": "abrimos 3 vagas"}]
    assert "Demitir 3 pessoas do suporte." in do_turno(state)


def test_ferramenta_anota_e_busca_decisao_fora_da_mesa():
    """Decisão tomada no chat ("anote que o Bruno coordena") vira arquivo e se acha
    depois pela busca, mesmo sem ter passado pela Mesa."""
    import asyncio
    from pathlib import Path

    from sentury.residentes.ferramentas import executar

    state = AnalysisState(session_id="conversa-1", user_id="u")
    anotada = asyncio.run(executar("decisao", {"acao": "anotar", "titulo": "Coordenação do suporte",
                                                "decisao": "Bruno coordena o suporte a partir de hoje."}, state))
    assert anotada["ok"] and Path(anotada["arquivo"]).exists()
    achadas = asyncio.run(executar("decisao", {"acao": "buscar", "termo": "quem coordena o suporte"}, state))
    assert [d["titulo"] for d in achadas["decisoes"]] == ["Coordenação do suporte"]
    assert not asyncio.run(executar("decisao", {"acao": "anotar", "titulo": "sem texto"}, state))["ok"]
