"""MCP contra um servidor de verdade, não contra um dublê.

Fica fora da suíte por precisar de rede e do npx: `SENTURY_MCP_REAL=1` liga.
O dublê prova que o nosso código faz o que ele mesmo espera; só o servidor
real prova que o handshake, o enquadramento das mensagens e o formato do erro
batem com o protocolo: foi assim que descobrimos o que o cliente aguenta.
"""
from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("SENTURY_MCP_REAL"),
    reason="precisa de rede e npx; ligue com SENTURY_MCP_REAL=1",
)


def _spec(area: str) -> dict:
    return {
        "id": "fs-teste",
        "nome": "filesystem",
        "transporte": "stdio",
        "comando": "npx.cmd" if os.name == "nt" else "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", area],
        "ativo": True,
    }


@pytest.mark.asyncio
async def test_servidor_mcp_oficial_responde(tmp_path):
    from sentury.external import mcp_registry

    (tmp_path / "nota.txt").write_text("NPS de teste: -31.2", encoding="utf-8")
    spec = _spec(str(tmp_path))

    info = await mcp_registry.inspecionar(spec, timeout=180)
    assert info["conectado"], info.get("erro")
    nomes = {t["nome"] for t in info["tools"]}
    assert {"read_text_file", "list_directory"} <= nomes

    lido = await mcp_registry.chamar(
        spec, "read_text_file", {"path": str(tmp_path / "nota.txt")}, timeout=180
    )
    assert lido["ok"] and "-31.2" in lido["texto"]

    # Nome errado volta como erro do servidor, não como exceção nossa.
    ruim = await mcp_registry.chamar(spec, "nao_existe", {}, timeout=180)
    assert not ruim["ok"] and "not found" in str(ruim.get("erro", "")).lower()
