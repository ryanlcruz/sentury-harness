"""O registro e a base do Mutation: sem ele nao ha linhagem nem a que voltar.

Estes testes protegem as tres regras que sustentam o resto: o estado so anda
pelo caminho declarado, nada e aprovado sem evidencia, e o que morreu continua
sendo evidencia.
"""
import pytest

from sentury.mutation import registro


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTURY_MUTATION_DIR", str(tmp_path))
    yield


def _abrir(**kw):
    base = {"alvo": "harness.reviewer", "hipotese": "ativar o reviewer so em risco alto"}
    return registro.abrir(**{**base, **kw})


def test_mutacao_nasce_proposta_e_com_id_citavel():
    m = _abrir(observacao="reviewer roda em tudo e custa caro")
    assert m.id == "AM-0001" and m.estado == "proposta"
    # Sequencial e legivel: `AM-0014` se cita numa conversa, um UUID nao.
    assert _abrir().id == "AM-0002"


def test_mutacao_sem_alvo_ou_hipotese_nao_abre():
    """Sem alvo nao ha o que comparar; sem hipotese nao ha como dizer se deu
    certo: e a afericao vira 'parece bom'."""
    with pytest.raises(ValueError, match="alvo"):
        registro.abrir(alvo="", hipotese="alguma coisa")
    with pytest.raises(ValueError, match="hipotese"):
        registro.abrir(alvo="harness.x", hipotese="")


def test_estado_so_anda_pelo_caminho_declarado():
    m = _abrir()
    # Nao da para promover o que nunca foi avaliado.
    with pytest.raises(ValueError, match="nao pode ir"):
        registro.transicionar(m.id, "promovida")

    registro.transicionar(m.id, "candidata")
    registro.transicionar(m.id, "em_avaliacao")
    aprovada = registro.transicionar(m.id, "aprovada", fitness={"acerto": 0.91})
    assert aprovada.estado == "aprovada"

    promovida = registro.transicionar(m.id, "promovida")
    # Do topo so da para voltar revertendo: e isso fica registrado como tal.
    assert registro.ESTADOS[promovida.estado] == ("revertida",)


def test_nao_se_aprova_sem_evidencia():
    m = _abrir()
    registro.transicionar(m.id, "candidata")
    registro.transicionar(m.id, "em_avaliacao")
    with pytest.raises(ValueError, match="evidencia"):
        registro.transicionar(m.id, "aprovada")


def test_reprovar_exige_dizer_o_porque():
    """Guardar que algo falhou sem o motivo faz a proxima tentativa repetir o
    mesmo caminho as cegas."""
    m = _abrir()
    registro.transicionar(m.id, "candidata")
    registro.transicionar(m.id, "em_avaliacao")
    with pytest.raises(ValueError, match="motivo"):
        registro.transicionar(m.id, "rejeitada")

    rejeitada = registro.transicionar(
        m.id, "rejeitada", motivo="regressao de qualidade no eval-v7",
        revisit_if=["modelo do reviewer mudar"],
    )
    assert rejeitada.motivo and rejeitada.revisit_if


def test_o_que_morreu_continua_sendo_evidencia():
    """Apagar o que nao deu certo e perder o resultado negativo do experimento."""
    m = _abrir()
    registro.transicionar(m.id, "candidata")
    registro.transicionar(m.id, "em_avaliacao")
    registro.transicionar(m.id, "rejeitada", motivo="piorou a latencia",
                          revisit_if=["latencia do provedor melhorar"])

    tentados = registro.ja_tentado("harness.reviewer")
    assert [t.id for t in tentados] == [m.id]
    assert tentados[0].revisit_if == ["latencia do provedor melhorar"]
    # E continua listavel: nao sumiu.
    assert m.id in [x.id for x in registro.listar()]


def test_linhagem_sobe_ate_a_raiz():
    primeira = _abrir()
    segunda = _abrir(parent=primeira.id, hipotese="mesma ideia, so no council")
    terceira = _abrir(parent=segunda.id, hipotese="agora com gate de custo")

    assert registro.linhagem(terceira.id) == [terceira.id, segunda.id, primeira.id]
    with pytest.raises(ValueError, match="pai desconhecida"):
        _abrir(parent="AM-9999")


def test_trilha_guarda_o_que_aconteceu():
    m = _abrir()
    registro.registrar_evento(m.id, "commit", "abc1234", arquivos=3)
    registro.registrar_evento(m.id, "custo", "crucible", tokens=18400)
    registro.transicionar(m.id, "candidata")

    tipos = [e["tipo"] for e in registro.historico(m.id)]
    assert tipos == ["aberta", "commit", "custo", "estado"]
    # O custo em tokens fica na trilha: e o que responde "quanto gastou".
    custo = next(e for e in registro.historico(m.id) if e["tipo"] == "custo")
    assert custo["tokens"] == 18400


def test_registro_sobrevive_ao_processo():
    m = _abrir()
    registro.transicionar(m.id, "candidata")
    recarregada = registro.carregar(m.id)
    assert recarregada and recarregada.estado == "candidata"
    assert registro.carregar("AM-0404") is None
