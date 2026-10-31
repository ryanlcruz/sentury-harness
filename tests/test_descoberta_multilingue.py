"""O idioma não esconde uma capacidade nem concede permissão para usá-la.

O provedor dublê escolhe nomes e confere a mesa de cada chamada: estes testes
medem o contrato do harness, não a compreensão de idiomas de uma LLM real.
"""
import asyncio
import json

import pytest

from sentury.config import settings
from sentury.domains.escopo import usar_setor
from sentury.harness import descoberta
from sentury.harness.orchestrator import SenturyOrchestrator
from sentury.harness.roteamento_de_skill import escolher
from sentury.harness.state import AnalysisState
from sentury.tools.capability_catalog import CapabilityEntry, build_catalog, render_manifest, search_catalog
from sentury.tools.catalog import execute_tool
from sentury.tools.registry import TOOL_REGISTRY
from tests.test_orchestrator import EchoResponder, _store


PEDIDOS = [
    "Leia resumo.txt e resuma o projeto.",
    "Read resumo.txt and summarize the project.",
    "请读取 resumo.txt 并总结项目。",
    "请用 Python 读取 resumo.txt 并总结项目。",
    "Lee resumo.txt y resume el proyecto.",
    "Прочитай resumo.txt и кратко опиши проект.",
    "اقرأ resumo.txt ولخص المشروع.",
    "resumo.txt を読んでプロジェクトを要約してください。",
    "le o resumo.txt ai e conta oq esse trem faz",
    "看看 resumo.txt e me diz what's inside.",
]


@pytest.fixture(autouse=True)
def generalista():
    with usar_setor("generalista"):
        yield


class _Nativo:
    supports_tools = True
    last_model = "fixture-multilingue"
    last_usage = None
    last_tool_calls = None

    def __init__(self, roteiro):
        self.roteiro = iter(roteiro)
        self.chamadas = []

    async def complete(self, messages, tools=None, **kwargs):
        self.chamadas.append({"messages": messages, "tools": tools})
        item = next(self.roteiro)
        self.last_tool_calls = None
        if isinstance(item, tuple):
            nome, argumentos = item
            # Um dublê que aceita qualquer nome esconderia o defeito original:
            # achava a ferramenta, mas ela continuava sem schema no provedor.
            assert nome in {schema["function"]["name"] for schema in tools}
            self.last_tool_calls = [{"id": f"c{len(self.chamadas)}", "type": "function",
                                     "function": {"name": nome, "arguments": json.dumps(argumentos)}}]
            return ""
        return item


def _orq(planner):
    return SenturyOrchestrator(planner=planner, responder=EchoResponder(), store=_store())


@pytest.mark.parametrize("pedido", PEDIDOS)
async def test_nome_do_mapa_carrega_schema_e_le_arquivo_no_turno(monkeypatch, tmp_path, pedido):
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_PROGRESSIVE_CAPABILITIES", True)
    # O mecanismo sob demanda é o que se mede aqui; o teto em zero o liga.
    monkeypatch.setattr(settings, "SENTURY_FERRAMENTAS_TETO_TOKENS", 0)
    monkeypatch.setattr(settings, "SENTURY_AGENT_LOOP", True)
    monkeypatch.setattr(settings, "SENTURY_GRAVAR_TRACOS", False)
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    (tmp_path / "resumo.txt").write_text("Este projeto organiza uma biblioteca pessoal.", encoding="utf-8")
    planner = _Nativo([
        ("search_tools", {"nomes": ["diagnosticos"]}),
        ("ler_arquivo", {"caminho": "resumo.txt"}),
        "O projeto organiza uma biblioteca pessoal.",
        "Estou pronto para outro pedido.",
    ])
    orq = _orq(planner)
    state = AnalysisState.new("idioma", "dono")
    resultado = await orq.handle_message(state, pedido)
    assert resultado["harness"]["ferramentas"] == ["search_tools", "ler_arquivo"]
    assert resultado["message"] == "O projeto organiza uma biblioteca pessoal."
    primeiro = "\n".join(str(m.get("content") or "") for m in planner.chamadas[0]["messages"])
    assert "`diagnosticos`" in primeiro and "Mapa das ferramentas" in primeiro
    # Ler arquivo é do núcleo: está na mesa em qualquer idioma, sem busca.
    assert "ler_arquivo" in {s["function"]["name"] for s in planner.chamadas[0]["tools"]}
    assert "diagnosticos" in {s["function"]["name"] for s in planner.chamadas[1]["tools"]}
    assert any("biblioteca pessoal" in str(m.get("content")) for m in planner.chamadas[2]["messages"])
    await orq.handle_message(state, "你好，今天怎么样？")
    ultimas = {s["function"]["name"] for s in planner.chamadas[3]["tools"]}
    assert "diagnosticos" not in ultimas, "um turno novo não herda schemas carregados por outro"


