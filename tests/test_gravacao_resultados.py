"""O traço guarda o que cada ferramenta que age no mundo devolveu."""
from sentury.harness import gravacao_do_turno as gravacao
from sentury.mutation import replay
from sentury.harness.pausa_do_turno import autorizacao_pendente


def _com_lista():
    lista = []
    marca = gravacao.RESULTADOS_DO_TURNO.set(lista)
    return lista, marca


def test_acao_e_leitura_do_disco_sao_anotadas():
    lista, marca = _com_lista()
    try:
        gravacao.anotar_resultado("browser", {"acao": "navegar", "url": "https://exemplo.com"}, {"ok": True, "titulo": "Exemplo"})
        gravacao.anotar_resultado("ler_arquivo", {"caminho": "a.txt"}, {"conteudo": "x"})
        gravacao.anotar_resultado("listar_arquivos", {"caminho": "."}, {"itens": []})
        gravacao.anotar_resultado("computador", {"acao": "clicar"}, erro="RuntimeError: sem tela")
    finally:
        gravacao.RESULTADOS_DO_TURNO.reset(marca)
    assert [r["tool"] for r in lista] == ["browser", "ler_arquivo", "listar_arquivos", "computador"]
    assert lista[0]["resultado"]["titulo"] == "Exemplo"
    assert lista[1]["resultado"]["conteudo"] == "x"
    assert lista[2]["resultado"]["itens"] == []
    assert lista[3]["erro"].startswith("RuntimeError")


def test_leitura_autorizada_no_registro_nao_e_anotada(setor_teste):
    lista, marca = _com_lista()
    try:
        gravacao.anotar_resultado("consultar_medida", {}, {"valor": 1})
    finally:
        gravacao.RESULTADOS_DO_TURNO.reset(marca)
    assert lista == []


def test_fora_de_gravacao_nao_anota_nada():
    gravacao.anotar_resultado("browser", {}, {"ok": True})
    assert gravacao.RESULTADOS_DO_TURNO.get() is None


def test_texto_gigante_e_objeto_estranho_ficam_leves():
    lista, marca = _com_lista()
    try:
        gravacao.anotar_resultado("computador", {"acao": "ver"}, {"print": "A" * 50_000, "quando": object()})
    finally:
        gravacao.RESULTADOS_DO_TURNO.reset(marca)
    resultado = lista[0]["resultado"]
    assert resultado["print"].startswith("[omitido no traço: 50000")
    assert isinstance(resultado["quando"], str)


