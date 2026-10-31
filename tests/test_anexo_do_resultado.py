"""O resultado da ferramenta vira o que o usuario ve.

`anexo_do_resultado` faz uma coisa so: sandbox, export binario e a entrega
declarada pelo setor. Ele devolve um rumo, e quem executa o passo traduz esse
rumo em seguir para o proximo passo ou parar o plano. Confundir os dois faz o
turno continuar quando deveria encerrar.
"""
import inspect
from types import SimpleNamespace

import pytest

from sentury.harness.anexo_do_resultado import anexo_do_resultado
from sentury.harness.execucao_do_passo import executar as executar_passo
from sentury.harness.orchestrator import SenturyOrchestrator

FONTE = inspect.getsource(anexo_do_resultado)
# Quem chama `anexo_do_resultado` é o executor do passo.
LACO = inspect.getsource(executar_passo)
METODO = inspect.getsource(SenturyOrchestrator._handle_message_inner)


# ------------------------------------ os caminhos que existem (eram quatro;
# o ascii saiu de proposito: o modelo escreve markdown)

@pytest.mark.parametrize("marcador,rotulo", [
    ('if tool == "executar_python":', "sandbox"),
    ("if tool in _export_binario():", "export binario"),
    ("entrega = _entregas_do_setor().get(tool)", "entrega do setor"),
])
def test_os_caminhos_continuam_existindo(marcador, rotulo):
    """Se um sumir numa refatoracao, o usuario para de receber aquele anexo: e
    nada mais no codigo denunciaria."""
    assert marcador in FONTE, rotulo


# ------------------------------------------- o contrato de saida, agora explicito

def test_as_saidas_viraram_retorno():
    """A contagem de saídas é o contrato: se mudar, quem mudou revisa de
    propósito. Dois `parar` (a entrega que o setor declara), dois `anexar`
    (arquivo de script e de exportação, que o modelo confere antes de
    responder) e um `seguir`."""
    assert FONTE.count('return "parar"') == 2
    assert FONTE.count('return "anexar"') == 2
    assert FONTE.count('return "seguir"') == 1
    assert FONTE.count('return "nada"') == 1


def test_nenhum_break_sobrou_solto():
    """`break` dentro da funcao extraida nao quebra o laco do chamador: ele
    quebraria um laco interno, mudando a semantica em silencio."""
    corpo = FONTE.split('"""', 2)[-1]
    soltos = [
        x.strip() for x in corpo.splitlines()
        if x.strip() in ("break", "continue")
    ]
    assert soltos == [], soltos


def test_o_chamador_traduz_os_tres_rumos():
    """Confundir "parar" com "seguir" faz o turno continuar quando deveria encerrar."""
    assert '_rumo == "seguir"' in LACO
    assert '_rumo == "parar"' in LACO
    depois_seguir = LACO.split('_rumo == "seguir"', 1)[1][:80]
    assert "return SEGUIR" in depois_seguir
    depois_parar = LACO.split('_rumo == "parar"', 1)[1][:200]
    assert "return PARAR" in depois_parar


def test_o_que_atravessa_a_fronteira():
    """A lista de anexos e do TURNO, nao deste passo: e mutada de proposito."""
    assert "anexos_do_turno.append(attachment)" in FONTE
    assert "export_response" in FONTE
    # o chamador recebe os dois de volta
    assert "attachment = _anexo" in LACO
    assert "export_response = _resposta" in LACO


def test_a_entrega_continua_vindo_do_pacote():
    """Ganho do bloco 4: nem o laco nem a funcao conhecem `gerar_plano_acao`
    pelo nome. Se alguem cravar de novo, aparece aqui."""
    assert "_entregas_do_setor()" in FONTE
    for cravado in ("gerar_plano_acao", "plano-de-acao.md", "Plano de Ação"):
        assert cravado not in FONTE, cravado


# ------------------------------------------------------- o que a extracao rendeu

def test_o_metodo_do_turno_continua_enxuto():
    """O teto exato mora em test_monolito; aqui fica o limite grosso."""
    assert len(METODO.splitlines()) < 1000


def test_o_laco_nao_formata_mais_saida():
    """O que ficou no laço e no passo é decisão de turno; formatação de anexo
    mora em `anexo_do_resultado`."""
    for formatacao in ("base64.b64encode", 'filename="', "mime_type"):
        assert formatacao not in LACO, formatacao
        assert formatacao not in METODO, formatacao


@pytest.mark.asyncio
async def test_markdown_do_sandbox_e_anexado_sem_depender_do_orquestrador(tmp_path):
    """Regressao do E2E: a funcao extraida ainda referenciava ``self``.

    O arquivo era criado corretamente, mas o turno caia com NameError antes de
    anexar. Markdown nao precisa do reparador visual de HTML.
    """
    arquivo = tmp_path / "inventario.md"
    arquivo.write_text("# Inventario\n\n9 tabelas", encoding="utf-8")

    resultado = {"arquivos_gerados": [str(arquivo)]}
    anexos = []
    rumo, anexo, nota = await anexo_do_resultado(
        "executar_python", {}, resultado, SimpleNamespace(), anexos,
    )

    assert rumo == "anexar"
    assert anexo["filename"] == "inventario.md"
    assert anexos == [anexo]
    # O modelo le a nota junto do resultado, e confere antes de responder.
    assert "ARQUIVO GERADO" in nota and resultado["conferir_o_arquivo"] == nota


@pytest.mark.asyncio
async def test_gerado_de_novo_substitui_o_anterior(tmp_path):
    """O modelo conferiu, achou errado e gerou de novo: vai so o novo."""
    primeiro, segundo = tmp_path / "v1.md", tmp_path / "v2.md"
    primeiro.write_text("# errado", encoding="utf-8")
    segundo.write_text("# certo", encoding="utf-8")
    anexos = [{"type": "pdf", "filename": "de-outra-ferramenta.pdf"}]
    for arquivo in (primeiro, segundo):
        await anexo_do_resultado(
            "executar_python", {}, {"arquivos_gerados": [str(arquivo)]}, SimpleNamespace(), anexos,
        )
    assert [a["filename"] for a in anexos] == ["de-outra-ferramenta.pdf", "v2.md"]


@pytest.mark.asyncio
async def test_entrega_direta_de_arquivo_preserva_telemetria_do_loop():
    from sentury.exec.python_exec import _SANDBOX_ROOT
    from sentury.harness.state import AnalysisState
    from tests.test_orchestrator import (
        EchoResponder, ScriptedPlanner, _store, _tool_call,
    )

    nome = "regressao-telemetria-anexo.md"
    orquestrador = SenturyOrchestrator(
        planner=ScriptedPlanner([_tool_call(
            "executar_python",
            codigo=f"open({nome!r}, 'w', encoding='utf-8').write('# pronto')",
        )]),
        responder=EchoResponder(), store=_store(),
    )
    try:
        resposta = await orquestrador.handle_message(
            AnalysisState.new("s-anexo-telemetria", "u"), "gere um arquivo md",
        )
        stats = resposta["harness"]["loop_stats"]
        assert stats["tool_calls"] >= 1
        assert stats["exit_reason"] == "completed"
        assert resposta["attachment"]["filename"] == nome
    finally:
        (_SANDBOX_ROOT / nome).unlink(missing_ok=True)
