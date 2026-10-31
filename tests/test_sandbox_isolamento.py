"""O artefato anexado tem que ser o QUE ESTA execucao criou.

A deteccao varria o diretorio por "modificado nos ultimos 10 segundos". Com
duas requisicoes concorrentes gerando artefato ao mesmo tempo, isso pode
entregar o arquivo de um usuario para o OUTRO. Nao e higiene de repositorio, e
isolamento entre requisicoes.
"""
import asyncio

import pytest

from sentury.exec.python_exec import executar_python
from sentury.harness.anexo_do_resultado import _extract_recent_sandbox_artifact


class _Store:
    def get_feedbacks(self):
        import pandas as pd
        return pd.DataFrame([{"nps_score": 8}])

    def get_tickets(self):
        import pandas as pd
        return pd.DataFrame()

    def get_technicians(self):
        import pandas as pd
        return pd.DataFrame()


async def test_execucao_declara_o_que_criou(tmp_path, monkeypatch):
    from sentury.exec import python_exec
    monkeypatch.setattr(python_exec, "_SANDBOX_ROOT", tmp_path.resolve())

    r = await executar_python(_Store(), "resultado = save_html('painel.html', '<b>NPS</b>')")
    gerados = r.get("arquivos_gerados") or []
    assert any(g.endswith("painel.html") for g in gerados), r


async def test_execucao_sem_arquivo_declara_lista_vazia(tmp_path, monkeypatch):
    from sentury.exec import python_exec
    monkeypatch.setattr(python_exec, "_SANDBOX_ROOT", tmp_path.resolve())

    r = await executar_python(_Store(), "resultado = 1 + 1")
    assert r.get("arquivos_gerados") == []


def test_anexa_o_arquivo_declarado_e_ignora_o_vizinho(tmp_path):
    """O ponto do isolamento: existe outro arquivo recem-criado ao lado, e ele
    NAO pode ser anexado."""
    meu = tmp_path / "meu.html"
    meu.write_text("<b>meu</b>", encoding="utf-8")
    do_outro = tmp_path / "do_outro.html"
    do_outro.write_text("<b>do outro usuario</b>", encoding="utf-8")

    att, _ = _extract_recent_sandbox_artifact([str(meu)])
    assert att and att["filename"] == "meu.html"


def test_lista_vazia_cai_na_varredura_antiga():
    """Retaguarda pros caminhos que ainda nao declaram."""
    att, _ = _extract_recent_sandbox_artifact([])
    assert att is None or isinstance(att, dict)


def test_caminho_declarado_que_sumiu_nao_quebra(tmp_path):
    att, _ = _extract_recent_sandbox_artifact([str(tmp_path / "nao_existe.png")])
    assert att is None or isinstance(att, dict)
