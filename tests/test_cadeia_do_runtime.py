"""A cadeia que o Sentury monta (`robinbandit.sentury.ChainProvider`) trata a falha
pelo tipo: recusa e pedido grande não castigam o provedor, a recusa chega ao turno,
a conversa gruda em quem respondeu e o gasto vai para o painel."""
import pytest

import robinbandit.sentury as runtime
from robinbandit.chain import FalhaDaCadeia, iniciar_contagem, iniciar_conversa, recusas_do_turno
from robinbandit.sentury import ChainProvider


class _Prov:
    def __init__(self, roteiro, name, models=None):
        self.roteiro = list(roteiro)
        self.name = name
        self.last_model = name
        self.models = list(models or [])
        self.calls = 0
        self.pedidos_de_modelo = []

    async def complete(self, messages, temperature=0.2, complexity=None, preferred_model=None):
        self.calls += 1
        self.pedidos_de_modelo.append(preferred_model)
        item = self.roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    async def _nada(_s):
        return None
    monkeypatch.setattr(runtime.asyncio, "sleep", _nada)


def _falhas(cadeia, nome):
    return cadeia.router.router._stat(nome).err


async def test_recusa_de_conteudo_vai_para_o_turno_e_nao_castiga_o_provedor():
    iniciar_contagem()
    recusa = _Prov([Exception("blocked by safety settings")], "recusa")
    bom = _Prov(["ok"], "bom")
    cadeia = ChainProvider([recusa, bom])
    cadeia.router.order = lambda candidatos, *a, **k: list(candidatos)

    assert await cadeia.complete([{"role": "user", "content": "oi"}]) == "ok"
    assert [r["provedor"] for r in recusas_do_turno()] == ["recusa"]
    assert _falhas(cadeia, "recusa") == 0


async def test_pedido_grande_demais_nao_castiga_o_provedor():
    grande = _Prov([Exception("413 Request Entity Too Large")], "grande")
    bom = _Prov(["ok"], "bom")
    cadeia = ChainProvider([grande, bom])
    cadeia.router.order = lambda candidatos, *a, **k: list(candidatos)

    assert await cadeia.complete([{"role": "user", "content": "oi"}]) == "ok"
    assert _falhas(cadeia, "grande") == 0


async def test_falha_transitoria_tenta_de_novo_no_mesmo_provedor():
    instavel = _Prov([Exception("503 Service Unavailable"), "voltou"], "instavel")
    cadeia = ChainProvider([instavel])
    assert await cadeia.complete([{"role": "user", "content": "oi"}]) == "voltou"
    assert instavel.calls == 2


async def test_todos_falharam_leva_o_tipo_de_cada_falha():
    a = _Prov([Exception("context_length_exceeded")], "a")
    b = _Prov([Exception("prompt is too long")], "b")
    cadeia = ChainProvider([a, b])
    with pytest.raises(FalhaDaCadeia) as erro:
        await cadeia.complete([{"role": "user", "content": "oi"}])
    assert erro.value.tipos == ["context_length", "context_length"]
    assert erro.value.da_requisicao


async def test_a_conversa_gruda_no_provedor_e_no_modelo_que_responderam():
    iniciar_conversa("conversa-grude")
    primeiro = _Prov(["um", "dois"], "primeiro", models=["m1", "m2"])
    segundo = _Prov(["tres", "quatro"], "segundo", models=["x"])
    cadeia = ChainProvider([primeiro, segundo])

    cadeia.router.order = lambda candidatos, *a, **k: [segundo, primeiro]
    await cadeia.complete([{"role": "user", "content": "oi"}])
    # O roteador agora prefere o outro; a conversa continua com quem respondeu.
    cadeia.router.order = lambda candidatos, *a, **k: [primeiro, segundo]
    assert await cadeia.complete([{"role": "user", "content": "de novo"}]) == "quatro"
    assert primeiro.calls == 0


async def test_o_gasto_de_quem_respondeu_vai_para_o_painel(monkeypatch):
    anotados = []
    monkeypatch.setattr(runtime, "_anotar_o_gasto", lambda provedor, uso: anotados.append((provedor, uso)))
    p = _Prov(["ok"], "pago")
    p.last_usage = {"entrada": 10, "saida": 2, "total": 12}
    await ChainProvider([p]).complete([{"role": "user", "content": "oi"}])
    assert anotados == [("pago", {"entrada": 10, "saida": 2, "total": 12})]


async def test_a_falha_de_todos_fica_gravada_no_turno():
    """Sem a falha na fila, o replay não sabia que ali o modelo tinha falhado."""
    from robinbandit.chain import iniciar_gravacao, respostas_do_turno

    iniciar_gravacao()
    cadeia = ChainProvider([_Prov([Exception("context_length_exceeded")], "a")])
    with pytest.raises(FalhaDaCadeia):
        await cadeia.complete([{"role": "user", "content": "oi"}])
    gravada = respostas_do_turno()[-1]
    assert gravada["tipos"] == ["context_length"] and "context_length_exceeded" in gravada["erro"]
