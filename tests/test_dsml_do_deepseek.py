"""A chamada do DeepSeek que chega como texto (DSML) vira a chamada que era.

O texto abaixo e o formato que o deepseek-v4-pro devolve pelo OpenRouter. Sem
a conversao, a marcacao iria para a pessoa como se fosse a resposta final.
"""
import json

import pytest

from robinbandit.providers.dsml import chamadas_do_dsml
from robinbandit.providers.openai_compat import OpenAICompatProvider

VISTO_NA_BANCADA = (
    '\n<｜DSML｜tool_calls>\n<｜DSML｜invoke name="executar_comando">\n'
    '<｜DSML｜parameter name="comando" string="true">git log -1 --format="%h %s"</｜DSML｜parameter>\n'
    '<｜DSML｜parameter name="descricao" string="true">Hash curto</｜DSML｜parameter>\n'
    '</｜DSML｜invoke>\n</｜DSML｜tool_calls>'
)


def test_chamada_da_bancada_vira_tool_call():
    resto, chamadas = chamadas_do_dsml(VISTO_NA_BANCADA)
    assert resto == ""
    assert chamadas[0]["function"]["name"] == "executar_comando"
    args = json.loads(chamadas[0]["function"]["arguments"])
    assert args == {"comando": 'git log -1 --format="%h %s"', "descricao": "Hash curto"}


def test_sem_abertura_e_com_json():
    texto = ('Vou ler.\n<｜DSML｜invoke name="ler_arquivo">'
             '<｜DSML｜parameter name="caminho" string="true">a.csv</｜DSML｜parameter>'
             '<｜DSML｜parameter name="linhas" string="false">10</｜DSML｜parameter>'
             '</｜DSML｜invoke>')
    resto, chamadas = chamadas_do_dsml(texto)
    assert resto == "Vou ler."
    assert json.loads(chamadas[0]["function"]["arguments"]) == {"caminho": "a.csv", "linhas": 10}


def test_texto_comum_passa_intacto():
    assert chamadas_do_dsml("O total foi 773.") == ("O total foi 773.", [])


class _Resposta:
    status_code = 200
    headers = {}
    text = ""

    def __init__(self, conteudo):
        self._c = conteudo

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}, "finish_reason": "stop"}]}


async def test_adapter_converte_so_quando_mandou_ferramenta(monkeypatch):
    class _Cliente:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resposta(VISTO_NA_BANCADA)

    import robinbandit.providers.openai_compat as modulo

    monkeypatch.setattr(modulo.httpx, "AsyncClient", _Cliente)
    p = OpenAICompatProvider(name="or", base_url="http://x", api_key="k", models=["m"])
    texto = await p.complete([{"role": "user", "content": "oi"}], tools=[{"type": "function"}])
    assert texto == "" and p.last_tool_calls[0]["function"]["name"] == "executar_comando"
