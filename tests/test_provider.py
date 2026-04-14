import pytest
from nexussentry.providers.llm_provider import get_provider, LLMProvider

def test_provider_singleton():
    provider1 = get_provider()
    provider2 = get_provider()
    assert provider1 is provider2

def test_mock_mode():
    provider = LLMProvider()
    provider._available = {}  # force empty keys
    provider._provider_key_pools = {}
    assert provider.mock_mode is True

def test_resolve_provider():
    provider = LLMProvider()
    provider._available = {"gemini": "fake", "groq": "fake"}
    provider._provider_key_pools = {}
    
    # Should respect preference if available
    assert provider._resolve_provider("groq") == "groq"
    
    # Auto should pick gemini as it's priority 1
    assert provider._resolve_provider("auto") == "gemini"
    
    # If prefer is unavailable, fallback to auto
    assert provider._resolve_provider("huggingface") == "gemini"


def test_huggingface_env_alias_detected(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "")
    monkeypatch.setenv("HUGGINGFACEHUB_API_TOKEN", "")
    monkeypatch.setenv("HF_TOKEN", "hf_test_alias_token_1234567890")

    provider = LLMProvider()
    assert "huggingface" in provider.available_providers


def test_multi_key_env_alias_parsing(monkeypatch):
    for env_key in [
        "GROQ_API_KEY",
        "GROK_API_KEY",
        "GROQ_API_KEYS",
        "GROQ_API_KEY_1",
        "GROQ_API_KEY_2",
        "GROQ_API_KEY_3",
        "GROQ_API_KEY_4",
        "GROQ_API_KEY_5",
        "GROQ_API_KEY_6",
        "GROQ_API_KEY_7",
        "GROQ_API_KEY_8",
        "GROQ_API_KEY_9",
        "GROQ_API_KEY_10",
    ]:
        monkeypatch.setenv(env_key, "")
    monkeypatch.setenv("GROQ_API_KEYS", "groq_key_1,groq_key_2")
    monkeypatch.setenv("GROQ_API_KEY_1", "groq_key_3")
    monkeypatch.setenv("GROQ_API_KEY_2", "groq_key_2")

    provider = LLMProvider()

    assert provider._provider_key_pools["groq"] == ["groq_key_1", "groq_key_2", "groq_key_3"]
    assert provider._available["groq"] == "groq_key_1"
