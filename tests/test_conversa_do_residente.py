import asyncio

import pytest
from fastapi.testclient import TestClient

from sentury.residentes import registro, tarefas, worker


@pytest.fixture
def http(tmp_path, monkeypatch):
    import sentury.main as main
    from sentury.memory.local_session_store import LocalSessionStore
    from sentury.memory.session_index import SessionIndex

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.delenv("SENTURY_HQ_URL", raising=False)
    store = LocalSessionStore(str(tmp_path))
    monkeypatch.setattr(main, "session_store", store)
    monkeypatch.setattr(main, "session_index", SessionIndex(store))
    worker.configurar(None)
    registro.criar({"nome": "atlas", "papel": "cuida da infraestrutura", "objetivo": "verificar disco",
                    "ferramentas": ["ler_arquivo"]})
    main.app.dependency_overrides[main.verify_api_token] = lambda: None
    yield TestClient(main.app), main
    main.app.dependency_overrides.clear()
    worker.configurar(None)


def test_envio_enfileira_na_sessao_propria(http):
    cliente, _ = http
    resposta = cliente.post("/sentury/residentes/atlas/conversa", json={"pedido": "Leia o disco", "user_id": "pessoa"})
    assert resposta.status_code == 201
    assert resposta.json()["origem"] == "conversa:pessoa:agente:atlas"
    conversa = cliente.get("/sentury/residentes/atlas/conversa").json()
    assert conversa["session_id"] == "agente:atlas"
    assert conversa["mensagens"][-1]["content"] == "Leia o disco"
    assert conversa["agente"]["previa"] == "Leia o disco"


def test_historico_real_esconde_identidade_e_nao_duplica_observador(http):
    cliente, main = http
    tarefa = tarefas.enfileirar("atlas", "Verifique o disco", "conversa:pessoa:agente:atlas")
    async def preparar():
        _, state = await main._load_state("agente:atlas", "hq")
        state.history = [
            {"role": "system", "content": "identidade interna"},
            {"role": "user", "content": tarefa.pedido, "origem": f"tarefa:{tarefa.id}"},
            {"role": "assistant", "content": "Disco verificado."}]
        await main._persist_state(state)
    asyncio.run(preparar())
    tarefas.comecar(tarefa.id)
    feita = tarefas.concluir(tarefa.id, "Disco verificado.")
    asyncio.run(main._resposta_do_residente_na_conversa(feita))
    dados = cliente.get("/sentury/residentes/atlas/conversa").json()
    assert [m["content"] for m in dados["mensagens"]] == [tarefa.pedido, "Disco verificado."]
    assert dados["mensagens"][-1]["residente"] == "atlas"


def test_espera_e_resposta_usam_mesma_tarefa_da_hq(http):
    cliente, _ = http
    tarefa = tarefas.enfileirar("atlas", "Confirme o destino")
    tarefas.comecar(tarefa.id)
    tarefas.esperar(tarefa.id, "Qual pasta?", resposta="Qual pasta?")
    dados = cliente.get("/sentury/residentes/atlas/conversa").json()
    assert dados["esperando"][0]["id"] == tarefa.id
    resposta = cliente.post(f"/sentury/residentes/_tarefas/{tarefa.id}/responder",
                           json={"resposta": "", "retorno": "Downloads"})
    assert resposta.status_code == 200
    assert resposta.json()["estado"] == tarefas.NA_FILA


def test_residente_desconhecido_nao_cria_sessao(http):
    cliente, _ = http
    assert cliente.get("/sentury/residentes/ausente/conversa").status_code == 422


def test_vez_na_mesa_e_pedido_de_colega_aparecem_curtos():
    from sentury.residentes import conversa, mesa, registro, tarefas

    registro.criar({"nome": "atlas", "papel": "planejador", "objetivo": "organizar", "ferramentas": ["ler_arquivo"]})
    assunto = mesa.abrir("qual fonte usar?", "pessoa", "@atlas")
    vez = tarefas.enfileirar("atlas", "É a sua vez (3 falas restantes)...", f"{mesa.ORIGEM}{assunto.id}")
    pai = tarefas.enfileirar("atlas", "garanta o backup")
    tarefas.comecar(pai.id)
    registro.criar({"nome": "forge", "papel": "construtor", "objetivo": "rodar", "ferramentas": ["ler_arquivo"]})
    colega = tarefas.enfileirar("forge", "leia o log", "agente:atlas", pai.id)
    assert conversa._o_que_chegou(vez) == "Vez na Mesa: qual fonte usar?"
    assert conversa._o_que_chegou(colega) == "Atlas pediu: leia o log"
    assert conversa._o_que_chegou(pai) == "garanta o backup"


