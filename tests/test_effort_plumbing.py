"""E1, encanamento do effort: contextvar, tradução por provedor e payload."""
import asyncio

import pytest

from robinbandit.sentury import ChainProvider, _accepted_kwargs
from sentury.llm.effort import (
    active_effort,
    build_reasoning_payload,
    clear_effort,
    effort_state,
    normalize,
    provider_effort_for,
    use_effort,
)
from robinbandit.groq_provider import _groq_effort


# --- contextvar ---

def test_sem_effort_no_request_e_none():
    assert active_effort() is None


def test_use_e_clear_restauram_o_contexto():
    token = use_effort("high")
    assert active_effort() == "high"
    clear_effort(token)
    assert active_effort() is None


def test_token_restaura_o_nivel_anterior_em_aninhamento():
    fora = use_effort("low")
    dentro = use_effort("high")
    assert active_effort() == "high"
    clear_effort(dentro)
    assert active_effort() == "low"  # reset(token), não "apaga tudo"
    clear_effort(fora)


def test_nivel_invalido_cai_no_default():
    token = use_effort("turbo")
    assert active_effort() == "medium"
    clear_effort(token)


def test_normalize():
    assert normalize("HIGH") == "high"
    assert normalize(" low ") == "low"
    assert normalize("nada") is None
    assert normalize(None) is None


# --- tradução lógico → provedor ---

def test_provider_effort_default():
    assert provider_effort_for("low") == "none"
    assert provider_effort_for("high") == "high"
    assert provider_effort_for(None) is None
    assert provider_effort_for("invalido") is None


def test_policy_por_modo_tem_precedencia(monkeypatch):
    from sentury.llm import effort as mod
    monkeypatch.setitem(mod.EFFORT_POLICY, ("ultra_max", "low"), "medium")
    assert provider_effort_for("low", mode="ultra_max") == "medium"
    assert provider_effort_for("low", mode="ultra") == "none"


def test_build_reasoning_payload():
    assert build_reasoning_payload(None) == {}
    assert build_reasoning_payload("none") == {"reasoning": {"enabled": False, "exclude": True}}
    assert build_reasoning_payload("high") == {"reasoning": {"effort": "high", "exclude": False}}


def test_groq_respeita_a_capacidade_do_modelo():
    assert _groq_effort("openai/gpt-oss-120b", "high") == "high"
    assert _groq_effort("openai/gpt-oss-120b", "xhigh") == "high"   # rebaixa
    assert _groq_effort("qwen/qwen3-32b", "high") is None           # não aceita
    assert _groq_effort("modelo-desconhecido", "high") is None
    assert _groq_effort("openai/gpt-oss-120b", None) is None


# --- chain: só manda o que o provedor aceita ---

class _FakeProvider:
    name = "fake"
    last_model = "fake:m"

    def __init__(self):
        self.recebido = None

    async def complete(self, messages, temperature=0.2, complexity=None,
                       preferred_model=None, tools=None, reasoning_effort=None):
        self.recebido = {"complexity": complexity, "tools": tools,
                         "reasoning_effort": reasoning_effort}
        return "ok"


class _ProviderAntigo:
    """Assinatura sem tools/effort: não pode quebrar."""
    name = "antigo"
    last_model = "antigo:m"

    def __init__(self):
        self.chamado = False

    async def complete(self, messages, temperature=0.2, complexity=None):
        self.chamado = True
        return "ok"


def test_chain_repassa_o_effort_ativo():
    p = _FakeProvider()
    chain = ChainProvider([p], active_effort=active_effort,
                          provider_effort_for=provider_effort_for)
    token = use_effort("high")
    try:
        assert asyncio.run(chain.complete([{"role": "user", "content": "oi"}])) == "ok"
    finally:
        clear_effort(token)
    assert p.recebido["reasoning_effort"] == "high"


def test_chain_nao_manda_effort_no_classify():
    p = _FakeProvider()
    chain = ChainProvider([p], active_effort=active_effort,
                          provider_effort_for=provider_effort_for)
    token = use_effort("high")
    try:
        asyncio.run(chain.complete([{"role": "user", "content": "oi"}], complexity="CLASSIFY"))
    finally:
        clear_effort(token)
    assert p.recebido["reasoning_effort"] is None


