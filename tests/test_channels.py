import pathlib
from fastapi.testclient import TestClient

from sentury.external.channels import CANAIS, catalogo, declaracao


def _client():
    from sentury.main import app
    return TestClient(app)


def test_catalogo_junta_estado_de_runtime():
    saida = catalogo({"telegram": {"status": "online", "active": True}})
    telegram = next(c for c in saida if c["id"] == "telegram")
    assert telegram["status"] == "online"
    assert telegram["active"] is True
    assert telegram["label"] == "Telegram"


def test_canal_secreto_nunca_declara_valor():
    for canal in CANAIS:
        for campo in canal["fields"]:
            assert "value" not in campo


def test_rota_lista_canais_com_campos():
    resposta = _client().get("/sentury/channels")
    assert resposta.status_code == 200
    canais = {c["id"]: c for c in resposta.json()["canais"]}
    assert {"web", "telegram", "voz"} <= set(canais)
    assert [c["name"] for c in canais["telegram"]["fields"]] == ["token", "allowed_ids"]
    assert "token" not in canais["telegram"].get("values", {})


def test_canal_desconhecido_e_404():
    assert _client().post("/sentury/channels/fax/config", json={}).status_code == 404


def test_canal_sem_configuracao_recusa():
    assert declaracao("web")["configurable"] is False
    assert _client().post("/sentury/channels/web/config", json={}).status_code == 400


def test_comando_de_execucao_vai_para_a_interface():
    from sentury.harness.orchestrator import SenturyOrchestrator as O

    assert O._tool_command("executar_python", {"codigo": "print(1)"}) == "print(1)"
    assert O._tool_command("consultar_sql", {"sql": "SELECT 1"}) == "SELECT 1"
    # Antes isto era `None`: só quem rodava um comando literal aparecia, e a
    # linha das outras dizia que algo rodou sem dizer em cima de quê. Nem toda
    # ferramenta roda um comando, mas toda ferramenta age sobre algo: e o
    # cartão de execução, fechado, é uma linha só.
    assert O._tool_command("consultar_medida", {"grupo": "Alfa"}) == "grupo: Alfa"


def test_papeis_do_catalogo_sao_abertos():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path("sentury/plugins/robinbandit/src")))
    from robinbandit.model_catalog import _papeis

    assert _papeis("openai/whisper-1", ["audio"], [], set()) == ["texto", "transcricao"]
    assert "imagem" in _papeis("g/flash-image", ["text"], ["text", "image"], set())
    assert _papeis("openai/text-embedding-3", ["text"], [], set()) == ["embedding"]
    assert _papeis("meta/llama", ["text"], ["text"], set()) == ["texto"]


def test_codex_encontrado_fora_do_path(monkeypatch, tmp_path):
    import sys, pathlib, shutil as sh
    sys.path.insert(0, str(pathlib.Path("sentury/plugins/robinbandit/src")))
    from robinbandit import codex_provider

    binario = tmp_path / ".codex" / "bin" / "codex.exe"
    binario.parent.mkdir(parents=True)
    binario.write_text("", encoding="utf-8")
    monkeypatch.setattr(sh, "which", lambda _n: None)
    monkeypatch.setattr(codex_provider.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path)))

    assert codex_provider.resolve_codex_binary("codex") == str(binario)


def test_mcp_registro_guarda_so_o_nome_da_variavel(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from sentury.external import mcp_registry

    servidor = mcp_registry.salvar({
        "nome": "Teste",
        "transporte": "stdio",
        "comando": "echo",
        "args": ["oi"],
        "env_vars": ["MINHA_CHAVE"],
    })
    assert servidor["env_vars"] == ["MINHA_CHAVE"]
    bruto = (tmp_path / "mcp.json").read_text(encoding="utf-8")
    assert "MINHA_CHAVE" in bruto

    assert mcp_registry.obter(servidor["id"])["nome"] == "Teste"
    assert mcp_registry.remover(servidor["id"]) is True
    assert mcp_registry.obter(servidor["id"]) is None


def test_mcp_recusa_transporte_sem_destino(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from sentury.external import mcp_registry

    with pytest.raises(ValueError):
        mcp_registry.salvar({"nome": "x", "transporte": "http"})
    with pytest.raises(ValueError):
        mcp_registry.salvar({"nome": "x", "transporte": "stdio"})


def test_mcp_inspecionar_devolve_erro_em_vez_de_levantar(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from sentury.external import mcp_registry

    resultado = asyncio.run(mcp_registry.inspecionar(
        {"transporte": "stdio", "comando": "binario-que-nao-existe-mesmo", "args": []},
        timeout=3,
    ))
    assert resultado["conectado"] is False
    assert resultado["erro"]


def test_custo_so_existe_com_preco_publicado():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path("sentury/plugins/robinbandit/src")))
    from robinbandit.chain import custo_estimado

    uso = {"entrada": 1_000_000, "saida": 500_000, "total": 1_500_000}
    precos = {"m": {"prompt_per_million": 0.5, "completion_per_million": 2.0}}

    assert custo_estimado("groq:m", uso, precos) == 1.5
    # Sem preco conhecido, nao se inventa numero.
    assert custo_estimado("groq:desconhecido", uso, precos) is None
    assert custo_estimado("groq:m", None, precos) is None


def test_contagem_soma_todas_as_chamadas_do_turno():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path("sentury/plugins/robinbandit/src")))
    from robinbandit import chain

    chain.iniciar_contagem()
    chain._somar({"entrada": 10, "saida": 5, "total": 15})
    chain._somar({"entrada": 3, "saida": 2, "total": 5})
    assert chain.contagem_do_turno() == {"entrada": 13, "saida": 7, "total": 20, "chamadas": 2}


async def test_compactacao_avisa_antes_e_depois(monkeypatch):
    from sentury.harness.context_budget import ContextBudgetManager
    from sentury.harness.state import AnalysisState

    class _Contextualizer:
        async def summarize_and_extract(self, messages, current_state=None):
            from sentury.harness.state import ConversationState
            return "resumo do que veio antes", (current_state or ConversationState())

    eventos = []
    gerente = ContextBudgetManager(_Contextualizer(), limit_messages=2, limit_chars=100000)
    state = AnalysisState.new("compact", "u1")
    state.history = [
        {"role": "user", "content": f"pergunta {i}"} if i % 2 == 0
        else {"role": "assistant", "content": f"resposta {i}"}
        for i in range(40)
    ]

    await gerente.manage(state, progress_cb=eventos.append)

    tipos = [e.get("type") for e in eventos]
    assert "stage" in tipos, tipos
    assert "compacted" in tipos, tipos
    resumo = next(e for e in eventos if e.get("type") == "compacted")
    assert resumo["mensagens_antes"] > resumo["mensagens_depois"]