def test_a_conversa_diz_quando_ele_esta_trabalhando(http):
    """Sem isto a tela ficava parada entre o pedido e a resposta, como se o
    pedido tivesse se perdido."""
    cliente, _ = http
    assert cliente.get("/sentury/residentes/atlas/conversa").json()["trabalhando"] is False
    tarefa = tarefas.enfileirar("atlas", "Leia o disco", "conversa:pessoa:agente:atlas")
    assert cliente.get("/sentury/residentes/atlas/conversa").json()["trabalhando"] is True
    tarefas.comecar(tarefa.id)
    assert cliente.get("/sentury/residentes/atlas/conversa").json()["trabalhando"] is True
    tarefas.concluir(tarefa.id, "Disco ok.")
    assert cliente.get("/sentury/residentes/atlas/conversa").json()["trabalhando"] is False


def test_tela_mostra_o_pedido_e_quem_esta_trabalhando():
    """Os dois chats mostram o pedido na hora e o residente escrevendo enquanto trabalha."""
    from pathlib import Path

    cliente = Path("sentury/client/src")
    conversa = (cliente / "features/residentes/ConversaDoResidente.tsx").read_text(encoding="utf-8")
    assert "setEnviado(texto)" in conversa and "<Digitando" in conversa
    digitando = (cliente / "features/residentes/Digitando.tsx").read_text(encoding="utf-8")
    assert "está escrevendo" in digitando and 'role="status"' in digitando
    principal = (cliente / "app/AppShell.tsx").read_text(encoding="utf-8")
    assert "<ResidenteTrabalhando" in principal
    composer = (cliente / "features/chat/Composer.tsx").read_text(encoding="utf-8")
    assert "event.key === 'Tab'" in composer, "Tab escolhe a sugestão do @"


def test_mencoes_do_comeco_abrem_o_chip_e_as_do_meio_ficam_com_o_sentury():
    """`@alfa @nina faça X` vai aos dois e abre o chip "Falando com"; `@` no meio
    da frase é fala sobre o residente, para o Sentury."""
    import shutil
    import subprocess
    from pathlib import Path

    cliente = Path("sentury/client")
    composer = (cliente / "src/features/chat/Composer.tsx").read_text(encoding="utf-8")
    assert "Falando com {nomeVisivel(nome)}" in composer and "Voltar ao Sentury" in composer
    assert "enviarAosResidentes(sessionId, alvos, pedido)" in composer
    node = shutil.which("node")
    if not node or not (cliente / "node_modules/typescript").exists():
        pytest.skip("o resto precisa de Node e npm install")
    script = """
    const fs = require('fs'), ts = require('typescript'), assert = require('node:assert/strict');
    const codigo = ts.transpileModule(fs.readFileSync('src/runtime/interlocutores.ts', 'utf8'), {
      compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
    const m = {exports: {}}; new Function('exports', codigo)(m.exports);
    const conhecido = nome => ['alfa', 'nina'].includes(nome.toLowerCase());
    assert.deepEqual(m.exports.mencoesIniciais('@alfa @Nina faça o resumo', conhecido),
                     {nomes: ['alfa', 'nina'], pedido: 'faça o resumo'});
    assert.deepEqual(m.exports.mencoesIniciais('pergunte ao @alfa como foi', conhecido),
                     {nomes: [], pedido: 'pergunte ao @alfa como foi'});
    assert.deepEqual(m.exports.mencoesIniciais('@zeca oi', conhecido), {nomes: [], pedido: '@zeca oi'});
    """
    resultado = subprocess.run([node, "-e", script], cwd=cliente, capture_output=True, text=True, timeout=30)
    assert resultado.returncode == 0, resultado.stderr