def test_traco_guarda_os_resultados(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_TRACOS_DIR", str(tmp_path))
    gravado = replay.gravar(mensagem="abra o site", conjunto="desenvolvimento",
                            resultados_ferramentas=[{"tool": "browser", "argumentos": {}, "resultado": {"ok": True}}])
    lido = replay.carregar(gravado.id)
    assert lido.resultados_ferramentas == [{"tool": "browser", "argumentos": {}, "resultado": {"ok": True}}]


class TestFila:
    def test_casa_pelo_pedido_e_nao_pela_posicao(self):
        fila = gravacao.FilaDeResultados([
            {"tool": "browser", "argumentos": {"acao": "navegar", "url": "b"}, "resultado": {"ok": "b"}},
            {"tool": "browser", "argumentos": {"acao": "navegar", "url": "a"}, "resultado": {"ok": "a"}},
        ])
        assert fila.servir("browser", {"acao": "navegar", "url": "a"})["resultado"] == {"ok": "a"}
        assert fila.sobraram == 1 and fila.servidos == 1

    def test_anotacao_da_execucao_nao_conta_no_pedido(self):
        fila = gravacao.FilaDeResultados([
            {"tool": "computador", "argumentos": {"acao": "abrir", "_feito": "na frente"}, "resultado": {"ok": True}},
        ])
        assert fila.servir("computador", {"acao": "abrir"}) is not None

    def test_pedido_diferente_e_divergencia(self):
        fila = gravacao.FilaDeResultados([
            {"tool": "browser", "argumentos": {"url": "a"}, "resultado": {}},
        ])
        assert fila.servir("browser", {"url": "outra"}) is None
        assert fila.servir("computador", {}) is None
        assert fila.divergencias == [
            "browser: argumentos diferentes do gravado", "computador: sem resultado gravado",
        ]

    def test_erro_gravado_volta_com_o_mesmo_tipo(self):
        import pytest

        with pytest.raises(TimeoutError, match="prazo"):
            gravacao.resultado_gravado({"tool": "x", "erro": "prazo", "tipo_erro": "TimeoutError"})
        with pytest.raises(RuntimeError, match="sem tela"):
            gravacao.resultado_gravado({"tool": "x", "erro": "sem tela", "tipo_erro": "ErroDoComputador"})

    def test_resultado_servido_e_copia(self):
        registro = {"tool": "x", "resultado": {"lista": [1]}}
        gravacao.resultado_gravado(registro)["lista"].append(2)
        assert registro["resultado"] == {"lista": [1]}


def test_acao_no_mundo_com_resultado_gravado_conta_como_repetivel():
    gravadas = [
        {"tool": "escrever_arquivo", "argumentos": {}, "resultado": {}},
        {"tool": "listar_arquivos", "argumentos": {}, "resultado": {}},
    ]
    assert gravacao.sem_resultado_gravado(["listar_arquivos", "escrever_arquivo"], gravadas) == []
    assert gravacao.sem_resultado_gravado(["escrever_arquivo", "escrever_arquivo"], gravadas) == ["escrever_arquivo"]


class TestReplayServe:
    """O replay devolve o que o mundo devolveu, sem agir de novo."""

    @staticmethod
    def _agente(destino, conteudo="gravado"):
        from sentury.tools.catalog import execute_tool

        class Agente:
            async def handle_message(self, estado, _mensagem):
                try:
                    saida = await execute_tool(None, estado, "escrever_arquivo", {
                        "caminho": str(destino), "conteudo": conteudo,
                    })
                except RuntimeError as exc:
                    saida = {"erro": str(exc)}
                return {"message": str(saida), "harness": {"ferramentas": ["escrever_arquivo"]}}

        return Agente()

    def _traco(self, tmp_path, monkeypatch, destino):
        monkeypatch.setenv("SENTURY_TRACOS_DIR", str(tmp_path / "tracos"))
        return replay.gravar(
            mensagem="grave o arquivo", respostas_llm=["x"], conjunto="desenvolvimento",
            resultado_observado={"mensagem": "", "ferramentas": ["escrever_arquivo"]},
            ambiente={"despacho": "texto"},
            resultados_ferramentas=[{
                "tool": "escrever_arquivo",
                "argumentos": {"caminho": str(destino), "conteudo": "gravado"},
                "resultado": {"ok": True, "bytes": 7},
            }],
        )

    async def test_serve_o_resultado_e_nao_escreve(self, tmp_path, monkeypatch):
        destino = tmp_path / "nao-criar.txt"
        traco = self._traco(tmp_path, monkeypatch, destino)
        saida = await replay.repetir(traco, lambda *_: self._agente(destino))

        assert saida["ok"] is True, saida
        assert saida["mensagem"] == str({"ok": True, "bytes": 7})
        assert saida["ferramentas_servidas"] == 1 and saida["resultados_sobraram"] == 0
        assert not destino.exists()

    async def test_pedido_que_mudou_e_recusado_e_explicado(self, tmp_path, monkeypatch):
        destino = tmp_path / "nao-criar.txt"
        traco = self._traco(tmp_path, monkeypatch, destino)
        saida = await replay.repetir(traco, lambda *_: self._agente(destino, conteudo="outro"))

        assert saida["ok"] is False
        assert saida["ferramentas_bloqueadas"] == ["escrever_arquivo"]
        assert saida["divergencias"] == ["escrever_arquivo: argumentos diferentes do gravado"]
        assert not destino.exists()

    async def test_bateria_conta_divergencia_como_mudanca(self, tmp_path, monkeypatch):
        destino = tmp_path / "nao-criar.txt"
        self._traco(tmp_path, monkeypatch, destino)
        resultado = await replay.bateria(lambda *_: self._agente(destino, conteudo="outro"))

        assert resultado["pulados"] == []
        assert [m["divergencias"] for m in resultado["mudaram"]] == [
            ["escrever_arquivo: argumentos diferentes do gravado"],
        ]


def test_acao_gravada_conta_como_aprovada_so_no_replay():
    """A aprovação dada na produção não fica no traço. No replay, ter o
    resultado gravado prova que a ação rodou lá; fora do replay, nada muda."""
    registro = {"tool": "escrever_arquivo", "argumentos": {"caminho": "a.txt", "conteudo": "x"}, "resultado": {"ok": True}}
    fila = gravacao.FilaDeResultados([registro])
    assert fila.tem("escrever_arquivo", {"caminho": "a.txt", "conteudo": "x"})
    assert not fila.tem("escrever_arquivo", {"caminho": "b.txt", "conteudo": "x"})
    assert fila.sobraram == 1, "consultar não consome"

    marca_fila = gravacao.REPLAY_FERRAMENTAS.set(fila)
    try:
        assert not gravacao.aprovado_na_gravacao("escrever_arquivo", registro["argumentos"])
        marca_replay = gravacao.EM_REPLAY.set(True)
        try:
            assert gravacao.aprovado_na_gravacao("escrever_arquivo", registro["argumentos"])
            assert not gravacao.aprovado_na_gravacao("escrever_arquivo", {"caminho": "outro.txt"})
        finally:
            gravacao.EM_REPLAY.reset(marca_replay)
    finally:
        gravacao.REPLAY_FERRAMENTAS.reset(marca_fila)


def test_no_replay_escrita_sem_resultado_gravado_pede_cartao_mesmo_com_tudo_liberado(tmp_path, monkeypatch):
    """A permissão desta máquina hoje não decide o replay: o que decide é o que
    a produção fez. Sem resultado gravado, a ação não rodou lá; o cartão abriu."""
    from sentury.data.store import SemDados
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState
    from sentury.tools import permissoes

    monkeypatch.setenv("SENTURY_HOME", str(tmp_path))
    monkeypatch.setenv("SENTURY_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(permissoes, "_DA_SESSAO", {})
    monkeypatch.setattr(permissoes, "_CREDITO_UNICO", {})
    permissoes.definir_permitir_tudo(True)
    try:
        orq = SenturyOrchestrator(planner=None, responder=None, store=SemDados())
        estado = AnalysisState.new("s", "u")
        passo = {"tool": "escrever_arquivo", "arguments": {"caminho": str(tmp_path / "a.txt"), "conteudo": "x"}}

        assert autorizacao_pendente(orq, [passo], estado) is None, "fora do replay, tudo liberado passa"
        marca_replay = gravacao.EM_REPLAY.set(True)
        try:
            marca_fila = gravacao.REPLAY_FERRAMENTAS.set(gravacao.FilaDeResultados([]))
            try:
                assert autorizacao_pendente(orq, [passo], estado), "sem resultado gravado, pede o cartão"
            finally:
                gravacao.REPLAY_FERRAMENTAS.reset(marca_fila)
            gravada = {"tool": "escrever_arquivo", "argumentos": passo["arguments"], "resultado": {"ok": True}}
            marca_fila = gravacao.REPLAY_FERRAMENTAS.set(gravacao.FilaDeResultados([gravada]))
            try:
                assert autorizacao_pendente(orq, [passo], estado) is None, "gravada, rodou na produção"
            finally:
                gravacao.REPLAY_FERRAMENTAS.reset(marca_fila)
        finally:
            gravacao.EM_REPLAY.reset(marca_replay)
    finally:
        permissoes.definir_permitir_tudo(False)
