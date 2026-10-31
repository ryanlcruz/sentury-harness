"""O `browser` na mesa do modelo, sem roubar o `ler_pagina`.

A escada de percepção começa antes do navegador: ler texto de página pública é
o degrau barato. O navegador é para interagir.
"""
import pytest

from sentury.tools.capability_catalog import build_catalog, search_catalog
from sentury.tools.registry import TOOL_REGISTRY, ferramenta_exposta


def _primeira(consulta: str) -> str:
    return search_catalog(build_catalog(TOOL_REGISTRY), consulta)[0][0].name


def test_o_browser_esta_exposto_e_ensina_consequencia():
    meta = TOOL_REGISTRY["browser"]
    assert ferramenta_exposta(meta)
    assert "consequencia" in meta["orientacao"] and "ler_pagina" in meta["orientacao"]


@pytest.mark.parametrize("consulta", [
    "abre o site da empresa e clica no botao de vagas",
    "preenche o formulario de contato no site",
])
def test_pedido_de_interagir_acha_o_browser(consulta):
    assert _primeira(consulta) == "browser"


@pytest.mark.parametrize("consulta", [
    "leia esta pagina https://exemplo.com/sobre",
    "resuma o texto deste link",
])
def test_pedido_de_ler_continua_no_ler_pagina(consulta):
    assert _primeira(consulta) == "ler_pagina"


def test_o_generalista_recebe_a_descricao(monkeypatch):
    from sentury.domains import escolha
    from sentury.llm import prompts

    from sentury.tools.capability_catalog import build_catalog, render_manifest
    from sentury.tools.registry import TOOL_REGISTRY

    monkeypatch.setattr(escolha, "ler", lambda *a, **k: "generalista")
    assert "`browser`" in render_manifest(build_catalog(TOOL_REGISTRY, []))
