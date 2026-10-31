"""Pool de credenciais: parsing de CSV, detecção de cota e round-robin."""
import pytest

from robinbandit.credentials import KeyRotator, parse_keys, is_quota_error


def test_parse_keys_csv_e_unica():
    assert parse_keys("k1,k2,k3") == ["k1", "k2", "k3"]
    assert parse_keys(" a , b ,, c ") == ["a", "b", "c"]  # trim + descarta vazio
    assert parse_keys("uma") == ["uma"]
    assert parse_keys(None) == []
    assert parse_keys("") == []


def test_is_quota_error():
    assert is_quota_error(Exception("429 Too Many Requests"))
    assert is_quota_error(Exception("rate limit exceeded"))
    assert is_quota_error(Exception("402 insufficient credit"))
    assert is_quota_error(Exception("exceeded your current quota"))
    assert not is_quota_error(Exception("timeout"))
    assert not is_quota_error(Exception("500 server error"))


def test_rotator_uma_chave_nao_rotaciona():
    r = KeyRotator(["so-uma"])
    assert not r.has_multiple
    assert r.order() == ["so-uma"]
    assert r.order() == ["so-uma"]


def test_rotator_round_robin():
    r = KeyRotator(["a", "b", "c"])
    assert r.has_multiple
    # começa em índices diferentes a cada chamada (espalha a carga), mas sempre
    # com TODAS as chaves (failover)
    o1 = r.order(); o2 = r.order(); o3 = r.order()
    assert o1[0] == "a" and o2[0] == "b" and o3[0] == "c"
    for o in (o1, o2, o3):
        assert sorted(o) == ["a", "b", "c"]


def test_provider_aceita_csv_de_chaves():
    from robinbandit.openai_compat import OpenAICompatProvider
    p = OpenAICompatProvider("x", "https://api.exemplo.ai/v1", "k1,k2,k3", ["m"])
    assert p._keys.keys == ["k1", "k2", "k3"] and p._keys.has_multiple
