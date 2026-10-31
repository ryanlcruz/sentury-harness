"""O Router gruda no provedor que respondeu, por conversa, e so solta na falha.

Seguir o ranking a cada chamada faria dois turnos da mesma conversa sairem de
modelos diferentes. Consistencia: mantem quem respondeu e troca so quando falha
ou para de responder.
"""
from robinbandit.routing import chain as cadeia
from robinbandit.routing.chain import ChainProvider


class _Prov:
    def __init__(self, name, roteiro):
        self.name = name
        self.models = [f"{name}-m1", f"{name}-m2"]
        self.roteiro = list(roteiro)
        self.chamado_com = []
        self.last_model = None

    async def complete(self, messages, temperature=0.2, preferred_model=None):
        self.chamado_com.append(preferred_model)
        item = self.roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        self.last_model = f"{self.name}:{preferred_model or self.models[0]}"
        return item


class _RouterQueTroca:
    """Ranking que inverte a ordem a cada chamada, como um bandit indeciso."""

    def __init__(self):
        self.vez = 0

    def order(self, candidatos, context, selection=None, requires=None):
        self.vez += 1
        return list(candidatos) if self.vez % 2 else list(reversed(candidatos))

    def order_models(self, pname, modelos, context):
        return list(reversed(modelos))

    def begin(self, *a, **k): pass
    def end(self, *a, **k): pass
    def record_success(self, *a, **k): pass
    def record_failure(self, *a, **k): pass
    def record_model_failure(self, *a, **k): pass
    def record_quota(self, *a, **k): pass


async def test_mantem_o_modelo_que_respondeu_e_solta_na_falha():
    cadeia._GRUDE.clear()
    a = _Prov("a", ["1", "2", RuntimeError("500 servidor caiu")])
    b = _Prov("b", ["3"])
    ch = ChainProvider([a, b], _RouterQueTroca())
    msgs = [{"role": "user", "content": "oi"}]

    cadeia.iniciar_conversa("c1")
    assert await ch.complete(msgs) == "1"
    grudado = cadeia.grude_da_conversa()
    assert grudado[0] == "a"
    # O ranking agora poe b na frente; o grude mantem a, no mesmo modelo.
    assert await ch.complete(msgs) == "2"
    assert a.chamado_com[-1] == grudado[1]
    # a falha: o grude solta e b responde, e passa a ser o grudado.
    assert await ch.complete(msgs) == "3"
    assert cadeia.grude_da_conversa()[0] == "b"

    cadeia.iniciar_conversa("c2")
    assert cadeia.grude_da_conversa() is None
    cadeia._GRUDE.clear()