async def test_memoria_camada2_grava_journal_por_sessao(tmp_path):
    from sentury.memory.local_session_store import LocalSessionStore

    store = LocalSessionStore(tmp_path)
    await store.set("sessao-x", {"history": [{"role": "user", "content": "oi"}]}, 60)
    await store.set("sessao-y", {"history": [{"role": "user", "content": "ola"}]}, 60)

    assert len(store.eventos_da_sessao("sessao-x")) == 1
    dias = store.sessoes_por_dia()
    assert dias and dias[0]["total"] == 2

    # O journal global continua sendo a fonte: a camada 2 e um recorte dele.
    assert store.journal_path.exists()
    assert len(list(store.sessions_dir.glob("*/*/*/*/events.jsonl"))) == 2


async def test_memoria_camada2_ignora_id_perigoso(tmp_path):
    from sentury.memory.local_session_store import LocalSessionStore

    store = LocalSessionStore(tmp_path)
    caminho = store.caminho_da_sessao("../../fora")
    assert store.sessions_dir in caminho.parents


async def test_subagente_abre_e_fecha_o_proprio_passo():
    from sentury.agents.subagents import ExplicitSubagentCoordinator

    class _Chain:
        async def complete(self, messages, temperature=0.2, context=None):
            return "Resumo curto do papel."

    eventos = []
    coord = ExplicitSubagentCoordinator(_Chain())

    class _Estado:
        history = [{"role": "user", "content": "analise"}]
        results = {"r1": {"tool": "consultar_medida", "data": {"medida": -31}}}
        last_result_id = "r1"

    saida = await coord.consultar("revise a medida", _Estado(), quantos=2, emit=eventos.append)

    assert saida["completed_count"] == 2
    inicios = [e for e in eventos if e["type"] == "tool_start"]
    fins = [e for e in eventos if e["type"] == "tool_complete"]
    assert len(inicios) == 2 and len(fins) == 2
    # A marca visual do papel viaja com o evento.
    assert {e["kind"] for e in inicios} == {"researcher", "reviewer"}
    assert all(e["duration_ms"] >= 1 for e in fins)


def test_shell_nasce_desligado():
    from sentury.tools.shell import executar

    resultado = executar("git status", habilitado=False)
    assert resultado["ok"] is False and resultado["recusado"] is True
    assert "SENTURY_SHELL" in resultado["motivo"]


def test_shell_lista_de_permissao_e_o_que_manda():
    import pytest
    from sentury.tools.shell import ComandoRecusado, validar

    assert validar("git status --short")[0].lower().startswith("git")
    assert validar("git commit -m x", permitir_escrita=True)

    for proibido in ("rm -rf .", "sudo ls", "curl http://x", "ssh host"):
        with pytest.raises(ComandoRecusado):
            validar(proibido, permitir_escrita=True)

    # Escrita so com aprovacao no passo.
    with pytest.raises(ComandoRecusado):
        validar("git commit -m x")
    with pytest.raises(ComandoRecusado):
        validar("mkdir novo")


def test_shell_recusa_metacaractere_porque_nao_ha_shell():
    import pytest
    from sentury.tools.shell import ComandoRecusado, validar

    for perigoso in ("cat x | grep senha", "ls > saida.txt", "ls && rm -rf .", "echo $HOME"):
        with pytest.raises(ComandoRecusado):
            validar(perigoso, permitir_escrita=True)


def test_shell_executa_leitura_real_com_duracao():
    from sentury.tools.shell import executar

    resultado = executar("git rev-parse --abbrev-ref HEAD", habilitado=True, diretorio=str(pathlib.Path(__file__).resolve().parent.parent))
    assert resultado["ok"] is True
    assert resultado["saida"].strip()
    assert resultado["duracao_ms"] >= 0


def test_o_fim_do_processo_espera_a_saida_ser_lida(monkeypatch):
    """O processo sair nao quer dizer que a saida ja foi lida. `esperar`
    devolvia codigo 0 com saida vazia quando o leitor ainda nao tinha lido,
    e o CI caia neste arquivo uma vez a cada tantas rodadas."""
    import sys
    import time

    from sentury.tools import processos

    drenar = processos._drenar

    def _leitor_lento(*args, **kwargs):
        time.sleep(0.5)
        return drenar(*args, **kwargs)

    monkeypatch.setattr(processos, "_drenar", _leitor_lento)
    pid = processos.iniciar(
        [sys.executable, "-c", "print('pronto')"], diretorio=".", comando="print",
    )
    resultado = processos.esperar(pid, timeout=10)
    assert resultado["codigo"] == 0
    assert resultado["saida"].strip() == "pronto"


def test_web_recusa_endereco_interno_no_servidor_e_esquema_perigoso_sempre(monkeypatch):
    """No servidor quem lê é o processo do Sentury, e 169.254.169.254 é o
    metadata da nuvem. Na instalação local o endereço interno é a máquina da
    pessoa e entra. Esquema que não é página fica fora nos dois."""
    import pytest
    from sentury.tools.web import UrlRecusada, validar_url

    internas = ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1/admin",
                "http://localhost:8000/health")
    monkeypatch.setenv("SENTURY_EM_SERVIDOR", "1")
    for perigosa in (*internas, "file:///etc/passwd", "gopher://interno/"):
        with pytest.raises(UrlRecusada):
            validar_url(perigosa)
    monkeypatch.delenv("SENTURY_EM_SERVIDOR")
    assert all(validar_url(url) == url for url in internas)
    for perigosa in ("file:///etc/passwd", "gopher://interno/"):
        with pytest.raises(UrlRecusada):
            validar_url(perigosa)
    with pytest.raises(UrlRecusada):
        validar_url("http://127.0.0.1/admin", rede_interna=False)


def test_web_extrai_texto_sem_script_nem_style():
    from sentury.tools.web import extrair_texto

    html = (
        "<html><head><title>Relatorio</title><style>.a{color:red}</style></head>"
        "<body><script>alert(1)</script><p>Medida caiu 4 pontos.</p></body></html>"
    )
    saida = extrair_texto(html)
    assert saida["titulo"] == "Relatorio"
    assert "Medida caiu 4 pontos." in saida["texto"]
    assert "alert(1)" not in saida["texto"]
    assert "color:red" not in saida["texto"]


