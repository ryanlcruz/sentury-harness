"""Toda implementação de um contrato passa pelo mesmo teste.

Trocar uma peça por outra só é fácil quando a nova cumpre o contrato inteiro.
Sem um teste comum, a troca muda o comportamento sem ninguém ver.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentury.domains.carregador import descobrir, ler
from sentury.residentes import browser_da_caixa
from sentury.tools.browser_chrome_provider import ChromeTabProvider
from sentury.tools.browser_chrome_remoto import ChromeRemotoProvider
from sentury.tools.browser_contracts import Action, Observation
from sentury.tools.browser_fake_provider import FakeBrowserProvider
from sentury.tools.browser_playwright_provider import PlaywrightBrowserProvider
from sentury.tools.browser_provider import BrowserProvider
from sentury.tools.registry import TOOL_REGISTRY

FIXTURE_DO_SETOR = Path(__file__).parent / "fixtures" / "setor_teste"


# ------------------------------------------------------------- navegador

def _pagina(tmp_path):
    arquivo = tmp_path / "pagina.html"
    arquivo.write_text("<html><head><title>Teste</title></head><body><a href='#'>Entrar</a></body></html>",
                       encoding="utf-8")
    return arquivo


FABRICAS = {
    FakeBrowserProvider: lambda tmp: FakeBrowserProvider(_pagina(tmp)),
    PlaywrightBrowserProvider: lambda tmp: PlaywrightBrowserProvider(),
    ChromeTabProvider: lambda tmp: ChromeTabProvider(),
    # A ponte remota fala HTTP com a API; aqui ela não alcança nada.
    ChromeRemotoProvider: lambda tmp: ChromeRemotoProvider(SimpleNamespace(
        disponivel=lambda: False, sem_esperar=lambda *a, **k: False, chamar=None)),
    browser_da_caixa.Provedor: lambda tmp: browser_da_caixa.Provedor(
        SimpleNamespace(nome="conformidade", criado_em="2026-10-10")),
}


def _todas_as_subclasses(classe):
    for sub in classe.__subclasses__():
        yield sub
        yield from _todas_as_subclasses(sub)


def test_toda_implementacao_de_navegador_esta_na_conformidade():
    """Provedor novo do Sentury sem fábrica aqui é provedor sem conformidade.
    Dublês declarados nos testes ficam de fora."""
    do_sentury = {c for c in _todas_as_subclasses(BrowserProvider) if c.__module__.startswith("sentury.")}
    faltando = {c.__name__ for c in do_sentury} - {c.__name__ for c in FABRICAS}
    assert not faltando, f"sem teste de conformidade: {sorted(faltando)}"


@pytest.mark.parametrize("classe", list(FABRICAS), ids=lambda c: c.__name__)
def test_provedor_de_navegador_cumpre_o_contrato_sem_abrir_navegador(classe, tmp_path):
    provedor = FABRICAS[classe](tmp_path)
    assert isinstance(provedor, BrowserProvider)
    assert isinstance(provedor.name, str) and provedor.name.strip()
    assert isinstance(provedor.is_available(), bool)
    assert provedor.close_session("conformidade-sessao-que-nao-existe") is False
    assert provedor.emergency_cleanup("conformidade-sessao-que-nao-existe") is None


async def test_sessao_do_provedor_fala_o_contrato(tmp_path):
    """Com o provedor que roda em memória: sessão com id, ação vira observação,
    fechar a sessão conhecida devolve True."""
    provedor = FakeBrowserProvider(_pagina(tmp_path))
    sessao = provedor.create_session("tarefa-1")
    assert isinstance(sessao.session_id, str) and sessao.session_id
    observacao = await sessao.execute(Action("snapshot"))
    assert isinstance(observacao, Observation)
    assert provedor.close_session(sessao.session_id) is True


# ------------------------------------------------------------- setores

def _pacotes():
    pacotes = list(descobrir())
    do_teste = ler(FIXTURE_DO_SETOR)
    if do_teste is not None:
        pacotes.append(do_teste)
    return pacotes


def _ferramentas_citadas(pack):
    """Todo nome de ferramenta que o pacote usa em algum campo."""
    citadas = set(pack.entregas) | set(pack.titulos_de_passo) | set(pack.colunas_de_grafico)
    citadas |= set(pack.titulos_de_painel) | set(pack.titulos_de_secao) | set(pack.texto_de_terceiros)
    if pack.ferramenta_de_causa:
        citadas.add(pack.ferramenta_de_causa)
    for item in pack.dicas_de_grafico:
        citadas.add(item[0])
    for colecao in (pack.fontes_de_dados, pack.guardas):
        for item in colecao:
            if isinstance(item, dict) and item.get("ferramenta"):
                citadas.add(item["ferramenta"])
    return citadas


@pytest.mark.parametrize("pack", _pacotes(), ids=lambda p: p.name)
def test_setor_so_cita_ferramenta_que_existe(pack, setor_teste):
    faltando = sorted(n for n in _ferramentas_citadas(pack) if n not in TOOL_REGISTRY)
    assert not faltando, f"{pack.name} cita ferramenta que não existe: {faltando}"


@pytest.mark.parametrize("pack", _pacotes(), ids=lambda p: p.name)
def test_metricas_do_setor_sao_coerentes(pack):
    nomes = pack.metric_names
    assert set(pack.higher_is_better) <= nomes, pack.name
    assert set(pack.metric_meta) <= nomes, pack.name
    for dimensao, valores in pack.dimensoes.items():
        assert all(isinstance(v, str) for v in valores), (pack.name, dimensao)


@pytest.mark.parametrize("pack", _pacotes(), ids=lambda p: p.name)
def test_ferramenta_declarada_pelo_setor_e_dele(pack, setor_teste):
    """Ferramenta com `setor` aponta para um pacote que existe."""
    nomes = {p.name for p in _pacotes()}
    alheias = sorted(n for n, m in TOOL_REGISTRY.items() if m.get("setor") and m["setor"] not in nomes)
    assert not alheias, f"ferramenta de setor sem pacote: {alheias}"
