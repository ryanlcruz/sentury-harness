from robinbandit.credentials import KeyRotator


def test_get_gemini_live_api_key_returns_first_configured_key(monkeypatch):
    import sentury.main as m

    monkeypatch.setattr(m.settings, "GEMINI_API_KEY", "k1,k2")

    assert m.get_gemini_live_api_key() == "k1"


def test_get_gemini_live_api_keys_round_robins_for_live_failover(monkeypatch):
    import sentury.main as m

    monkeypatch.setattr(m.settings, "GEMINI_API_KEY", "k1,k2")
    monkeypatch.setattr(m, "_gemini_live_keys", KeyRotator(["k1", "k2"]))

    assert m.get_gemini_live_api_keys() == ["k1", "k2"]
    assert m.get_gemini_live_api_keys() == ["k2", "k1"]