def test_web_sem_chave_ainda_tem_provedor_de_busca():
    from sentury.tools.web import provedor_de_busca

    class _Settings:
        pass

    # Antes, sem chave nenhuma a busca nunca funcionava e o modelo respondia
    # de memoria. O DuckDuckGo em HTML nao exige credencial.
    provedor = provedor_de_busca(_Settings())
    assert provedor["nome"] == "duckduckgo"
    assert provedor["variavel"] == ""


def test_web_chave_configurada_tem_prioridade_sobre_o_sem_chave():
    from sentury.tools.web import provedor_de_busca

    class _Settings:
        TAVILY_API_KEY = "sk-xxx"

    assert provedor_de_busca(_Settings())["nome"] == "tavily"


def test_web_provedor_guarda_o_nome_da_variavel_nao_o_valor():
    from sentury.tools.web import provedor_de_busca

    class _Settings:
        TAVILY_API_KEY = "segredo-que-nao-pode-vazar"

    provedor = provedor_de_busca(_Settings())
    assert provedor["variavel"] == "TAVILY_API_KEY"
    assert "segredo" not in str(provedor)


async def test_ferramentas_novas_respondem_pelo_catalogo():
    from tests.fixtures.setor_teste.dados import StoreTeste
    from sentury.harness.state import AnalysisState
    from sentury.tools.catalog import execute_tool

    store = StoreTeste()
    state = AnalysisState.new("t", "u")

    # Shell nasce ligado (um agente sem comando nao trabalha); desligado, a
    # ferramenta DIZ isso em vez de inventar resposta.
    from sentury.config import settings

    ligado_antes = settings.SENTURY_SHELL
    try:
        settings.SENTURY_SHELL = False
        comando = await execute_tool(store, state, "executar_comando", {"comando": "git status"})
        assert comando["recusado"] is True and "SENTURY_SHELL" in comando["motivo"]
    finally:
        settings.SENTURY_SHELL = ligado_antes

    # Busca agora tem provedor mesmo sem chave; o contrato e sempre devolver
    # a lista, nunca inventar resultado.
    busca = await execute_tool(store, state, "buscar_web", {"consulta": ""})
    assert busca["ok"] is False and busca["resultados"] == []


def test_imagem_so_com_marcador_declarado():
    from sentury.harness.policy import sentury_harness
    from sentury.harness.state import AnalysisState
    from sentury.tools.imagem import limpar_marcador, pediu_imagem

    assert pediu_imagem("@image uma coruja dourada") is True
    assert pediu_imagem("olha @IMAGE isso") is True
    # Nao confundir com e-mail nem com pedido de grafico de dados.
    assert pediu_imagem("me manda para contato@image.com") is False
    assert pediu_imagem("faz um visual bonito do Medida") is False
    assert limpar_marcador("@image uma coruja") == "uma coruja"

    estado = AnalysisState.new("t", "u")
    assert sentury_harness.evaluate(estado, "gerar_imagem", "@image uma coruja", {}).allowed is True
    negado = sentury_harness.evaluate(estado, "gerar_imagem", "faz um visual do Medida", {})
    assert negado.allowed is False and "@image" in negado.reason


async def test_imagem_sem_credencial_diz_o_motivo():
    from sentury.tools.imagem import gerar_imagem

    class _Settings:
        GEMINI_API_KEY = ""

    saida = await gerar_imagem("@image uma coruja", _Settings())
    assert saida["ok"] is False
    assert "GEMINI_API_KEY" in saida["motivo"]


def test_persona_separa_identidade_do_setor_do_nucleo_do_agente():
    from pathlib import Path

    from sentury.llm.prompts import NUCLEO_DO_AGENTE, build_system_persona

    # A identidade e do SETOR, e mora no pacote dele. Era uma constante
    # `IDENTIDADE_CX` no motor: que ninguem usava, porque o fallback ja tinha
    # virado a identidade generalista. Identidade de setor no motor era o
    # mesmo vazamento das outras, so que numa variavel morta.
    from sentury.domains.carregador import ler

    persona_do_setor = ler(Path("tests/fixtures/setor_teste")).persona
    assert "Medida" in persona_do_setor
    # O nucleo e do Sentury: Harness, honestidade sobre dado, ferramentas.
    assert "Harness" in NUCLEO_DO_AGENTE

    outro = build_system_persona("Voce e o Sentury de Logistica. Fala de frota e rota.")
    assert "frota e rota" in outro
    # Trocar de setor troca a identidade, mas o nucleo continua inteiro.
    assert "Harness" in outro
    assert "unidades de negócio" not in outro.split("Harness")[0]


def test_diagnostico_separa_varias_chaves_gratis_de_varias_chaves_pagas():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path("sentury/plugins/robinbandit/src")))
    from robinbandit.account_health import diagnosticar

    class _Config:
        providers = {
            "gratis": {"api_key_env": "GRATIS_KEY", "cost_class": "free_preferred"},
            "misto": {"api_key_env": "MISTO_KEY", "cost_class": "mixed"},
        }

    class _Settings:
        GRATIS_KEY = "k1,k2"
        MISTO_KEY = "k1,k2"

    avisos = {a["provedor"]: a for a in diagnosticar(_Config(), _Settings(), [])}

    # Duas chaves gratis multiplicam cota: e o objetivo, nao um problema.
    assert avisos["gratis"]["gravidade"] == "ok"
    # Duas chaves num provedor misto viram sorteio entre paga e gratis.
    assert avisos["misto"]["gravidade"] == "atencao"
    assert "paga" in avisos["misto"]["detalhe"]
    assert "MISTO_KEY_PAGA" in avisos["misto"]["detalhe"]


def test_diagnostico_aponta_conta_declarada_sem_chave():
    """Conta sem chave e conta DESLIGADA, e desligada nao e problema.

    Antes toda conta declarada sem chave virava triangulo amarelo. Quem nao
    assina metade dos provedores abria a tela e via oito avisos que nao pedem
    acao nenhuma: e aviso que aparece sempre ninguem le, inclusive na vez que
    importava. A excecao e a conta marcada como PAGA: dizer que se paga por
    algo e nao por a chave e engano de configuracao, nao escolha.
    """
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path("sentury/plugins/robinbandit/src")))
    from robinbandit.account_health import diagnosticar

    class _Config:
        providers = {}

    def _avisar(conta):
        return diagnosticar(_Config(), object(), [conta])[0]

    gratis = _avisar({"id": "openrouter-free", "provider": "openrouter",
                      "key_env": "OR_FREE", "configurada": False})
    assert gratis["gravidade"] == "info"
    assert "OR_FREE" in gratis["detalhe"]
    assert "fora da cadeia" in gratis["detalhe"]

    paga = _avisar({"id": "openrouter-paga", "provider": "openrouter",
                    "key_env": "OR_PAGA", "configurada": False, "paga": True})
    assert paga["gravidade"] == "atencao"
    assert "OR_PAGA" in paga["detalhe"]