async def test_busca_chinesa_sem_match_oferece_rota_por_nome():
    state = AnalysisState.new("busca", "dono")
    resultado = await execute_tool(None, state, "search_tools", {"consulta": "请读取文件"})
    assert not resultado["achadas"]
    assert "`ler_arquivo`" in resultado["catalogo"]
    carregada = await execute_tool(None, state, "search_tools", {"nomes": ["ler_arquivo"]})
    assert [schema["function"]["name"] for schema in carregada["schemas"]] == ["ler_arquivo"]


def test_busca_preserva_escritas_e_encontra_nome_unicode():
    entradas = [CapabilityEntry("读取文件", "tool", "读取文件"),
                CapabilityEntry("читать", "tool", "Прочитать файл")]
    assert search_catalog(entradas, "读取文件")[0][0].name == "读取文件"
    assert search_catalog(entradas, "Прочитать файл")[0][0].name == "читать"


def test_catalogo_e_carregamento_respeitam_badge_e_setor():
    state = AnalysisState.new("permissoes", "dono")
    recusadas = descoberta.consultar(state, {"nomes": ["computador", "analyze_nps", "nao_existe"]})
    assert recusadas["schemas"] == [] and len(recusadas["nao_encontradas"]) == 3
    token = descoberta.abrir()
    try:
        state.funcoes_ativas = ["computador"]
        assert descoberta.consultar(state, {"nomes": ["computador"]})["schemas"]
        state.funcoes_ativas = []
        _, nomes, mapa, _ = descoberta.preparar(state, "请继续", [])
        assert "computador" not in nomes and "`computador`" not in mapa
    finally:
        descoberta.fechar(token)


def test_catalogo_respeita_escopo_do_residente():
    from sentury.residentes.escopo import vestido
    from sentury.residentes.manifesto import validar

    agente = validar({"nome": "atlas", "papel": "leitor", "objetivo": "ler arquivos",
                      "ferramentas": ["ler_arquivo"]})
    with vestido(agente):
        state = AnalysisState.new("residente", "dono")
        assert "editar_arquivo" not in {entry.name for entry in build_catalog(TOOL_REGISTRY)}
        assert descoberta.consultar(state, {"nomes": ["editar_arquivo"]})["schemas"] == []
        assert descoberta.consultar(state, {"nomes": ["ler_arquivo"]})["schemas"]


def test_listagem_paginada_nao_perde_ferramentas():
    state = AnalysisState.new("catalogo", "dono")
    offset, nomes = 0, []
    while offset is not None:
        pagina = descoberta.consultar(state, {"offset": offset})
        nomes.extend(entry["name"] for entry in pagina["achadas"])
        offset = pagina["proximo_offset"]
    assert len(nomes) == len(set(nomes))
    assert set(nomes) == {entry.name for entry in build_catalog(TOOL_REGISTRY)}
    categoria = descoberta.consultar(state, {"categoria": "browser"})
    assert all(entry["category"] == "browser" for entry in categoria["achadas"])


def test_mapa_grande_mantem_categorias_descobriveis():
    entradas = [CapabilityEntry(f"ferramenta_{i}", "tool", "descrição " * 25, category="plugin")
                for i in range(300)]
    mapa = render_manifest(entradas, max_chars=1200)
    assert "plugin: 300 ferramentas" in mapa and "search_tools(categoria" in mapa


async def test_conversas_simultaneas_nao_compartilham_descobertas():
    sincronizar = asyncio.Event()

    async def turno(carregar):
        token = descoberta.abrir()
        try:
            state = AnalysisState.new(str(carregar), "dono")
            if carregar:
                descoberta.consultar(state, {"nomes": ["ler_arquivo"]})
                sincronizar.set()
            await sincronizar.wait()
            _, nomes, _, _ = descoberta.preparar(state, "请继续", [])
            return "ler_arquivo" in nomes
        finally:
            descoberta.fechar(token)

    assert await asyncio.gather(turno(True), turno(False)) == [True, False]


