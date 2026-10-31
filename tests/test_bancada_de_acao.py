"""A bancada recusa ação diferente da autorizada e espera o resultado real do cliente."""
import asyncio
import json

import pytest

from scripts.gravar_evals_de_acao import carregar_casos, pelo_tato, preparar, validar_chamada


@pytest.mark.parametrize("caso", list(carregar_casos()))
def test_os_casos_usam_ferramenta_declarada(caso, tmp_path):
    from sentury.tools.registry import TOOL_REGISTRY
    dados = carregar_casos()[caso]
    assert dados["ferramenta"] in TOOL_REGISTRY
    assert dados["capacidade"] and dados["contem"]
    validar_chamada(dados, dados["ferramenta"], dados["argumentos"], tmp_path)


@pytest.mark.parametrize("mudanca", [
    {"linguagem": "powershell"}, {"conteudo": "print(999)"},
    {"arquivo": "outro.py"}, {"argumentos": ["extra"]}, {"diretorio": "/fora"},
    {"cwd": "/fora"}, {"codigo": "print(999)"},
])
def test_script_diferente_nao_executa(mudanca, tmp_path):
    caso = carregar_casos()["script"]
    with pytest.raises(ValueError):
        validar_chamada(caso, caso["ferramenta"], {**caso["argumentos"], **mudanca}, tmp_path)


def test_nao_aceita_outro_executor(tmp_path):
    caso = carregar_casos()["script"]
    with pytest.raises(ValueError):
        validar_chamada(caso, "executar_comando", caso["argumentos"], tmp_path)


def test_casa_precisa_ser_vazia(tmp_path):
    (tmp_path / "arquivo.txt").write_text("preservar", encoding="utf-8")
    with pytest.raises(ValueError, match="vazia"):
        preparar(tmp_path)
    assert (tmp_path / "arquivo.txt").read_text(encoding="utf-8") == "preservar"


async def test_chamada_mcp_espera_resposta_sem_fabricar_dados(tmp_path):
    tarefa = asyncio.create_task(pelo_tato(tmp_path, "browser", {"acao": "snapshot"}))
    async def aguardar():
        while not list(tmp_path.glob("*.pedido.json")):
            await asyncio.sleep(0)
    await asyncio.wait_for(aguardar(), timeout=2)
    pedido = next(tmp_path.glob("*.pedido.json"))
    assert json.loads(pedido.read_text(encoding="utf-8")) == {"ferramenta": "browser", "argumentos": {"acao": "snapshot"}}
    assert not tarefa.done()
    resposta = {"ok": True, "observacao": "dado devolvido pelo cliente de teste"}
    pedido.with_name(pedido.name.replace(".pedido.json", ".resposta.json")).write_text(json.dumps(resposta), encoding="utf-8")
    assert await tarefa == resposta