def test_rodizio_de_chaves_alterna_e_mantem_todas_para_failover():
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path("sentury/plugins/robinbandit/src")))
    from robinbandit.credentials import KeyRotator, is_quota_error

    rotator = KeyRotator(["k1", "k2"])
    assert rotator.order() == ["k1", "k2"]
    assert rotator.order() == ["k2", "k1"]

    # O sinal para pular de chave e cota/credito, nao erro qualquer.
    assert is_quota_error(Exception("429 Too Many Requests")) is True
    assert is_quota_error(Exception("402 insufficient credit")) is True
    assert is_quota_error(Exception("500 internal error")) is False


def test_funcao_ligada_vale_sem_a_palavra_no_texto():
    from sentury.harness.policy import sentury_harness
    from sentury.harness.state import AnalysisState

    estado = AnalysisState.new("t", "u")

    # Sem ligar e sem atalho no texto: nao gera imagem.
    assert sentury_harness.evaluate(estado, "gerar_imagem", "faz um visual do Medida", {}).allowed is False

    # Badge ligado: vale para qualquer pedido, sem precisar repetir @image.
    estado.funcoes_ativas = ["image"]
    decisao = sentury_harness.evaluate(estado, "gerar_imagem", "uma coruja dourada", {})
    assert decisao.allowed is True and "ligada" in decisao.reason

    # O atalho digitado continua funcionando para quem prefere teclar.
    estado.funcoes_ativas = []
    assert sentury_harness.evaluate(estado, "gerar_imagem", "@image uma coruja", {}).allowed is True


async def test_subagente_aceita_papel_que_o_usuario_inventa():
    from sentury.agents.subagents import ExplicitSubagentCoordinator

    class _Chain:
        async def complete(self, messages, temperature=0.2, context=None):
            # Devolve o angulo pedido para provar que ele chegou no prompt.
            return str(messages[0]["content"])[-80:]

    coord = ExplicitSubagentCoordinator(_Chain())

    class _Estado:
        history = [{"role": "user", "content": "x"}]
        results = {"r1": {"tool": "consultar_medida", "data": {"medida": -31}}}
        last_result_id = "r1"

    eventos = []
    saida = await coord.consultar(
        "avalie a proposta", _Estado(), papeis=["risco juridico", "impacto financeiro"], emit=eventos.append,
    )
    papeis = [item["role"] for item in saida["results"]]
    assert papeis == ["risco juridico", "impacto financeiro"]
    # Papel inventado leva a marca do próprio Sentury, sem palpite pelo nome.
    assert {e["kind"] for e in eventos if e["type"] == "tool_start"} == {"core"}


async def test_subagente_sem_papel_nomeado_usa_os_padrao():
    from sentury.agents.subagents import ExplicitSubagentCoordinator

    class _Chain:
        async def complete(self, messages, temperature=0.2, context=None):
            return "ok"

    class _Estado:
        results = {}

    saida = await ExplicitSubagentCoordinator(_Chain()).consultar("revise", _Estado(), quantos=2)
    assert [r["role"] for r in saida["results"]] == ["evidence_analyst", "operations_critic"]


async def test_papel_livre_leva_a_marca_do_sentury_em_qualquer_lingua():
    """Papel inventado não vira especialista por palpite sobre o nome: "risco
    jurídico" e "legal risk" saem iguais, com a marca do próprio Sentury."""
    from sentury.agents.subagents import ExplicitSubagentCoordinator

    class _Chain:
        async def complete(self, messages, temperature=0.2, context=None):
            return "ok"

    class _Estado:
        results = {}

    saida = await ExplicitSubagentCoordinator(_Chain()).consultar(
        "revise", _Estado(), papeis=["risco juridico", "legal risk", "pesquisa de mercado"])
    assert [r["capability"] for r in saida["results"]] == ["core", "core", "core"]


