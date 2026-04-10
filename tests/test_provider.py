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
    assert provider._resolve_provider("anthropic") == "gemini"