def test_a_conversa_principal_mostra_o_resumo_e_aponta_para_o_chat_do_residente():
    """Cada residente tem chat próprio: na conversa do Sentury o encaminhamento é
    uma linha com os nomes, e a resposta leva ao chat de quem respondeu."""
    from pathlib import Path

    src = Path("sentury/client/src")
    bolha = (src / "features/chat/MessageBubble.tsx").read_text(encoding="utf-8")
    assert "<EncaminhadoAosResidentes nomes={mencionados(message)}" in bolha
    assert "Continuar com {nomeVisivel(message.residente)}" in bolha
    linha = (src / "features/chat/EncaminhadoAosResidentes.tsx").read_text(encoding="utf-8")
    assert "abrirConversaDoResidente(nome)" in linha
    shell = (src / "app/AppShell.tsx").read_text(encoding="utf-8")
    assert "aoAbrirConversaDoResidente(" in shell
    composer = (src / "features/chat/Composer.tsx").read_text(encoding="utf-8")
    assert "'/sentury/residentes/_mencao'" in composer


def test_o_arroba_acha_as_mesas_e_o_chip_leva_a_conversa_para_la():
    """Escolher uma Mesa no @ liga o chip "Na Mesa"; com vários residentes no chip,
    "Levar para a Mesa" abre um assunto com eles. A conversa mostra só a linha e o
    resumo, com o caminho até o assunto."""
    from pathlib import Path

    src = Path("sentury/client/src")
    composer = (src / "features/chat/Composer.tsx").read_text(encoding="utf-8")
    assert "Mesas abertas" in composer and "escolherMesa(assunto)" in composer
    assert "Na Mesa: {mesaDaConversa.titulo}" in composer and "Levar para a Mesa" in composer
    assert "'/sentury/residentes/_levar_a_mesa'" in composer
    bolha = (src / "features/chat/MessageBubble.tsx").read_text(encoding="utf-8")
    assert "<EncaminhadoAMesa id={message.mesa.id}" in bolha and "Mesa fechou: {message.mesa.titulo}" in bolha
    assert "ou escreva @{message.residente} aqui" in bolha
    shell = (src / "app/AppShell.tsx").read_text(encoding="utf-8")
    assert "aoAbrirAssuntoDaMesa(" in shell and "inicial={assuntoDaMesa}" in shell
    view = (src / "features/residentes/MesaView.tsx").read_text(encoding="utf-8")
    assert "residentes.falarNoAssunto(assunto.id" in view


def test_o_chat_do_residente_chama_colega_mesa_e_skill():
    """No chat de um residente, `@` lista colegas e Mesas (e abre uma nova com ele),
    e `/` lista as skills dele antes das outras. Na Mesa ele entra chamado."""
    from pathlib import Path

    src = Path("sentury/client/src/features/residentes")
    campo = (src / "CampoDoResidente.tsx").read_text(encoding="utf-8")
    assert "grupo: 'Colegas'" in campo and "Nova Mesa com ${Nome}" in campo
    assert "Skills de ${Nome}" in campo and "skillsDele.includes(s.name)" in campo
    conversa = (src / "ConversaDoResidente.tsx").read_text(encoding="utf-8")
    assert "skillsDele={agente?.skills || []}" in conversa
    assert "const fala = `@${nome} ${texto}`" in conversa
    assert "residentes.falarNoAssunto(destino.id, fala)" in conversa


def _anexo(nome="dados.txt", conteudo=b"total=27"):
    import base64
    return {"nome": nome, "data_url": "data:text/plain;base64," + base64.b64encode(conteudo).decode("ascii")}


