"""Multi-provider: provider genérico OpenAI-compatible, registro e roteador
(cooldown, score/latência, bandit)."""
import pytest

from sentury.config import settings
from robinbandit.openai_compat import OpenAICompatProvider, _parse_quota
from robinbandit.openrouter_provider import OpenRouterProvider
from robinbandit import ProviderRouter, RobinConfig
from robinbandit.providers import describe_from_config


ROBIN_CONFIG = RobinConfig.from_yaml("sentury/plugins/robinbandit/config/sentury.yaml")


def _router():
    return ProviderRouter(
        providers=ROBIN_CONFIG.providers,
        last_resort=ROBIN_CONFIG.last_resort,
        weights=ROBIN_CONFIG.weights,
        strategy=ROBIN_CONFIG.strategy,
        cost_penalties=ROBIN_CONFIG.cost_penalties,
        profiles=ROBIN_CONFIG.profiles,
    )


class _FakeProvider:
    def __init__(self, name):
        self.name = name


def test_url_normaliza_base():
    p = OpenAICompatProvider("x", "https://api.exemplo.ai/v1", "k", ["m"])
    assert p.url == "https://api.exemplo.ai/v1/chat/completions"
    p2 = OpenAICompatProvider("x", "https://api.exemplo.ai/v1/chat/completions", "k", ["m"])
    assert p2.url == "https://api.exemplo.ai/v1/chat/completions"
    p3 = OpenAICompatProvider("x", "https://api.exemplo.ai/v1/", "k", ["m"])
    assert p3.url == "https://api.exemplo.ai/v1/chat/completions"


@pytest.mark.asyncio
async def test_sem_modelos_falha_claro():
    p = OpenAICompatProvider("x", "https://api.exemplo.ai/v1", "k", [])
    with pytest.raises(RuntimeError):
        await p.complete([{"role": "user", "content": "oi"}])


def test_base_urls_e_meta_cobrem_todos():
    for key in ("github", "cerebras", "huggingface", "sambanova", "mistral", "cohere"):
        assert ROBIN_CONFIG.providers[key]["base_url"].startswith("https://")
    # todo provedor tem tier + quality (prior do bandit)
    for key, meta in ROBIN_CONFIG.providers.items():
        assert "tier" in meta and "quality" in meta
        assert 0.0 <= meta["quality"] <= 1.0


def test_describe_providers_estrutura():
    keys = {p["key"] for p in describe_from_config(ROBIN_CONFIG, settings)}
    for key in ROBIN_CONFIG.chain_order:
        assert key in keys


def test_parse_quota_headers():
    assert _parse_quota({"x-ratelimit-remaining-requests": "42"}) == {"rpm": 42, "rpd": None}
    assert _parse_quota({"nada": "aqui"}) is None
    assert _parse_quota(None) is None


def test_cooldown_apos_429():
    r = _router()
    r.record_failure("groq", "rate_limit")
    assert r.cooldown_remaining("groq") > 0
    # reincidência escala o cooldown
    primeiro = r.cooldown_remaining("groq")
    r.record_failure("groq", "rate_limit")
    assert r.cooldown_remaining("groq") >= primeiro
    # sucesso limpa o cooldown
    r.record_success("groq", 200.0)
    assert r.cooldown_remaining("groq") == 0


def test_order_poe_cooled_e_fallback_no_fim():
    r = _router()
    provs = [_FakeProvider("groq"), _FakeProvider("gemini"), _FakeProvider("fallback")]
    r.record_failure("groq", "rate_limit")   # groq em cooldown
    ordered = [getattr(p, "name") for p in r.order(provs)]
    assert ordered[-1] == "fallback"          # demo sempre por último
    assert ordered.index("gemini") < ordered.index("groq")  # saudável antes do cooled


def test_bandit_aprende_qualidade():
    r = _router()
    # provedor bom acumula alpha (sucesso), ruim acumula beta (falha)
    for _ in range(20):
        r.record_success("github", 300.0, context="CRITICAL")
        r.record_failure("cohere", "other", context="CRITICAL")
    snap = r.snapshot()
    assert snap["github"]["health_mean"] > snap["cohere"]["health_mean"]


def test_reward_quality_move_o_bandit():
    r = _router()
    base = r.snapshot()
    # aprovado pelo critic → sobe; corrigido → desce
    for _ in range(5):
        r.reward_quality("github", "CRITICAL", good=True)
        r.reward_quality("cohere", "CRITICAL", good=False)
    snap = r.snapshot()
    assert snap["github"]["quality_mean"] > snap["cohere"]["quality_mean"]


def test_decay_readapta_provedor():
    # provedor vira ruim (falhas) e depois melhora (sucessos): com decay, a
    # qualidade se recupera: não fica engessada no passado ruim.
    r = _router()
    for _ in range(30):
        r.record_failure("groq", "other", context="STANDARD")
    ruim = r.snapshot()["groq"]["health_mean"]
    for _ in range(60):
        r.record_success("groq", 150.0, context="STANDARD")
    bom = r.snapshot()["groq"]["health_mean"]
    assert bom > ruim + 0.2  # readaptou pra cima


