"""Schemas reais e recuperacao por rota nomeada."""
import asyncio

from sentury.exec import python_exec
from sentury.exec.contrato import CodigoDeErro
from sentury.harness.loop_budget import BudgetTracker
from sentury.harness.repeticao import lembrete
from sentury.harness.rotas import dica_de_rota, e_alternativa, rota_para
from sentury.llm import tool_schemas
from sentury.llm.tool_schemas import build_tool_schemas
from sentury.tools.registry import TOOL_REGISTRY, sempre_exposta


def _schemas():
    return {
        item["function"]["name"]: item["function"]["parameters"]
        for item in build_tool_schemas()
    }


def test_todo_registro_declara_parametros():
    assert all("parametros" in meta for meta in TOOL_REGISTRY.values())


def test_catalogo_total_nao_vira_mesa_do_generalista(monkeypatch):
    monkeypatch.setattr(tool_schemas, "_setor_ativo", lambda: "")
    enviados = set(_schemas())
    esperados = {
        nome for nome, meta in TOOL_REGISTRY.items()
        if sempre_exposta(meta) and not meta.get("setor")
    }
    assert enviados == esperados
    assert not any(TOOL_REGISTRY[nome].get("setor") for nome in enviados)


def test_mesa_de_cx_recebe_motor_e_ferramentas_de_cx(monkeypatch):
    monkeypatch.setattr(tool_schemas, "_setor_ativo", lambda: "setor_teste")
    enviados = set(_schemas())
    esperados = {
        nome for nome, meta in TOOL_REGISTRY.items()
        if sempre_exposta(meta)
        and (not meta.get("setor") or meta.get("setor") == "setor_teste")
    }
    assert enviados == esperados


def test_modelo_enxerga_os_nomes_dos_argumentos_criticos():
    schemas = _schemas()
    assert schemas["executar_python"]["required"] == ["codigo"]
    assert "codigo" in schemas["executar_python"]["properties"]
    assert {"conteudo", "linguagem", "argumentos"} <= set(
        schemas["executar_script"]["properties"]
    )
    assert "comando" in schemas["executar_comando"]["properties"]


def test_aliases_continuam_permitidos_na_transicao():
    assert _schemas()["executar_python"]["additionalProperties"] is True


def test_import_negado_aponta_executar_script():
    resultado = {"erro": "import negado", "codigo_erro": CodigoDeErro.IMPORT_NEGADO}
    rota = rota_para("executar_python", resultado)
    assert rota.alternativa == "executar_script"
    assert "linguagem `python`" in rota.instrucao
    assert e_alternativa("executar_python", resultado, "executar_script")


def test_metacaractere_aponta_script_e_permissao_nao_e_falha():
    recusado = {"motivo": "'|' usa metacaractere de shell", "recusado": True}
    assert rota_para("executar_comando", recusado).alternativa == "executar_script"
    pendente = {
        "precisa_permissao": True,
        "codigo_erro": CodigoDeErro.PRECISA_PERMISSAO,
    }
    assert rota_para("executar_comando", pendente) is None


def test_recusa_de_politica_nao_ensina_contorno():
    resultado = {
        "recusado": True,
        "codigo_erro": CodigoDeErro.RECUSADO_POLITICA,
        "motivo": "hardline",
    }
    assert rota_para("executar_script", resultado) is None


def test_lembrete_de_falha_nomeia_a_alternativa():
    resultado = {"erro": "import negado", "codigo_erro": CodigoDeErro.IMPORT_NEGADO}
    texto = lembrete("executar_python", resultado, 1)
    assert "ROTA DE RECUPERACAO" in texto
    assert "executar_script" in texto
    assert "apenas em texto" in dica_de_rota("executar_python", resultado)


def test_rota_so_reseta_na_primeira_tentativa():
    tracker = BudgetTracker()
    tracker.consecutive_no_progress = 2
    primeira = tracker.registrar_rota(
        "executar_python", {"codigo": "import x"},
        "executar_script", {"conteudo": "import x", "linguagem": "python"},
    )
    assert primeira is True
    tracker.rota_bem_sucedida(primeira)
    assert tracker.consecutive_no_progress == 0
    assert tracker.registrar_rota(
        "executar_python", {"codigo": "import x"},
        "executar_script", {"conteudo": "import x", "linguagem": "python"},
    ) is False


def test_sandbox_classifica_import_para_a_rota(monkeypatch):
    from sentury.exec import provider_python

    monkeypatch.setattr(provider_python, "habilitado", lambda: False)
    r = asyncio.run(python_exec.executar_python(None, "import socket\nresultado = 1"))
    assert r["codigo_erro"] == CodigoDeErro.IMPORT_NEGADO
    assert rota_para("executar_python", r).alternativa == "executar_script"


def test_anunciar_a_rota_sem_chamar_recebe_o_fato_uma_vez():
    """O modelo respondeu "vou usar executar_script" e parou: a rota de uma falha
    que acabou de acontecer ficou sem tentativa. O laço diz isso uma vez."""
    from sentury.harness.rotas import RastreadorDeRota

    rastreador = RastreadorDeRota()
    rastreador.falhou("executar_python", {}, {"erro": "import negado", "codigo_erro": CodigoDeErro.IMPORT_NEGADO})
    aviso = rastreador.aviso_se_parou()
    assert "executar_script" in aviso and "ainda não foi chamado" in aviso
    assert rastreador.aviso_se_parou() == ""


def test_sem_aviso_quando_algo_deu_certo_depois_ou_sem_rota():
    """Depois de uma ferramenta que deu certo, responder pode ser a conclusão; e
    recusa da política não tem rota a lembrar."""
    from sentury.harness.rotas import RastreadorDeRota

    rastreador = RastreadorDeRota()
    rastreador.falhou("executar_python", {}, {"erro": "import negado", "codigo_erro": CodigoDeErro.IMPORT_NEGADO})

    class Orcamento:
        def rota_bem_sucedida(self, tentativa):
            pass

    rastreador.concluiu(Orcamento(), None, {})
    assert rastreador.aviso_se_parou() == ""

    sem_rota = RastreadorDeRota()
    sem_rota.falhou("executar_comando", {}, {"motivo": "recusado pela política", "recusado": True})
    assert sem_rota.aviso_se_parou() == ""


def test_a_rota_deixa_a_alternativa_na_mesa_do_turno():
    """O `executar_script` não é do núcleo. Se a rota manda usá-lo e ele não
    está entre as ferramentas da chamada, o modelo só consegue anunciar."""
    from sentury.harness import descoberta
    from sentury.harness.rotas import RastreadorDeRota

    token = descoberta.abrir()
    try:
        RastreadorDeRota().falhou("executar_python", {},
                                  {"erro": "import negado", "codigo_erro": CodigoDeErro.IMPORT_NEGADO})
        assert "executar_script" in descoberta._TURNO.get().carregadas
    finally:
        descoberta.fechar(token)
