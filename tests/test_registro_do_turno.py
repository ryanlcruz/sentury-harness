"""O registro do turno: gravado a cada passo, sobrevive ao reinício do
servidor e deixa a pessoa continuar sem repetir o que já foi feito."""
import asyncio

import pytest
from fastapi import HTTPException

from sentury.harness import registro_do_turno as reg
from sentury.harness.state import AnalysisState


@pytest.fixture(autouse=True)
def _pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "pasta", lambda: tmp_path / "turnos")
    reg._limpar_para_testes()
    yield tmp_path / "turnos"
    reg._limpar_para_testes()


@pytest.fixture
def ferramentas_falsas(monkeypatch):
    from sentury.tools import catalog

    portas = {}

    async def executar(store, state, tool, arguments, *a):
        if tool in portas:
            portas[tool][0].set()
            await portas[tool][1].wait()
        if tool == "ler_arquivo" and arguments.get("caminho") == "quebra.txt":
            return {"status": "error", "erro": "não existe"}
        return {"status": "ok"}

    monkeypatch.setattr(catalog, "_executar_ferramenta", executar)
    return portas


async def test_cada_ferramenta_vira_um_passo(ferramentas_falsas):
    from sentury.tools.catalog import execute_tool

    state = AnalysisState.new("r1", "u")
    reg.abrir(state, "leia e grave")
    await execute_tool(None, state, "ler_arquivo", {"caminho": "a.txt"})
    await execute_tool(None, state, "ler_arquivo", {"caminho": "quebra.txt"})
    await execute_tool(None, state, "escrever_arquivo", {"caminho": "b.md", "conteudo": "x" * 5000})
    reg.fechar("r1", reg.CONCLUIDO)

    gravado = reg.ler("r1")
    assert gravado["status"] == "terminado" and gravado["motivo_de_termino"] == "concluido"
    assert [(p["ferramenta"], p["status"], p["efeito_colateral"]) for p in gravado["passos"]] == [
        ("ler_arquivo", "ok", False), ("ler_arquivo", "erro", False), ("escrever_arquivo", "ok", True)]
    # O conteúdo do arquivo não vai para o registro, só o começo.
    assert len(gravado["passos"][2]["argumentos"]["conteudo"]) <= reg.TETO_DE_ARGUMENTO + 1


async def test_sem_turno_aberto_nada_e_gravado(ferramentas_falsas, _pasta):
    from sentury.tools.catalog import execute_tool

    await execute_tool(None, AnalysisState.new("solto", "u"), "escrever_arquivo", {"caminho": "b.md"})
    assert reg.ler("solto") is None


async def test_o_servidor_cai_no_meio_da_escrita_e_a_pessoa_continua(ferramentas_falsas):
    """A escrita começou e o servidor caiu antes de ela acabar. Na subida, o
    turno vira `reinicio`, com a escrita `incerto`. Continuar põe no turno
    seguinte o que já foi feito, dizendo para conferir antes de repetir."""
    from sentury.tools.catalog import execute_tool

    comecou, nunca = asyncio.Event(), asyncio.Event()
    ferramentas_falsas["escrever_arquivo"] = (comecou, nunca)
    state = AnalysisState.new("r2", "u")
    state.funcoes_ativas = ["computador", "goal"]
    reg.abrir(state, "gere o relatório e mande por e-mail")
    await execute_tool(None, state, "ler_arquivo", {"caminho": "vendas.csv"})
    escrita = asyncio.create_task(execute_tool(None, state, "escrever_arquivo", {"caminho": "relatorio.md"}))
    await comecou.wait()

    # O processo morre aqui: o que estava em memória some.
    em_disco = reg.ler("r2")
    assert em_disco["status"] == "rodando" and em_disco["passos"][-1]["status"] == "rodando"
    assert em_disco["funcoes"] == ["computador", "goal"]
    reg._limpar_para_testes()
    escrita.cancel()
    await asyncio.gather(escrita, return_exceptions=True)

    assert reg.recuperar_no_inicio() == ["r2"]
    depois = reg.ler("r2")
    assert depois["status"] == "reinicio"
    assert [p["status"] for p in depois["passos"]] == ["ok", "incerto"]

    assert reg.continuar("r2")["status"] == "retomado"
    novo = AnalysisState.new("r2", "u")
    reg.abrir(novo, "gere o relatório e mande por e-mail")
    nota = novo.history[-1]["content"]
    assert nota.startswith("[INSTRUÇÃO DO SISTEMA:")
    assert "gere o relatório e mande por e-mail" in nota and "vendas.csv" in nota
    assert "escrever_arquivo(caminho=relatorio.md): incerto" in nota and "Não repita" in nota
    assert reg.ler("r2")["status"] == "rodando", "a nota tem de ser consumida uma vez"