def test_quota_penalty_evita_quase_esgotado():
    from robinbandit.router import _Stat
    assert ProviderRouter._quota_penalty(_Stat(rpm_remaining=0)) > ProviderRouter._quota_penalty(_Stat(rpm_remaining=100))
    assert ProviderRouter._quota_penalty(_Stat()) == 0.0            # sem info = neutro
    assert ProviderRouter._quota_penalty(_Stat(rpm_remaining=100)) == 0.0  # folgado = neutro


def test_dump_load_roundtrip():
    r = _router()
    r.record_success("groq", 180.0, context="SIMPLE")
    dump = r.dump()
    r2 = _router()
    r2.load(dump)
    assert r2.snapshot()["groq"]["ok"] == 1


def test_gemini_ordena_por_rpd_e_qualidade():
    from robinbandit.gemini_provider import _order_gemini_models
    ms = ["gemini-3.5-flash", "gemma-4-31b-it", "gemini-2.5-flash"]
    # rotina: workhorse de RPD alto (gemma 1.5K) antes dos de 20/dia
    assert _order_gemini_models(ms, "SIMPLE")[0] == "gemma-4-31b-it"
    # CRITICAL: qualidade primeiro (3.5-flash)
    assert _order_gemini_models(ms, "CRITICAL")[0] == "gemini-3.5-flash"


def test_provider_meta_tem_kinds():
    for key, meta in ROBIN_CONFIG.providers.items():
        assert "kinds" in meta and "text" in meta["kinds"]
    assert set(ROBIN_CONFIG.providers["gemini"]["kinds"]) == {"text", "embed", "media"}


def test_order_prefere_provider_do_perfil_quando_saude_empata():
    class _FixedRng:
        def betavariate(self, a, b):
            return 0.5

    r = _router()
    r._rng = _FixedRng()
    provs = [_FakeProvider("groq"), _FakeProvider("openrouter"), _FakeProvider("fallback")]

    ordered = [p.name for p in r.order(provs, context="coding:CRITICAL")]

    assert ordered[0] == "openrouter"
    assert ordered[-1] == "fallback"


@pytest.mark.asyncio
async def test_openrouter_prefere_modelo_do_perfil(monkeypatch):
    seen_models = []

    class _Resp:
        def __init__(self, model):
            self._model = model
            self.headers = {}
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": f"ok:{self._model}"}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            seen_models.append(json["model"])
            return _Resp(json["model"])

    monkeypatch.setattr("robinbandit.openai_compat.httpx.AsyncClient", lambda timeout=30.0: _Client())

    provider = OpenRouterProvider("dummy", ["openai/gpt-oss-120b:free", "qwen/qwen3-coder:free"])
    result = await provider.complete(
        [{"role": "user", "content": "gere código"}],
        preferred_model="qwen/qwen3-coder:free",
    )

    assert result == "ok:qwen/qwen3-coder:free"
    assert seen_models[0] == "qwen/qwen3-coder:free"


@pytest.mark.asyncio
async def test_openrouter_classify_desliga_reasoning(monkeypatch):
    seen_payloads = []

    class _Resp:
        headers = {}
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"intent":"CHAT","complexity":"SIMPLE","priority":"LOW","events":["DIRECT_RESPONSE"]}'}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            seen_payloads.append(json)
            return _Resp()

    monkeypatch.setattr("robinbandit.openai_compat.httpx.AsyncClient", lambda timeout=30.0: _Client())

    provider = OpenRouterProvider("dummy", ["deepseek/deepseek-v4-pro"])
    await provider.complete([{"role": "user", "content": "opa"}], complexity="CLASSIFY")

    assert seen_payloads
    assert seen_payloads[0]["reasoning_effort"] == "none"
    assert seen_payloads[0]["reasoning"]["enabled"] is False
    assert seen_payloads[0]["max_tokens"] <= 512


@pytest.mark.asyncio
async def test_openai_compat_openrouter_classify_desliga_reasoning(monkeypatch):
    seen_payloads = []

    class _Resp:
        headers = {}
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"intent":"CHAT","complexity":"SIMPLE","priority":"LOW","events":["DIRECT_RESPONSE"]}'}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            seen_payloads.append(json)
            return _Resp()

    monkeypatch.setattr("robinbandit.openai_compat.httpx.AsyncClient", lambda timeout=30.0: _Client())

    provider = OpenAICompatProvider("ultra_max", "https://openrouter.ai/api/v1", "dummy", ["deepseek/deepseek-v4-pro"])
    await provider.complete([{"role": "user", "content": "opa"}], complexity="CLASSIFY")

    assert seen_payloads
    assert seen_payloads[0]["reasoning_effort"] == "none"
    assert seen_payloads[0]["reasoning"]["enabled"] is False
    assert seen_payloads[0]["max_tokens"] <= 512


def test_order_sem_profile_permanece_compativel():
    class _FixedRng:
        def betavariate(self, a, b):
            return 0.5

    r = _router()
    r._rng = _FixedRng()
    provs = [_FakeProvider("groq"), _FakeProvider("gemini"), _FakeProvider("fallback")]

    ordered = [p.name for p in r.order(provs, context="STANDARD")]

    assert "fallback" == ordered[-1]