def test_anexo_acompanha_tarefa_e_volta_no_historico(http, monkeypatch):
    from pathlib import Path
    from sentury.residentes import caixa, hq, registro

    cliente, main = http
    monkeypatch.setattr(caixa, "disponivel", lambda: False)
    resposta = cliente.post("/sentury/residentes/atlas/conversa", json={
        "pedido": "Leia o total", "user_id": "pessoa", "arquivos": [_anexo()]})
    assert resposta.status_code == 201
    tarefa = tarefas.carregar(resposta.json()["id"])
    assert Path(tarefa.anexos[0]["caminho"]).read_bytes() == b"total=27"
    conversa = cliente.get("/sentury/residentes/atlas/conversa").json()
    assert conversa["mensagens"][-1]["content"] == "Leia o total\n\n[anexos: dados.txt]"
    assert conversa["mensagens"][-1]["pedido_original"] == "Leia o total"

    async def executar(state, mensagem):
        from sentury.residentes import escopo
        from sentury.tools import arquivos
        assert escopo.pode_usar("ler_arquivo")
        assert "dados.txt" in mensagem and "total=27" not in mensagem
        state.history.append({"role": "user", "content": mensagem})
        lido = arquivos.ler(tarefa.anexos[0]["caminho"])
        assert "27" in str(lido)
        state.history.append({"role": "assistant", "content": "O total é 27."})
        return {"message": "O total é 27."}

    monkeypatch.setattr(main.orchestrator, "handle_message", executar)
    tarefas.comecar(tarefa.id)
    resultado = asyncio.run(main._rodar_turno_do_residente(registro.carregar("atlas"), tarefa))
    tarefas.concluir(tarefa.id, resultado["message"])
    conversa = cliente.get("/sentury/residentes/atlas/conversa").json()
    assert [m["content"] for m in conversa["mensagens"]] == ["Leia o total\n\n[anexos: dados.txt]", "O total é 27."]
    async def verificar_artefato():
        _, state = await main._load_state("agente:atlas", "hq")
        assert any(a.get("attachment", {}).get("filename") == "dados.txt" for a in state.artifacts.values())
    asyncio.run(verificar_artefato())


def test_sem_leitura_recusa_anexo_antes_de_gravar(http):
    cliente, _ = http
    registro.criar({"nome": "iris", "papel": "conversa", "objetivo": "responder", "ferramentas": ["listar_arquivos"]})
    resposta = cliente.post("/sentury/residentes/iris/conversa", json={
        "pedido": "Leia", "user_id": "pessoa", "arquivos": [_anexo()]})
    assert resposta.status_code == 422 and "ler_arquivo" in resposta.json()["detail"]
    assert tarefas.listar("iris") == []


@pytest.mark.parametrize("arquivo", [
    {"nome": "ruim.txt", "data_url": "data:text/plain;base64,!errado"},
    {"nome": "ruim.txt", "data_url": "https://example.invalid/arquivo"},
    {"nome": "vazio.txt", "data_url": "data:text/plain;base64,"},
])
def test_anexo_invalido_nao_cria_tarefa(http, arquivo):
    cliente, _ = http
    resposta = cliente.post("/sentury/residentes/atlas/conversa", json={
        "pedido": "Leia", "user_id": "pessoa", "arquivos": [arquivo]})
    assert resposta.status_code == 422
    assert tarefas.listar("atlas") == []


def test_limite_de_quantidade_e_nome_sem_travessia(http):
    from pathlib import Path
    from sentury.tools.arquivos import pasta_de_rascunho
    cliente, _ = http
    corpo = {"pedido": "Leia", "user_id": "pessoa", "arquivos": [_anexo()] * 7}
    assert cliente.post("/sentury/residentes/atlas/conversa", json=corpo).status_code == 422
    assert tarefas.listar("atlas") == []
    corpo["arquivos"] = [_anexo("../../fora.txt")]
    resposta = cliente.post("/sentury/residentes/atlas/conversa", json=corpo)
    assert resposta.status_code == 201
    caminho = Path(resposta.json()["anexos"][0]["caminho"])
    assert caminho.resolve().is_relative_to(pasta_de_rascunho("agente:atlas").resolve())
    assert caminho.name == "fora.txt"


def test_hq_recebe_o_mesmo_upload_com_token(http, monkeypatch):
    cliente, _ = http
    monkeypatch.setenv("SENTURY_HQ_TOKEN", "token-da-bancada")
    corpo = {"pedido": "Leia", "user_id": "pessoa", "arquivos": [_anexo()]}
    assert cliente.post("/hq/agents/atlas/conversa", json=corpo).status_code == 401
    resposta = cliente.post("/hq/agents/atlas/conversa", json=corpo, headers={"Authorization": "Bearer token-da-bancada"})
    assert resposta.status_code == 201 and resposta.json()["anexos"][0]["nome"] == "dados.txt"