def test_chain_omite_effort_quando_o_provedor_nao_aceita():
    p = _ProviderAntigo()
    chain = ChainProvider([p], active_effort=active_effort,
                          provider_effort_for=provider_effort_for)
    token = use_effort("high")
    try:
        assert asyncio.run(chain.complete([{"role": "user", "content": "oi"}])) == "ok"
    finally:
        clear_effort(token)
    assert p.chamado


def test_accepted_kwargs():
    assert "reasoning_effort" in _accepted_kwargs(_FakeProvider().complete)
    assert "reasoning_effort" not in _accepted_kwargs(_ProviderAntigo().complete)

    class ComVarKw:
        async def complete(self, messages, temperature=0.2, **kw):
            return "ok"

    assert _accepted_kwargs(ComVarKw().complete) is None  # aceita qualquer um


# --- degradacao graciosa: modelo que EXIGE raciocinio ---

def test_detecta_rejeicao_de_controle_de_raciocinio():
    from sentury.llm.effort import is_reasoning_rejection
    assert is_reasoning_rejection(
        '{"error":{"message":"Reasoning is mandatory for this endpoint and cannot be disabled."}}')
    assert is_reasoning_rejection('reasoning_effort is not supported by this model')
    # 400 por outro motivo nao pode ser confundido
    assert not is_reasoning_rejection('{"error":{"message":"context length exceeded"}}')
    assert not is_reasoning_rejection("")


def test_registro_de_modelo_sem_controle_e_por_modelo():
    from sentury.llm.effort import (
        mark_reasoning_control_rejected,
        reasoning_control_allowed,
    )
    assert reasoning_control_allowed("modelo-novo/x")
    mark_reasoning_control_rejected("modelo-novo/x")
    assert not reasoning_control_allowed("modelo-novo/x")
    assert reasoning_control_allowed("outro/y")  # nao contamina os demais


def test_400_de_raciocinio_reenvia_sem_o_campo_e_memoriza(monkeypatch):
    """gpt-oss devolve 400 'Reasoning is mandatory'. O turno NAO pode morrer:
    reenvia sem o controle (no Ultra nao ha fallback pra outro provedor)."""
    import httpx

    from robinbandit.openai_compat import OpenAICompatProvider

    enviados = []

    class _Resp:
        def __init__(self, status, payload):
            self.status_code = status
            self.headers = {}
            self.text = ('{"error":{"message":"Reasoning is mandatory for this '
                         'endpoint and cannot be disabled."}}')
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            enviados.append(json)
            tem_reasoning = "reasoning" in (json or {})
            return _Resp(400 if tem_reasoning else 200, json)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client())
    p = OpenAICompatProvider(name="or", base_url="https://openrouter.ai/api/v1",
                             api_key="k", models=["exige/raciocinio"])
    assert asyncio.run(p.complete([{"role": "user", "content": "oi"}],
                                  reasoning_effort="low")) == "ok"
    assert len(enviados) == 2                      # 1 falhou, 1 reenviou
    assert "reasoning" in enviados[0]
    assert "reasoning" not in enviados[1]

    # Memorizou: a proxima chamada ja nao manda o campo.
    enviados.clear()
    asyncio.run(p.complete([{"role": "user", "content": "oi"}], reasoning_effort="low"))
    assert len(enviados) == 1 and "reasoning" not in enviados[0]


def test_detecta_resposta_cortada_pelo_teto_de_tokens(monkeypatch):
    """max_tokens e teto DURO: ao bater nele o modelo para no meio da frase e a
    resposta chega como se estivesse completa. Sem olhar o finish_reason a gente
    entrega texto cortado sem saber."""
    import httpx

    from robinbandit.openai_compat import OpenAICompatProvider

    class _Resp:
        status_code = 200
        headers = {}
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"finish_reason": "length",
                                 "message": {"content": "O NPS do Sudeste caiu porque o backl"}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client())
    p = OpenAICompatProvider(name="x", base_url="https://api.exemplo/v1", api_key="k",
                             models=["m"])
    asyncio.run(p.complete([{"role": "user", "content": "oi"}]))
    assert p.last_truncated is True


def test_resposta_completa_nao_marca_truncamento(monkeypatch):
    import httpx

    from robinbandit.openai_compat import OpenAICompatProvider

    class _Resp:
        status_code = 200
        headers = {}
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": {"content": "Pronto."}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client())
    p = OpenAICompatProvider(name="x", base_url="https://api.exemplo/v1", api_key="k",
                             models=["m"])
    asyncio.run(p.complete([{"role": "user", "content": "oi"}]))
    assert p.last_truncated is False
