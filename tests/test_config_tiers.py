import copy

import pytest

from config import DEFAULT_APP_TIER, FEATURE_MATRIX, load_config


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("APP_TIER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("REQUEST_MAX_BYTES", raising=False)
    monkeypatch.delenv("RATE_LIMIT_REQUESTS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_WINDOW", raising=False)
    yield


def test_default_tier_is_public():
    config = load_config()
    assert config.app_tier == DEFAULT_APP_TIER == "public"
    assert config.features == FEATURE_MATRIX["public"]


def test_invalid_tier_falls_back(monkeypatch):
    monkeypatch.setenv("APP_TIER", "enterprise")
    config = load_config()
    assert config.app_tier == "public"
    assert config.features == FEATURE_MATRIX["public"]


def test_paid_tier_features(monkeypatch):
    monkeypatch.setenv("APP_TIER", "paid")
    config = load_config()
    assert config.features == FEATURE_MATRIX["paid"]


def test_ultimate_tier_enables_llm_when_key_present(monkeypatch):
    monkeypatch.setenv("APP_TIER", "ultimate")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    config = load_config()
    expected = copy.deepcopy(FEATURE_MATRIX["ultimate"])
    expected["FEATURE_LLM_ASSIST"] = True
    assert config.features == expected