async def test_mcp_chega_ao_agente_pela_ferramenta(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from tests.fixtures.setor_teste.dados import StoreTeste
    from sentury.harness.state import AnalysisState
    from sentury.tools.catalog import execute_tool

    store = StoreTeste()
    state = AnalysisState.new("t", "u")

    # Servidor que nao existe: erro claro, nao excecao nem invencao.
    saida = await execute_tool(store, state, "usar_mcp", {"servidor": "nao-registrado", "ferramenta": "x"})
    assert saida["ok"] is False
    assert "nao esta registrado" in saida["erro"]


def test_shell_recusa_ler_segredo_mesmo_com_comando_permitido():
    import pytest
    from sentury.tools.shell import ComandoRecusado, validar

    # `cat` e leitura legitima; `cat .env` entrega as chaves para dentro do
    # historico da conversa, que fica gravado.
    for alvo in (
        "cat .env",
        "cat ../.env.local",
        "cat C:/Users/x/.codex/auth.json",
        "cat ~/.aws/credentials",
        "ls C:/Users/x/.ssh",
        "cat chave.pem",
    ):
        with pytest.raises(ComandoRecusado):
            validar(alvo, permitir_escrita=True)

    # Leitura comum continua passando.
    assert validar("cat README.md")
    assert validar("git log --oneline -5")
    assert validar("ls C:/Users/x/Downloads")


def test_shell_tira_aspas_do_argumento_no_windows():
    import os
    from sentury.tools.shell import validar

    partes = validar('ls "C:/Users/x/Downloads"')
    if os.name == "nt":
        # Sem isto o programa recebia o nome com as aspas dentro.
        assert partes[1] == "C:/Users/x/Downloads"


def test_permissao_pergunta_uma_vez_e_lembra(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from sentury.tools import permissoes as pm

    # Leitura nao passa por aqui; o que altera comeca perguntando.
    assert pm.avaliar("mkdir nova")["precisa_perguntar"] is True

    # "sessao" vale na conversa, nao em outra.
    pm.responder("mkdir nova", "sessao", "s1")
    assert pm.avaliar("mkdir C:/outra", "s1")["permitido"] is True
    assert pm.avaliar("mkdir C:/outra", "s2")["precisa_perguntar"] is True

    # "sempre" vale em qualquer conversa e sobrevive ao processo (fica no disco).
    pm.responder("cp a b", "sempre")
    assert pm.avaliar("cp x y", "s9")["permitido"] is True
    assert "cp" in (tmp_path / "permissoes.json").read_text(encoding="utf-8")

    # Um ban nem o modo permitir-tudo derruba (recusa pontual nao grava nada).
    pm.responder("pip install x", "negar_sempre")
    pm.definir_permitir_tudo(True)
    assert pm.avaliar("pip install requests")["permitido"] is False
    assert pm.avaliar("mv a b")["permitido"] is True


def test_permissao_cobre_o_verbo_nao_o_alvo(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from sentury.tools.permissoes import assinatura

    # Autorizar de novo por causa da mensagem do commit viraria ruido, e ruido
    # se aprova no automatico.
    assert assinatura('git commit -m "qualquer texto"') == "git commit"
    assert assinatura("git push") == "git push"
    # Caminho nao entra: criar pasta aqui ou ali e a mesma decisao.
    assert assinatura("mkdir C:/a") == assinatura("mkdir /outro/lugar") == "mkdir"


def test_shell_escrita_pede_permissao_e_leitura_nao(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    from sentury.tools import permissoes as pm
    from sentury.tools.shell import executar

    # Sessao propria: autorizacao de sessao vive no processo, e outro teste
    # rodando antes deixaria esta ja autorizada.
    sessao = "shell-escrita"
    pm.limpar_sessao(sessao)

    leitura = executar("git rev-parse --abbrev-ref HEAD", habilitado=True, session_id=sessao,
                      diretorio=str(pathlib.Path(__file__).resolve().parent.parent))
    assert leitura["ok"] is True

    escrita = executar("mkdir " + str(tmp_path / "nova"), habilitado=True, session_id=sessao)
    assert escrita.get("precisa_permissao") is True

    pm.responder("mkdir x", "sessao", sessao)
    assert executar("mkdir " + str(tmp_path / "nova"), habilitado=True, session_id=sessao)["ok"] is True


def test_ambiente_diz_o_sistema_em_vez_de_supor():
    from sentury.tools.shell import ambiente

    amb = ambiente()
    assert amb["sistema"]
    assert amb["listar"] in ("ls", "dir")
    assert amb["diretorio"]


def test_politica_de_shell_vem_do_yaml_e_nao_do_codigo(tmp_path, monkeypatch):
    from sentury.tools import shell

    politica = tmp_path / "politica.yaml"
    politica.write_text(
        "versao: 1\n"
        "leitura:\n  echo: null\n"
        "escrita: {}\n"
        "negados: [git]\n"
        "alvos_proibidos: []\n"
        "pastas_proibidas: []\n"
        "limites: {saida_chars: 100}\n"
        "com_subcomando: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SENTURY_SHELL_CONFIG", str(politica))
    shell.politica(recarregar=True)
    try:
        # A politica do arquivo manda: `echo` passa e `git`, permitido no
        # arquivo padrao: deixa de passar.
        assert shell.validar("echo oi")
        import pytest

        with pytest.raises(shell.ComandoRecusado):
            shell.validar("git status")
        assert shell.limite_de_saida() == 100
    finally:
        monkeypatch.delenv("SENTURY_SHELL_CONFIG", raising=False)
        shell.politica(recarregar=True)


def test_politica_ilegivel_nao_vira_politica_permissiva(tmp_path, monkeypatch):
    import pytest
    from sentury.tools import shell

    monkeypatch.setenv("SENTURY_SHELL_CONFIG", str(tmp_path / "nao-existe.yaml"))
    shell.politica(recarregar=True)
    try:
        # Sem arquivo legivel, nada roda: o contrario seria a falha perigosa.
        with pytest.raises(shell.ComandoRecusado):
            shell.validar("git status")
    finally:
        monkeypatch.delenv("SENTURY_SHELL_CONFIG", raising=False)
        shell.politica(recarregar=True)


def test_catalogo_de_artefato_vem_do_yaml(tmp_path, monkeypatch):
    from sentury import policies
    from sentury.harness import orchestrator

    (tmp_path / "artefatos.yaml").write_text(
        "versao: 1\n"
        "tipos:\n  webp: image/webp\n"
        "export_binario:\n  export_webp: webp\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SENTURY_POLICIES_DIR", str(tmp_path))
    policies.limpar_cache()
    try:
        # Formato novo entra pelo arquivo, sem tocar em codigo.
        #
        # As tres mudaram de casa: sao sobre FORMATO de saida (que extensao, que
        # mime, que confirmacao) e foram junto com o bloco que as usa, quando o
        # anexo saiu do laco do turno.
        from sentury.harness import anexo_do_resultado as saida

        assert saida._export_binario()["export_webp"] == ("webp", "image/webp")
        assert saida._padroes_do_sandbox() == ("*.webp",)
        assert saida._extensoes_de_artefato() == ("webp",)
    finally:
        monkeypatch.delenv("SENTURY_POLICIES_DIR", raising=False)
        policies.limpar_cache()


def test_config_ilegivel_nao_derruba_e_usa_o_padrao(tmp_path, monkeypatch):
    from sentury import policies

    quebrado = tmp_path / "artefatos.yaml"
    quebrado.write_text("isto: [nao fecha", encoding="utf-8")
    monkeypatch.setenv("SENTURY_POLICIES_DIR", str(tmp_path))
    policies.limpar_cache()
    try:
        # Config quebrada nao derruba o agente nem abre o que deveria fechar.
        assert policies.carregar("artefatos", {"tipos": {"png": "image/png"}})["tipos"] == {"png": "image/png"}
    finally:
        monkeypatch.delenv("SENTURY_POLICIES_DIR", raising=False)
        policies.limpar_cache()


def test_negar_nao_bane_o_comando():
    """Dizer 'nao' agora e diferente de banir: a pergunta volta na proxima."""
    from sentury.tools import permissoes

    sessao = "sess-negar-pontual"
    permissoes.limpar_sessao(sessao)
    permissoes.esquecer("rm")
    try:
        permissoes.responder("rm -rf build", "negar", sessao)
        assert "rm" not in permissoes.estado()["negados"]
        assert permissoes.avaliar("rm -rf build", sessao)["precisa_perguntar"]

        # Banir e uma resposta separada, e ai sim fica gravado.
        permissoes.responder("rm -rf build", "negar_sempre", sessao)
        decisao = permissoes.avaliar("rm -rf build", sessao)
        assert not decisao["permitido"] and not decisao["precisa_perguntar"]
    finally:
        permissoes.esquecer("rm")
        permissoes.limpar_sessao(sessao)


def test_comando_longo_desanexa_em_vez_de_morrer():
    """Timeout deixou de matar: vira 'volte depois'."""
    import sys
    from sentury.tools import processos

    try:
        pid = processos.iniciar(
            [sys.executable, "-c", "import time; time.sleep(4); print('terminei')"],
            diretorio=".", comando="tarefa longa",
        )
        parcial = processos.esperar(pid, timeout=0.5)
        assert parcial["rodando"], "deveria continuar vivo apos o teto"
        assert pid in {item["id"] for item in processos.listar(apenas_rodando=True)}

        final = processos.esperar(pid, timeout=20)
        assert not final["rodando"] and final["codigo"] == 0
        assert "terminei" in final["saida"]
    finally:
        processos.limpar_tudo()


class _AgendadorFalso:
    """Dublê com a mesma superfície do CronScheduler, sem asyncio nem Redis."""

    def __init__(self):
        self.jobs = []

    def add_job(self, session_id, user_id, prompt, interval_sec=None, cron_expr=None, **kw):
        if len(self.jobs) >= 2:
            raise ValueError("limite de agendamentos atingido")
        job = {"id": f"j{len(self.jobs)}", "session_id": session_id, "prompt": prompt,
               "cron_expr": cron_expr, "interval_sec": interval_sec, "run_count": 0}
        self.jobs.append(job)
        return job

    def add_once_job(self, session_id, user_id, prompt, delay_sec=None, run_at=None, **kw):
        job = self.add_job(session_id, user_id, prompt, **kw)
        job.update(kind="once", delay_sec=delay_sec, run_at=run_at)
        return job

    def list_jobs(self, session_id=None):
        return [j for j in self.jobs if session_id is None or j["session_id"] == session_id]

    def remove_job(self, job_id):
        antes = len(self.jobs)
        self.jobs = [j for j in self.jobs if j["id"] != job_id]
        return len(self.jobs) < antes


def test_agendar_aceita_cron_direto_do_modelo():
    """O modelo entende 'toda segunda de manha'; o regex de antes nao entendia.

    Este era o 'fake' do agendamento: o motor rodava, mas a porta so abria
    para duas frases exatas atras de `/cron`. Fora delas, nada era agendado.
    """
    from sentury.external import agendador

    agendador.registrar(_AgendadorFalso())
    try:
        r = agendador.agendar(session_id="s1", user_id="u1",
                              tarefa="me manda o Medida da semana", cron="0 9 * * 1")
        assert r["ok"] and r["cron_expr"] == "0 9 * * 1"

        r = agendador.agendar(session_id="s1", user_id="u1",
                              tarefa="checa o backlog", intervalo_seg=1800)
        assert r["ok"] and r["interval_sec"] == 1800

        assert len(agendador.listar("s1")["agendamentos"]) == 2
        assert agendador.cancelar("j0")["ok"]
        assert len(agendador.listar("s1")["agendamentos"]) == 1
    finally:
        agendador.limpar()


def test_agendar_recusa_pedido_incompleto_em_vez_de_adivinhar():
    from sentury.external import agendador

    agendador.registrar(_AgendadorFalso())
    try:
        # Sem QUANDO: nao inventa um horario.
        r = agendador.agendar(session_id="s1", user_id="u1", tarefa="me manda o Medida")
        assert not r["ok"] and "cron" in r["erro"]
        # Sem O QUE: nao agenda uma tarefa vazia.
        r = agendador.agendar(session_id="s1", user_id="u1", tarefa="", cron="0 9 * * 1")
        assert not r["ok"]
        # Erro do agendador chega como mensagem, nao como excecao.
        for _ in range(2):
            agendador.agendar(session_id="s1", user_id="u1", tarefa="x", cron="0 9 * * *")
        r = agendador.agendar(session_id="s1", user_id="u1", tarefa="x", cron="0 9 * * *")
        assert not r["ok"] and "limite" in r["erro"]
    finally:
        agendador.limpar()


def test_agendar_uma_vez_entende_daqui_a_trinta_minutos():
    from sentury.external import agendador

    agendador.registrar(_AgendadorFalso())
    try:
        r = agendador.agendar(
            session_id="s1", user_id="u1", tarefa="lembrar da reuniao",
            quando="daqui a 30 minutos",
        )
        assert r["ok"] and r["kind"] == "once"
        assert r["delay_sec"] == 1800
    finally:
        agendador.limpar()


def test_sem_agendador_registrado_a_ferramenta_diz_isso():
    """Num modo sem agendamento a ferramenta responde, nao estoura."""
    from sentury.external import agendador

    agendador.limpar()
    r = agendador.agendar(session_id="s1", user_id="u1", tarefa="x", cron="0 9 * * *")
    assert not r["ok"] and "indisponivel" in r["erro"]


def test_agendamento_sobrevive_ao_restart_sem_redis(tmp_path, monkeypatch):
    """Os agendamentos moram em disco local e voltam depois do restart."""
    import asyncio
    import json

    from sentury.external.cron_scheduler import CronScheduler

    class _Settings:
        pass

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    agendador = CronScheduler(orchestrator=None, session_store=None, settings=_Settings())

    async def cenario():
        agendador.jobs["j1"] = {
            "id": "j1", "session_id": "s1", "user_id": "u1", "prompt": "me manda o Medida",
            "kind": "cron", "cron_expr": "0 9 * * 1", "interval_sec": None,
            "chat_id": None, "active": True, "created_at": 0, "last_run": None, "run_count": 0,
        }
        await agendador._persist()

    asyncio.run(cenario())

    arquivo = tmp_path / "agendamentos.json"
    assert arquivo.exists(), "nao gravou em disco"
    guardado = json.loads(arquivo.read_text(encoding="utf-8"))
    assert guardado[0]["cron_expr"] == "0 9 * * 1"
    # E volta na leitura, que e o que o startup faz.
    assert agendador._ler_local()[0]["prompt"] == "me manda o Medida"


def test_regras_de_erro_vem_do_yaml():
    """Quem diz o que e 'sem credito' e uma tabela, nao um if.

    A redacao da mensagem muda quando o provedor quer, e o tempo certo de
    espera muda por instalacao e por plano contratado. Nenhuma das duas
    coisas deveria exigir uma versao nova.
    """
    from robinbandit import erros

    try:
        erros.configurar({
            "regras": [
                {"tipo": "credit", "quando_texto": ["saldo insuficiente"]},
                {"tipo": "rate_limit", "quando_texto": ["devagar ai"]},
            ],
            "cooldown_s": {"rate_limit": {"escala": [5, 10]}, "credit": 99},
        })
        assert erros.classificar(Exception("SALDO INSUFICIENTE na conta")) == "credit"
        assert erros.classificar(Exception("devagar ai amigo")) == "rate_limit"
        # Texto que a tabela nova nao cobre cai em "other": nao ha regra
        # escondida no codigo por tras dela.
        assert erros.classificar(Exception("429 too many requests")) == "other"
        assert erros.cooldown_de("credit") == 99
        # A escala avanca com a repeticao e o ultimo degrau se mantem.
        assert (erros.cooldown_de("rate_limit", 1), erros.cooldown_de("rate_limit", 2),
                erros.cooldown_de("rate_limit", 9)) == (5, 10, 10)
    finally:
        # A tabela e estado de PROCESSO: deixar a do teste de pe faz o proximo
        # classificar errado, e o erro aparece longe daqui.
        erros.configurar(None)


def test_credito_e_visto_antes_de_cota():
    """A mensagem de credito esgotado as vezes cita 'quota'. Tratar dinheiro
    acabado como rate limit faz o roteador insistir em quem nao vai voltar."""
    from robinbandit.chain import classify_error

    assert classify_error(Exception("You exceeded your current quota, please check billing")) == "credit"


def _config_com_gateway(tmp_path, extra=""):
    from robinbandit import RobinConfig

    linhas = [
        "version: 1",
        "routing:",
        "  chain_order: [gw]",
        "providers:",
        "  gw:",
        "    adapter: openai",
        "    label: Gateway local",
        "    base_url: http://localhost:20128/v1",
        "    models: [auto]",
    ]
    if extra:
        linhas.append(f"    {extra}")
    caminho = tmp_path / "robin.yaml"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return RobinConfig.from_yaml(str(caminho))


def test_gateway_local_entra_sem_chave_quando_declara(tmp_path):
    """Um gateway local que fala OpenAI entra como mais um provedor, sem
    trocar o RobinBandit. Na propria maquina ele nao tem segredo a exigir.
    """
    from robinbandit import RobinConfig
    from robinbandit.providers import build_provider

    try:
        # Sem a declaracao, provedor sem chave continua fora da cadeia.
        sem = build_provider(_config_com_gateway(tmp_path), "gw", None)
        assert sem is None

        com = build_provider(_config_com_gateway(tmp_path, "chave_opcional: true"), "gw", None)
        assert com is not None and com.name == "gw"
    finally:
        # `build_provider` configura o runtime GLOBAL do Robin a partir da
        # config recebida. Deixar a de brinquedo de pe faz o proximo teste ver
        # um catalogo de contas vazio, e o erro aparece longe daqui.
        build_provider(
            RobinConfig.from_yaml("sentury/plugins/robinbandit/config/sentury.yaml"),
            "fallback", None,
        )


def test_gateway_de_terceiro_nao_vem_declarado():
    """Gateway de terceiro e plugavel, nao e parte da configuracao.

    Declarado, ele apareceria na lista de provedores e no diagnostico de contas
    pedindo uma chave que ninguem escolheu usar. O YAML explica como plugar.
    """
    from robinbandit import RobinConfig

    cfg = RobinConfig.from_yaml("sentury/plugins/robinbandit/config/sentury.yaml")
    gateways = [n for n, p in cfg.providers.items() if (p or {}).get("categoria") == "gateway"]
    assert gateways == [], f"gateway de terceiro nao deveria vir declarado: {gateways}"

    # A explicacao mora no catalogo, que e do RobinBandit: gateway de terceiro
    # nao muda por agente hospedeiro.
    catalogo = pathlib.Path(
        "sentury/plugins/robinbandit/src/robinbandit/padrao.yaml"
    ).read_text(encoding="utf-8")
    assert "Plugar um gateway de terceiros" in catalogo, "sumiu a explicacao de como plugar"


def test_config_do_usuario_sobrepoe_o_repo_sem_apagar_o_resto(tmp_path, monkeypatch):
    """O repo traz os padroes; a maquina traz o que e dela.

    Sem isso, mudar uma linha (um endpoint local, a ordem preferida) exigia
    editar o arquivo versionado: que volta a ser sobrescrito no proximo pull.
    """
    from robinbandit import RobinConfig

    (tmp_path / "config.yaml").write_text(
        "routing:\n  chain_order: [gemini, fallback]\n", encoding="utf-8"
    )
    monkeypatch.setenv("ROBINBANDIT_HOME", str(tmp_path))
    cfg = RobinConfig.from_yaml("sentury/plugins/robinbandit/config/sentury.yaml")

    assert cfg.chain_order == ["gemini", "fallback"], "preferencia do usuario nao venceu"
    # O resto do repo continua de pe: sobrepor uma chave nao apaga as outras.
    assert len(cfg.providers) > 10
    assert cfg.erros.get("regras")


def test_aprendizado_do_roteador_sobrevive_ao_restart_sem_redis(tmp_path, monkeypatch):
    """O aprendizado do roteador mora em disco e volta depois do restart: sem
    isso a exploração inicial seria paga de novo a cada vez."""
    import json
    import time

    from robinbandit import estado

    monkeypatch.setenv("ROBINBANDIT_HOME", str(tmp_path))
    assert estado.carregar() is None

    assert estado.salvar({"gemini": {"ok": 12, "err": 1}})
    assert estado.carregar() == {"gemini": {"ok": 12, "err": 1}}

    # Aprendizado velho descreve um mundo que mudou (modelo aposentado, plano
    # trocado): melhor medir de novo do que confiar nele.
    caminho = estado.caminho()
    caminho.write_text(json.dumps({
        "gravado_em": time.time() - (estado.VALIDADE_S + 60),
        "ranking": {"gemini": {"ok": 999}},
    }), encoding="utf-8")
    assert estado.carregar() is None

    estado.salvar({"groq": {"ok": 3}})
    assert estado.esquecer() and estado.carregar() is None


def test_o_plugin_nao_importa_o_sentury():
    """O RobinBandit tem repositorio proprio: se ele importar `sentury.*`,
    deixa de rodar sozinho la."""
    import pathlib

    raiz = pathlib.Path("sentury/plugins/robinbandit/src")
    ofensores = [
        str(arquivo)
        for arquivo in raiz.rglob("*.py")
        if "from sentury" in arquivo.read_text(encoding="utf-8")
        or "import sentury" in arquivo.read_text(encoding="utf-8")
    ]
    assert not ofensores, f"o plugin passou a depender do host: {ofensores}"


def test_credencial_e_assunto_do_robinbandit(monkeypatch):
    """Quem sabe de credencial e o RB; o Sentury so mostra o que ele produz.

    Antes o host tinha uma lista com onze nomes de variavel escritos a mao:
    declarar um provedor novo no YAML nao bastava, era preciso lembrar de
    editar o host tambem: e esquecer significava a chave nova nunca aparecer.
    """
    from robinbandit import RobinConfig, saldo

    cfg = RobinConfig.from_yaml("sentury/plugins/robinbandit/config/sentury.yaml")

    class _Ambiente:
        GROQ_API_KEY = "k-groq-1,k-groq-2"      # multi-chave: duas cotas
        GEMINI_API_KEY = "k-gemini"

    achadas = saldo.credenciais(cfg, _Ambiente())
    por_provedor = {}
    for item in achadas:
        por_provedor.setdefault(item["provedor"], []).append(item)

    # Multi-chave vira duas entradas: mostrar como uma esconde metade da cota.
    assert len(por_provedor.get("groq", [])) == 2
    assert len(por_provedor.get("gemini", [])) == 1
    # Cada entrada carrega o NOME da variavel, nunca o valor.
    for item in por_provedor["groq"]:
        assert item["variavel"] == "GROQ_API_KEY" and item["rotulo"]


async def test_saldo_nunca_devolve_a_chave():
    """O painel precisa de presenca e saldo, nao de reconhecer o segredo."""
    from robinbandit import RobinConfig, saldo

    cfg = RobinConfig.from_yaml("sentury/plugins/robinbandit/config/sentury.yaml")

    class _Ambiente:
        GROQ_API_KEY = "sk-segredo-que-nao-pode-vazar"

    saldo.limpar_cache()
    resultado = await saldo.consultar(cfg, _Ambiente())
    assert resultado, "deveria listar a credencial configurada"
    bruto = repr(resultado)
    assert "sk-segredo" not in bruto and "_chave" not in bruto
    # Provedor que nao publica saldo diz isso, em vez de aparecer como zerado.
    assert resultado[0]["status"] == "sem_medicao"
    assert resultado[0]["variavel"] == "GROQ_API_KEY"


def test_user_agent_serve_para_buscar_e_para_ler():
    """Site que recusa requisicao sem identificacao devolve 403 e a pesquisa
    perde a fonte; buscador recusa quem se declara bot. O mesmo UA precisa
    passar nos dois."""
    from sentury.tools import web

    assert "Sentury/" in web.AGENTE and "http" in web.AGENTE
    assert "bot" not in web.AGENTE.lower()
    # E o dominio nao entra na identificacao: o agente e generalista.
    assert "CX" not in web.AGENTE


async def test_pesquisar_le_a_pagina_em_vez_de_so_listar(monkeypatch):
    """Responder a partir do trecho do buscador e responder a partir do resumo
    que ele escreveu."""
    from sentury.tools import web

    async def _busca_falsa(consulta, settings, limite=5):
        return {"ok": True, "provedor": "teste", "resultados": [
            {"titulo": "Um", "url": "https://exemplo.test/a", "trecho": "..."},
            {"titulo": "Dois", "url": "https://exemplo.test/b", "trecho": "..."},
        ]}

    async def _leitura_falsa(url, timeout=20.0):
        if url.endswith("/b"):
            return {"ok": False, "motivo": "403"}
        return {"ok": True, "titulo": "Um", "texto": "conteudo inteiro da pagina", "truncado": False}

    monkeypatch.setattr(web, "buscar", _busca_falsa)
    monkeypatch.setattr(web, "_ler_inteira", _leitura_falsa)

    saida = await web.pesquisar("qualquer coisa", None, paginas=2)
    assert saida["lidas"] == 1 and saida["falharam"] == ["https://exemplo.test/b"]
    lida = next(p for p in saida["paginas"] if p["ok"])
    # A URL viaja junto: sem ela a resposta nao tem como citar a fonte.
    assert lida["url"] and "conteudo inteiro" in lida["texto"]


async def test_buscar_web_escolhe_a_profundidade_sem_segunda_tool(monkeypatch):
    from sentury.harness.state import AnalysisState
    from sentury.tools import web
    from sentury.tools.catalog import execute_tool

    chamadas = []

    async def _buscar(consulta, settings, limite=5):
        chamadas.append(("trechos", consulta, limite, 0))
        return {"ok": True, "resultados": []}

    async def _pesquisar(consulta, settings, *, paginas=3, limite=5):
        chamadas.append(("paginas", consulta, limite, paginas))
        return {"ok": True, "resultados": [], "paginas": []}

    monkeypatch.setattr(web, "buscar", _buscar)
    monkeypatch.setattr(web, "pesquisar", _pesquisar)
    state = AnalysisState.new("busca-unificada", "u")

    await execute_tool(None, state, "buscar_web", {"consulta": "sentury"})
    await execute_tool(
        None, state, "buscar_web",
        {"consulta": "sentury", "profundidade": "profunda"},
    )

    assert chamadas == [
        ("trechos", "sentury", 5, 0),
        ("paginas", "sentury", 15, 8),
    ]


async def test_pesquisa_profunda_deduplica_limita_texto_e_le_em_paralelo(monkeypatch):
    import asyncio
    from sentury.tools import web

    async def _busca_falsa(consulta, settings, limite=5):
        assert limite == 20
        return {"ok": True, "resultados": [
            {"titulo": "A", "url": "https://exemplo.test/a?utm_source=x"},
            {"titulo": "A duplicada", "url": "https://EXEMPLO.test/a#secao"},
            {"titulo": "B", "url": "https://exemplo.test/b"},
        ]}

    ativas = 0
    pico = 0

    async def _leitura_falsa(url, timeout=20.0):
        nonlocal ativas, pico
        ativas += 1
        pico = max(pico, ativas)
        await asyncio.sleep(0)
        ativas -= 1
        return {"ok": True, "titulo": url, "texto": "x" * 20_000, "truncado": False}

    monkeypatch.setattr(web, "buscar", _busca_falsa)
    monkeypatch.setattr(web, "_ler_inteira", _leitura_falsa)

    saida = await web.pesquisar("tema", None, paginas=10, limite=20)

    assert saida["fontes_unicas"] == 2 and saida["lidas"] == 2
    assert pico == 2, "as páginas deveriam ser lidas concorrentemente"
    assert all(len(pagina["texto"]) == web.MAX_TEXTO_POR_FONTE for pagina in saida["paginas"])
    assert all(pagina["truncado"] for pagina in saida["paginas"])
