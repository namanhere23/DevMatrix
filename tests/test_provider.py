import pytest
from nexussentry.providers.llm_provider import get_provider, LLMProvider

def test_provider_singleton():
    provider1 = get_provider()
    provider2 = get_provider()
    assert provider1 is provider2

def test_mock_mode():
    provider = LLMProvider()
    provider._available = {}  # force empty keys
    assert provider.mock_mode is True

def test_resolve_provider():
    provider = LLMProvider()
    provider._available = {"gemini": "fake", "groq": "fake"}
    
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
