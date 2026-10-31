from sentury.config import Settings
from robinbandit.profiles import DEFAULT_PROFILE_MODELS, parse_profile_targets, resolve_profile_models


def test_parse_profile_targets_csv():
    raw = "groq:openai/gpt-oss-120b, gemini:gemini-3.5-flash"
    assert parse_profile_targets(raw) == [
        {"provider": "groq", "model": "openai/gpt-oss-120b"},
        {"provider": "gemini", "model": "gemini-3.5-flash"},
    ]


def test_parse_profile_targets_ignora_entrada_invalida():
    raw = "sem-separador, openrouter:qwen/qwen3-coder:free, :, groq:"
    assert parse_profile_targets(raw) == [
        {"provider": "openrouter", "model": "qwen/qwen3-coder:free"},
    ]


def test_settings_expoe_targets_por_perfil(monkeypatch):
    monkeypatch.setenv("SENTURY_ANALYSIS_MODELS", "groq:openai/gpt-oss-120b")
    monkeypatch.setenv("SENTURY_ARTIFACT_MODELS", "gemini:gemini-2.5-flash")
    monkeypatch.setenv("SENTURY_CODING_MODELS", "openrouter:qwen/qwen3-coder:free")
    monkeypatch.setenv("SENTURY_FALLBACK_MODELS", "groq:llama-3.1-8b-instant")

    cfg = Settings(_env_file=None)

    assert cfg.sentury_analysis_model_targets == [
        {"provider": "groq", "model": "openai/gpt-oss-120b"}
    ]
    assert cfg.sentury_coding_model_targets == [
        {"provider": "openrouter", "model": "qwen/qwen3-coder:free"}
    ]


def test_resolve_profile_models_usa_defaults_quando_env_vazio():
    cfg = Settings(_env_file=None)
    resolved = resolve_profile_models(cfg)
    assert resolved["analysis"]
    assert resolved["artifact"]
    assert resolved["coding"]
    assert resolved["fallback"]
    assert resolved["analysis"] == DEFAULT_PROFILE_MODELS["analysis"]


def test_preferred_model_for_coding_gemini_antigravity():
    from robinbandit.profiles import preferred_model_for
    assert preferred_model_for("coding", "gemini") == "antigravity-preview-05-2026"
    # O OpenRouter aposentou o qwen3-coder:free; openrouter/free e o sucessor
    # vivo (200k de contexto). Os testes de parsing acima seguem usando um id
    # COM `:` de proposito, porque e esse caso que o parser precisa preservar.
    assert preferred_model_for("coding", "openrouter") == "openrouter/free"
    assert preferred_model_for(None, "gemini") is None
    assert preferred_model_for("analysis", "openrouter") is None


def test_env_override_afeta_o_roteamento_de_verdade(monkeypatch):
    # Antes de wire, SENTURY_CODING_MODELS não mudava nada. Agora deve mudar.
    from robinbandit.profiles import (
        resolve_profile_models, set_active_profiles, preferred_model_for,
    )
    monkeypatch.setenv("SENTURY_CODING_MODELS", "groq:meu-coder-custom")
    cfg = Settings(_env_file=None)
    set_active_profiles(resolve_profile_models(cfg))
    try:
        assert preferred_model_for("coding", "groq") == "meu-coder-custom"
        # gemini saiu do coding (override substitui a lista) → None
        assert preferred_model_for("coding", "gemini") is None
    finally:
        set_active_profiles(None)  # restaura o DEFAULT pros outros testes