async def test_cliente_remoto_encaminha_arquivo_sem_gravar_no_notebook(monkeypatch):
    from sentury.residentes import cliente, anexos
    monkeypatch.setenv("SENTURY_HQ_URL", "https://hq.invalid")
    recebido = []
    async def http(metodo, caminho, corpo):
        recebido.append((metodo, caminho, corpo))
        return {"id": "tarefa"}
    monkeypatch.setattr(cliente, "_http", http)
    corpo = anexos.PedidoNaConversa(pedido="Leia", user_id="pessoa", arquivos=[_anexo()])
    await cliente.pedir_na_conversa("atlas", corpo)
    assert recebido == [("POST", "/agents/atlas/conversa", corpo.model_dump())]


def test_ingresso_da_caixa_so_copia_bytes(http, monkeypatch):
    import base64
    from pathlib import Path
    from types import SimpleNamespace
    from sentury.residentes import caixa, caixa_receber
    cliente, _ = http
    resposta = cliente.post("/sentury/residentes/atlas/conversa", json={
        "pedido": "Leia", "user_id": "pessoa", "arquivos": [_anexo()]})
    origem = Path(resposta.json()["anexos"][0]["caminho"])
    recebido = []
    monkeypatch.setattr(caixa, "garantir", lambda agente: "caixa-atlas")
    def docker(argv, **kwargs):
        recebido.append((argv, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(caixa, "_docker", docker)
    caixa.receber_anexo(registro.carregar("atlas"), origem, "/workspace/recebidos/tarefa/dados.txt")
    argv, argumentos = recebido[0]
    assert argv[:4] == ["docker", "exec", "-i", "caixa-atlas"]
    assert base64.b64decode(argumentos["input"]) == b"total=27"
    assert "docker.sock" not in str(argv) and "--mount" not in argv
    with pytest.raises(ValueError):
        caixa_receber.receber("/etc/credencial", argumentos["input"])


def test_cliente_reutiliza_leitura_e_preserva_indicadores():
    from pathlib import Path
    # O anexo mora no campo do chat; o envio e os indicadores, na conversa.
    fonte = "".join(Path(f"sentury/client/src/features/residentes/{nome}.tsx").read_text(encoding="utf-8")
                    for nome in ("ConversaDoResidente", "CampoDoResidente"))
    assert "lerAnexos" in fonte and "<Plus" in fonte and "arquivos" in fonte
    assert "setEnviado(texto)" in fonte and "<Digitando" in fonte
    assert "pedido_original" in fonte
    bubble = Path("sentury/client/src/features/chat/MessageBubble.tsx").read_text(encoding="utf-8")
    assert 'title="Copiar resposta"' in bubble


def test_tamanho_real_do_anexo_e_limitado(http):
    cliente, _ = http
    arquivo = _anexo(conteudo=b"x" * (8 * 1024 * 1024 + 1))
    resposta = cliente.post("/sentury/residentes/atlas/conversa", json={
        "pedido": "Leia", "user_id": "pessoa", "arquivos": [arquivo]})
    assert resposta.status_code == 422 and "8 MB" in resposta.json()["detail"]
    assert tarefas.listar("atlas") == []


def test_turno_recebe_caminho_da_caixa_e_nao_conteudo(http, monkeypatch):
    from sentury.residentes import anexos, caixa
    cliente, _ = http
    resposta = cliente.post("/sentury/residentes/atlas/conversa", json={
        "pedido": "Leia", "user_id": "pessoa", "arquivos": [_anexo()]})
    tarefa = tarefas.carregar(resposta.json()["id"])
    copiados = []
    monkeypatch.setattr(caixa, "disponivel", lambda: True)
    monkeypatch.setattr(caixa, "receber_anexo", lambda agente, origem, destino: copiados.append((agente.nome, destino)))
    texto = asyncio.run(anexos.contexto_dos_anexos(registro.carregar("atlas"), tarefa))
    assert copiados == [("atlas", f"/workspace/recebidos/{tarefa.id}/dados.txt")]
    assert copiados[0][1] in texto and "total=27" not in texto


def test_caixa_obrigatoria_sem_docker_nao_devolve_caminho_do_host(http, monkeypatch):
    from sentury.residentes import anexos, caixa
    cliente, _ = http
    resposta = cliente.post("/sentury/residentes/atlas/conversa", json={
        "pedido": "Leia", "user_id": "pessoa", "arquivos": [_anexo()]})
    tarefa = tarefas.carregar(resposta.json()["id"])
    monkeypatch.setattr(caixa, "disponivel", lambda: False)
    monkeypatch.setenv("SENTURY_CAIXA_OBRIGATORIA", "true")
    with pytest.raises(ValueError, match="caixa está indisponível"):
        asyncio.run(anexos.contexto_dos_anexos(registro.carregar("atlas"), tarefa))


def test_vezes_na_mesa_viram_uma_linha_por_assunto(http):
    """A conversa da Mesa mora na Mesa: no chat do residente cada assunto aparece
    uma vez só, e as vezes dele lá não se misturam com os pedidos da pessoa."""
    from sentury.residentes import mesa

    cliente, main = http
    assunto = mesa.abrir("riscos do lançamento", "pessoa", "@atlas")
    vezes = [tarefas.enfileirar("atlas", "É a sua vez...", f"{mesa.ORIGEM}{assunto.id}") for _ in range(2)]
    pedido = tarefas.enfileirar("atlas", "Verifique o disco", "conversa:pessoa:agente:atlas")

    async def preparar():
        _, state = await main._load_state("agente:atlas", "hq")
        state.history = []
        for vez in vezes:
            state.history += [{"role": "user", "content": vez.pedido, "origem": f"tarefa:{vez.id}"},
                              {"role": "assistant", "content": "Passei a vez."}]
        state.history += [{"role": "user", "content": pedido.pedido, "origem": f"tarefa:{pedido.id}"},
                          {"role": "assistant", "content": "Disco verificado."}]
        await main._persist_state(state)
    asyncio.run(preparar())
    for tarefa in (*vezes, pedido):
        tarefas.comecar(tarefa.id)
        tarefas.concluir(tarefa.id, "ok")
    mensagens = cliente.get("/sentury/residentes/atlas/conversa").json()["mensagens"]
    assert [m["content"] for m in mensagens] == [
        "Participei da Mesa: riscos do lançamento. A conversa e o resumo estão na Mesa.",
        "Verifique o disco", "Disco verificado."]
    assert mensagens[0]["mesa"] == assunto.id


def test_turno_do_residente_trabalha_na_pasta_dele(http, monkeypatch):
    """O que o residente grava fica numa pasta dele, visível dentro da pasta de
    trabalho do Sentury, e não solto no meio dela; o turno do Sentury não muda."""
    from sentury.residentes import registro
    from sentury.tools import arquivos

    _, main = http
    monkeypatch.setenv("SENTURY_WORKSPACE", str(arquivos.casa_do_sentury().parent / "trabalho"))
    tarefa = tarefas.enfileirar("atlas", "salve um relatório")
    vista = {}

    async def executar(state, mensagem):
        vista["raiz"] = arquivos.raiz_de_trabalho()
        state.history.append({"role": "assistant", "content": "salvo"})
        return {"message": "salvo"}

    monkeypatch.setattr(main.orchestrator, "handle_message", executar)
    tarefas.comecar(tarefa.id)
    asyncio.run(main._rodar_turno_do_residente(registro.carregar("atlas"), tarefa))
    assert vista["raiz"].parts[-2:] == ("Residentes", "Atlas") and vista["raiz"].is_dir()
    assert arquivos.raiz_de_trabalho().name == "trabalho"


def test_catalogo_separa_as_ferramentas_so_dos_residentes():
    from sentury.tools.registry import tools_by_category

    grupos = tools_by_category()
    so_deles = {t["nome"] for t in grupos.get("residentes", [])}
    assert {"memoria_do_agente", "falar_na_mesa", "pedir_ferramenta", "abrir_assunto"} <= so_deles
    fora = {t["nome"] for g, lista in grupos.items() if g != "residentes" for t in lista}
    assert not so_deles & fora and "pedir_ao_agente" in fora