@pytest.mark.parametrize("pedido", ["acompanha até fechar", "请继续跟进直到完成", "não monte um workflow"])
def test_skill_natural_nao_executa_por_regex(pedido):
    entrada = type("Skill", (), {"name": "montar-workflow", "gatilhos": [".*"]})()
    assert escolher(pedido, {"montar-workflow"}, lambda: [entrada]) == (None, None)
    assert escolher("[montar-workflow] " + pedido, {"montar-workflow"}, lambda: [entrada]) \
        == ("montar-workflow", "explicit")


async def test_badge_ligado_nao_forca_uso_em_conversa(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_PROGRESSIVE_CAPABILITIES", True)
    # O mecanismo sob demanda é o que se mede aqui; o teto em zero o liga.
    monkeypatch.setattr(settings, "SENTURY_FERRAMENTAS_TETO_TOKENS", 0)
    state = AnalysisState.new("sem-ferramenta", "dono")
    state.funcoes_ativas = ["computador"]
    resultado = await _orq(_Nativo(["Pode me contar."])).handle_message(state, "我想和你聊聊。")
    assert resultado["harness"]["ferramentas"] == []
    assert resultado["message"] == "Pode me contar."


async def test_falha_do_indice_preserva_catalogo_completo(monkeypatch):
    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", True)
    monkeypatch.setattr(settings, "SENTURY_PROGRESSIVE_CAPABILITIES", True)
    # O mecanismo sob demanda é o que se mede aqui; o teto em zero o liga.
    monkeypatch.setattr(settings, "SENTURY_FERRAMENTAS_TETO_TOKENS", 0)

    def falhar(*args):
        raise RuntimeError("índice indisponível")

    monkeypatch.setattr(descoberta, "preparar", falhar)
    planner = _Nativo(["Pode me contar."])
    await _orq(planner).handle_message(AnalysisState.new("sem-indice", "dono"), "请帮我一下。")
    assert "ler_arquivo" in {schema["function"]["name"] for schema in planner.chamadas[0]["tools"]}


def test_eval_local_mede_acesso_sem_fingir_compreensao_de_modelo():
    from sentury.evals.descoberta_multilingue import medir_acesso

    resultados = medir_acesso()
    assert all(r["acesso"] for r in resultados if r["acesso"] is not None)
    assert any(r["recall_lexical"] is False and r["acesso"] is True for r in resultados)


async def test_bancada_live_mede_leitura_real_e_preserva_chamada_nativa():
    import re
    from sentury.evals.descoberta_multilingue import Caso, medir_live

    class Leitor(_Nativo):
        async def complete(self, messages, tools=None, **kwargs):
            if len(self.chamadas) == 2:
                codigos = re.findall(r"LEITURA-[0-9a-f]{10}", str(messages))
                assert codigos, "o código aleatório deve vir da leitura, não do prompt"
                self.roteiro = iter([codigos[-1]])
            return await super().complete(messages, tools=tools, **kwargs)

    provider = Leitor([("search_tools", {"nomes": ["ler_arquivo"]}),
                       ("ler_arquivo", {"caminho": "resumo.txt"})])
    resultado, = await medir_live(provider, [Caso("zh", "请读取 resumo.txt 并告诉我代码。")])
    assert resultado["concluiu"] and resultado["native_tools"]
    assert resultado["ferramentas"] == ["search_tools", "ler_arquivo"]


def test_indice_de_skills_revalida_raizes_mesmo_com_mtime_igual(tmp_path, monkeypatch):
    import os
    from sentury.skills.skill_loader import SkillLoader

    motor, pacote = tmp_path / "motor", tmp_path / "pacote"
    for pasta, nome in [(motor, "generica"), (pacote, "do-pacote")]:
        skill = pasta / nome
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {nome}\ndescription: Exemplo\n---\nProcedimento.", encoding="utf-8")
    os.utime(motor, (2000000000, 2000000000))
    os.utime(pacote, (1000000000, 1000000000))
    loader = SkillLoader(motor)
    raizes = [motor]
    monkeypatch.setattr(loader, "_get_skill_roots", lambda: raizes)
    assert {s.name for s in loader.scan_skills()} == {"generica"}
    raizes = [motor, pacote]
    assert {s.name for s in loader.scan_skills()} == {"generica", "do-pacote"}
    raizes = [motor]
    assert {s.name for s in loader.scan_skills()} == {"generica"}
    assert loader.load_skill("do-pacote") is None
    raizes = []
    assert not loader.scan_skills() and loader.load_skill("generica") is None
