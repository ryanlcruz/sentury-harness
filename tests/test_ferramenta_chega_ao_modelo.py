"""Toda ferramenta disponível precisa aparecer para o modelo."""
import pytest

from sentury.harness import orchestrator as orq
from sentury.llm import prompts
from sentury.tools.registry import TOOL_REGISTRY, ferramenta_exposta, sempre_exposta
from sentury.harness.pausa_do_turno import autorizacao_pendente


def _tudo_que_o_modelo_le(setor: str = "setor_teste") -> str:
    """O que vai em toda chamada: o mapa de capacidades (uma linha por
    ferramenta), a persona e o prompt do planejador, montados com o setor."""
    from sentury.domains import escolha
    from sentury.tools.capability_catalog import build_catalog, render_manifest

    original = escolha.ler
    try:
        escolha.ler = lambda *a, **k: setor
        texto = render_manifest(build_catalog(TOOL_REGISTRY, []))
        texto += prompts.system_persona_do_dominio()
        texto += orq._prompt_do_planejador()
    finally:
        escolha.ler = original

    for nome in dir(orq):
        if nome.endswith("_PROMPT"):
            texto += str(getattr(orq, nome))
    return texto


def test_toda_ferramenta_registrada_aparece_para_o_modelo():
    visivel = _tudo_que_o_modelo_le()
    ausentes = sorted(
        nome for nome, meta in TOOL_REGISTRY.items()
        if sempre_exposta(meta)
        and (not meta.get("setor") or meta["setor"] == "setor_teste")
        and nome not in visivel
    )
    assert not ausentes, f"registradas mas invisiveis ao modelo: {ausentes}"


def test_ferramenta_legada_pode_existir_sem_vazar_ao_modelo():
    texto = _tudo_que_o_modelo_le()
    assert "save_analysis" not in texto
    assert "pesquisar_web" not in texto


def test_checar_pacote_esta_no_catalogo():
    assert "checar_pacote" in TOOL_REGISTRY
    assert "malware" in TOOL_REGISTRY["checar_pacote"]["descricao"].lower()


@pytest.mark.asyncio
async def test_checar_pacote_responde_pelo_despacho():
    from sentury.tools import catalog

    saida = await catalog.execute_tool(
        None, None, "checar_pacote", {"pacote": "requests", "ecossistema": "PyPI"})
    assert isinstance(saida, dict) and "permitido" in saida


def test_pedido_de_autorizacao_carrega_o_comando():
    """Sem o comando no payload a tela mandava string vazia e o POST voltava
    422: nenhum dos quatro botoes de autorizacao funcionava."""
    from pathlib import Path

    from sentury.tools.arquivos import _pedir_autorizacao

    pedido = _pedir_autorizacao("escrever_arquivo", Path("x.md").resolve(), "sess-teste")
    assert pedido is not None, "escrita deveria pedir autorizacao"
    assert pedido["comando"].startswith("escrever_arquivo ")
    assert pedido["chave"] and pedido["motivo"]


def test_harness_pede_autorizacao_antes_do_primeiro_passo():
    """Parar no meio joga fora o que ja rodou: o proximo turno recomeca o plano
    e refaz as mesmas buscas."""
    from sentury.harness.state import AnalysisState

    state = AnalysisState(session_id="sess-plano", user_id="u")
    plano = [
        {"tool": "buscar_web", "arguments": {"consulta": "fastapi"}},
        {"tool": "escrever_arquivo", "arguments": {"caminho": "fastapi.md", "conteudo": "x"}},
    ]
    pendente = autorizacao_pendente(None, plano, state)
    assert pendente is not None, "a escrita no plano deveria ser vista antes de executar"
    assert pendente["ferramenta"] == "escrever_arquivo"
    assert pendente["comando"].startswith("escrever_arquivo ")


def test_plano_so_de_leitura_nao_pede_nada():
    from sentury.harness.state import AnalysisState

    state = AnalysisState(session_id="sess-leitura", user_id="u")
    plano = [{"tool": "buscar_web", "arguments": {"consulta": "x"}},
             {"tool": "ler_arquivo", "arguments": {"caminho": "README.md"}}]
    assert autorizacao_pendente(None, plano, state) is None
