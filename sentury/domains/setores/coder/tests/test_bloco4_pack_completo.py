"""O pacote deixa de so adicionar ferramenta e passa a ensinar o setor.

Duas pecas que faltavam para "jogar dentro da pasta e so ligar":

`steering/` e contexto que entra sempre naquele setor, por regra. Skill e
procedimento recuperado quando o agente tem uma duvida; steering vale antes de
ele suspeitar de qualquer coisa.

E `mcp.json` no pacote: some na LEITURA e nunca na escrita. Gravar o servidor do
pacote no arquivo do usuario deixaria orfao quando o setor fosse desinstalado.
"""
from pathlib import Path

import pytest

from sentury.domains import steering
from sentury.domains.carregador import PREFIXO_MCP, mcp_do_pacote


def _pack(tmp_path: Path, nome: str = "teste") -> Path:
    alvo = tmp_path / nome
    (alvo / steering.PASTA).mkdir(parents=True)
    return alvo


def _play(pasta: Path, arquivo: str, cabecalho: str, corpo: str = "o corpo do playbook") -> None:
    (pasta / steering.PASTA / arquivo).write_text(
        "---" + chr(10) + cabecalho + chr(10) + "---" + chr(10) + corpo + chr(10),
        encoding="utf-8",
    )


# -------------------------------------------------------------- steering































# ------------------------------------------------------------------- mcp















# --------------------------------------------- o exemplo que vem no repo

def test_o_pacote_coder_traz_os_dois_exemplos():
    """O formato so existe de verdade quando ha um exemplo para copiar."""
    playbooks = steering.do_setor("coder")
    assert {p.quando for p in playbooks} == {"sempre", "arquivos"}

    (servidor,) = mcp_do_pacote("coder")
    assert servidor["id"].startswith(PREFIXO_MCP)
    # Exemplo nao sobe processo sozinho na primeira vez que alguem espia.
    assert servidor["ativo"] is False


# --------------------------------------- o motor para de ser de CX por dentro

def _mesa(monkeypatch, setor: str) -> list:
    """Os nomes que chegam ao modelo com aquele setor ligado.

    Fixa a ESCOLHA, nao o arquivo: onde o setor e persistido ja tem teste
    proprio, e mexer em `SENTURY_HOME` por variavel de ambiente nao funciona
    aqui: `settings` le uma vez, na importacao.
    """
    from sentury.domains import escolha
    from sentury.llm.tool_schemas import build_tool_schemas

    monkeypatch.setattr(escolha, "ler", lambda *a, **k: setor)
    return [s["function"]["name"] for s in build_tool_schemas() if "function" in s]