def test_dispensar_e_continuar_so_valem_depois_de_reinicio():
    reg.abrir(AnalysisState.new("r3", "u"), "x")
    assert reg.continuar("r3") is None and not reg.dispensar("r3")
    reg._limpar_para_testes()
    reg.recuperar_no_inicio()
    assert reg.dispensar("r3") and reg.ler("r3")["status"] == "dispensado"
    assert reg.recuperar_no_inicio() == []


@pytest.mark.parametrize("resultado, motivo", [
    ({"message": "ok"}, "concluido"),
    ({"message": "", "permissao": {"chave": "k"}}, "esperando_aprovacao"),
    ({"message": "", "clarification": {"intro": "?"}}, "esperando_resposta"),
    ({"message": "", "deliberation": {"stop_reason": "budget_exhausted"}}, "orcamento"),
    (None, "falha"),
])
def test_motivo_de_termino(resultado, motivo):
    assert reg.motivo_do_resultado(resultado) == motivo


async def test_endpoints():
    from sentury import main

    assert await main.turno_da_sessao("r4", None) == {}
    with pytest.raises(HTTPException) as erro:
        await main.continuar_turno("r4", None)
    assert erro.value.status_code == 409
    reg.abrir(AnalysisState.new("r4", "u"), "x")
    reg._limpar_para_testes()
    reg.recuperar_no_inicio()
    assert (await main.turno_da_sessao("r4", None))["status"] == "reinicio"
    assert await main.continuar_turno("r4", None) == {"mensagem": "x", "funcoes": []}


def test_bloqueio_de_computador_nao_inventa_gate_de_exportacao():
    from sentury.llm.prompts import build_block_instruction

    texto = build_block_instruction("computador", ["ligue @computador"], AnalysisState.new("s", "u"))
    assert "@computador" in texto
    assert "executar_python" not in texto


def test_historico_antigo_recupera_pedido_real_sem_trocar_continuacao_legitima():
    pedido = "acesse meu computador e liste meus projetos"
    nota = reg.nota_de_retomada({"pedido": pedido, "passos": []})
    state = AnalysisState.from_dict({
        "session_id": "s", "user_id": "u",
        "history": [
            {"role": "user", "content": "Continue de onde parou."},
            {"role": "system", "content": nota},
            {"role": "user", "content": "Continue de onde parou."},
        ],
    })
    assert state.history[0]["content"] == "Continue de onde parou."
    assert state.history[2]["content"] == pedido


class TestNaLista:
    """O que a lista de conversas mostra do último turno, para o que espera a
    pessoa aparecer sem ela abrir cada conversa."""

    @pytest.mark.parametrize("motivo, na_lista", [
        (reg.ESPERANDO_APROVACAO, "aguardando_aprovacao"),
        (reg.ESPERANDO_RESPOSTA, "aguardando_resposta"),
        (reg.FALHA, "falhou"),
        (reg.CONCLUIDO, None),
        (reg.PARADO, None),
    ])
    def test_como_o_turno_terminou(self, motivo, na_lista):
        reg.abrir(AnalysisState.new("l1", "u"), "x")
        assert reg.estado_na_lista("l1") == "trabalhando"
        reg.fechar("l1", motivo)
        assert reg.estado_na_lista("l1") == na_lista

    def test_reinicio_e_sem_registro(self):
        assert reg.estado_na_lista("nunca") is None
        reg.abrir(AnalysisState.new("l2", "u"), "x")
        reg._limpar_para_testes()
        reg.recuperar_no_inicio()
        assert reg.estado_na_lista("l2") == "interrompido"

    @pytest.mark.parametrize("motivo", [reg.ESPERANDO_APROVACAO, reg.ESPERANDO_RESPOSTA])
    def test_fechar_o_cartao_tira_da_espera(self, motivo):
        reg.abrir(AnalysisState.new("l3", "u"), "x")
        reg.fechar("l3", motivo)
        assert reg.dispensar("l3") and reg.estado_na_lista("l3") is None

    def test_turno_concluido_nao_se_dispensa(self):
        reg.abrir(AnalysisState.new("l4", "u"), "x")
        reg.fechar("l4", reg.CONCLUIDO)
        assert not reg.dispensar("l4") and reg.ler("l4")["status"] == "terminado"

    async def test_a_lista_de_conversas_traz_o_estado(self, monkeypatch):
        import sentury.main as main

        async def listar(user_id):
            return [{"session_id": "l5", "title": "a"}, {"session_id": "l6", "title": "b"}]

        monkeypatch.setattr(main.session_index, "list", listar)
        reg.abrir(AnalysisState.new("l5", "u"), "x")
        reg.fechar("l5", reg.ESPERANDO_APROVACAO)
        r = await main.sessions(user_id="u", limit=30, _=None)
        assert [(s["session_id"], s["estado_do_turno"]) for s in r["sessions"]] == [
            ("l5", "aguardando_aprovacao"), ("l6", None)]
