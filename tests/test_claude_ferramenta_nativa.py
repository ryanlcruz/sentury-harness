"""O Claude pela API com ferramenta nativa (blocos tool_use e tool_result).

Sem isto o adapter ignorava `tools=`, a cadeia o tirava da lista em turno com
ferramenta, e o Dedicado sem o Codex caia no caminho antigo do planner.
"""
import json

import httpx
import pytest

from robinbandit.providers import claude_provider
from robinbandit.providers.claude_provider import ClaudeProvider, _split_messages
from robinbandit.routing.chain import suporta_ferramentas

FERRAMENTAS = [{"type": "function", "function": {
    "name": "listar_arquivos", "description": "Lista uma pasta.",
    "parameters": {"type": "object", "properties": {"caminho": {"type": "string"}}}}}]

CONVERSA = [
    {"role": "system", "content": "Você é o Sentury."},
    {"role": "user", "content": "o que tem na pasta?"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "toolu_1", "type": "function",
     "function": {"name": "listar_arquivos", "arguments": json.dumps({"caminho": "."})}}]},
    {"role": "tool", "tool_call_id": "toolu_1", "content": "a.py b.py"},
    {"role": "user", "content": "[Contexto do turno: hoje]"},
]


def test_a_cadeia_ve_que_o_claude_aceita_ferramenta():
    assert suporta_ferramentas(ClaudeProvider("k", ["claude-x"]))


def test_chamada_e_resultado_viram_blocos_da_anthropic():
    sistema, msgs = _split_messages(CONVERSA, nativo=True)
    assert sistema == "Você é o Sentury."
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    uso = msgs[1]["content"][0]
    assert uso == {"type": "tool_use", "id": "toolu_1", "name": "listar_arquivos", "input": {"caminho": "."}}
    resultado = msgs[2]["content"][0]
    assert resultado["type"] == "tool_result" and resultado["tool_use_id"] == "toolu_1"
    assert not any(b.get("type") == "text" and not b.get("text") for m in msgs for b in m["content"])


async def test_resposta_com_tool_use_vira_last_tool_calls(monkeypatch):
    enviado = {}

    async def falso_post(self, url, headers=None, json=None):
        enviado.update(json)
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "content": [{"type": "text", "text": "Vou listar a pasta."},
                        {"type": "tool_use", "id": "toolu_2", "name": "listar_arquivos", "input": {"caminho": "."}}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", falso_post)
    p = ClaudeProvider("k", ["claude-x"])
    texto = await p.complete(CONVERSA[:2], tools=FERRAMENTAS)

    assert texto == "Vou listar a pasta."
    assert enviado["tools"][0]["name"] == "listar_arquivos"
    assert enviado["tools"][0]["input_schema"]["properties"]["caminho"]["type"] == "string"
    chamada = p.last_tool_calls[0]
    assert chamada["id"] == "toolu_2" and chamada["function"]["name"] == "listar_arquivos"
    assert json.loads(chamada["function"]["arguments"]) == {"caminho": "."}


async def test_sem_ferramentas_continua_como_antes(monkeypatch):
    async def falso_post(self, url, headers=None, json=None):
        assert "tools" not in json
        assert isinstance(json["messages"][0]["content"], str)
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"content": [{"type": "text", "text": "oi"}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", falso_post)
    p = ClaudeProvider("k", ["claude-x"])
    assert await p.complete([{"role": "user", "content": "oi"}]) == "oi"
    assert p.last_tool_calls is None
