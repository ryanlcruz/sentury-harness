"""ChainProvider: num 429, espera+retenta o mesmo provedor antes de cascatear."""
import pytest

from robinbandit.sentury import ChainProvider, classify_error


def test_classify_error():
    assert classify_error(Exception("Client error '429 Too Many Requests'")) == "rate_limit"
    assert classify_error(Exception("rate limit exceeded")) == "rate_limit"
    assert classify_error(Exception("401 Unauthorized: invalid api key")) == "auth"
    assert classify_error(Exception("Connection timed out")) == "network"
    assert classify_error(Exception("qualquer outra coisa")) == "other"


class _Prov:
    def __init__(self, roteiro, name="fake"):
        self.roteiro = list(roteiro)
        self.calls = 0
        self.name = name
        self.last_model = name
    async def complete(self, messages, temperature=0.2, complexity=None):
        self.calls += 1
        item = self.roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def test_retenta_no_mesmo_provider_em_429(monkeypatch):
    import robinbandit.sentury as chain
    async def _no_sleep(s): pass
    monkeypatch.setattr(chain.asyncio, "sleep", _no_sleep)
    p = _Prov([Exception("429 Too Many Requests"), "resposta boa"])
    ch = ChainProvider([p])
    out = await ch.complete([{"role": "user", "content": "oi"}])
    assert out == "resposta boa"
    assert p.calls == 2  # 429 -> retry -> sucesso, sem cascatear


async def test_auth_nao_retenta_o_mesmo_provider(monkeypatch):
    # auth (401) NÃO faz retry no mesmo provedor (diferente do 429). Com 1
    # provedor só, a cadeia esgota e levanta: mas o provedor foi chamado 1x só.
    import robinbandit.sentury as chain
    async def _no_sleep(s): pass
    monkeypatch.setattr(chain.asyncio, "sleep", _no_sleep)
    ruim = _Prov([Exception("401 unauthorized"), "nunca chega"], name="ruim")
    ch = ChainProvider([ruim])
    with pytest.raises(RuntimeError):
        await ch.complete([{"role": "user", "content": "oi"}])
    assert ruim.calls == 1  # auth não retenta


async def test_cascateia_para_outro_provider(monkeypatch):
    # 5xx é passageiro: uma nova tentativa no mesmo provedor, depois o próximo
    # entrega. A ordem fica fixa porque o roteador adaptativo aprende com os
    # outros testes da suíte.
    import robinbandit.sentury as chain
    async def _no_sleep(s): pass
    monkeypatch.setattr(chain.asyncio, "sleep", _no_sleep)
    ruim = _Prov([Exception("500 server error"), Exception("500 server error")], name="ruim")
    bom = _Prov(["fallback ok"], name="bom")
    ch = ChainProvider([ruim, bom])
    monkeypatch.setattr(ch.router, "order", lambda provedores, *a, **k: list(provedores))
    out = await ch.complete([{"role": "user", "content": "oi"}])
    assert out == "fallback ok"
    assert ruim.calls == 1 + ch._RATE_LIMIT_RETRIES
    assert bom.calls == 1


# --- Modo Inteligência Máxima (Ultra) ---

async def test_no_ultra_nao_cai_na_cadeia_gratis_quando_ultra_ativo():
    # Dentro de escopos legados no_ultra(), Ultra/Super continua usando somente
    # o tier pago ativo. Nao pode cair na cadeia gratis/demo.
    from robinbandit.sentury import use_ultra_provider, clear_ultra_provider, no_ultra
    ultra = _Prov(["ultra"], name="ultra")
    normal = _Prov(["normal"], name="normal")
    ch = ChainProvider([normal])
    tok = use_ultra_provider(ultra)
    try:
        with no_ultra():
            out = await ch.complete([{"role": "user", "content": "classifica"}])
    finally:
        clear_ultra_provider(tok)
    assert out == "ultra"
    assert ultra.calls == 1
    assert normal.calls == 0


async def test_ultra_tenta_primeiro_e_responde():
    # Com o modo Ultra ativo, o provedor Ultra responde ANTES da cadeia normal:
    # o provedor normal nem é chamado.
    from robinbandit.sentury import use_ultra_provider, clear_ultra_provider
    ultra = _Prov(["resposta ultra"], name="ultra")
    normal = _Prov(["resposta normal"], name="normal")
    ch = ChainProvider([normal])
    tok = use_ultra_provider(ultra)
    try:
        out = await ch.complete([{"role": "user", "content": "oi"}])
    finally:
        clear_ultra_provider(tok)
    assert out == "resposta ultra"
    assert ultra.calls == 1
    assert normal.calls == 0


async def test_reforcado_falha_e_devolve_controle_ao_router(monkeypatch):
    # Reforçado é híbrido: tenta a escolha forte e continua pela cadeia aprendida.
    import robinbandit.sentury as chain
    async def _no_sleep(s): pass
    monkeypatch.setattr(chain.asyncio, "sleep", _no_sleep)
    from robinbandit.sentury import use_ultra_provider, clear_ultra_provider
    ultra = _Prov([Exception("402 insufficient credit")], name="ultra")
    normal = _Prov(["resposta normal"], name="normal")
    ch = ChainProvider([normal])
    tok = use_ultra_provider(ultra)
    try:
        out = await ch.complete([{"role": "user", "content": "oi"}])
    finally:
        clear_ultra_provider(tok)
    assert ultra.calls == 1
    assert normal.calls == 1
    assert out == "resposta normal"


async def test_dedicado_falha_sem_fallback(monkeypatch):
    import robinbandit.sentury as chain
    async def _no_sleep(s): pass
    monkeypatch.setattr(chain.asyncio, "sleep", _no_sleep)
    from robinbandit.sentury import use_ultra_provider, clear_ultra_provider
    dedicado = _Prov([Exception("402 insufficient credit")], name="ultra_max")
    normal = _Prov(["não deve chamar"], name="normal")
    ch = ChainProvider([normal])
    tok = use_ultra_provider(dedicado)
    try:
        with pytest.raises(RuntimeError):
            await ch.complete([{"role": "user", "content": "oi"}])
    finally:
        clear_ultra_provider(tok)
    assert dedicado.calls == 1
    assert normal.calls == 0


async def test_ultra_continua_primeiro_mesmo_com_override_do_planner():
    # Quando o planner anterior usou um provedor normal (ex.: Mistral), o
    # responder pode receber preferred_model_override para manter coerência. No
    # modo Ultra, isso não pode empurrar o provedor normal para frente da chave
    # Ultra; caso contrário o "think" forte planeja e a resposta cai em modelo
    # fraco.
    from robinbandit.sentury import use_ultra_provider, clear_ultra_provider
    ultra = _Prov(["resposta ultra"], name="ultra")
    mistral = _Prov(["resposta mistral"], name="mistral")
    ch = ChainProvider([mistral])
    ch.preferred_model_override = "mistral:mistral-small-latest"

    tok = use_ultra_provider(ultra)
    try:
        out = await ch.complete([{"role": "user", "content": "oi"}])
    finally:
        clear_ultra_provider(tok)

    assert out == "resposta ultra"
    assert ultra.calls == 1
    assert mistral.calls == 0


async def test_ultra_desativado_por_padrao():
    # Sem ativar o modo, o contextvar é None e nada muda: só a cadeia normal.
    ultra_nunca = _Prov(["nunca"], name="ultra")
    normal = _Prov(["resposta normal"], name="normal")
    ch = ChainProvider([ultra_nunca, normal])
    out = await ch.complete([{"role": "user", "content": "oi"}])
    assert out == "resposta normal"
    assert ultra_nunca.calls == 0
