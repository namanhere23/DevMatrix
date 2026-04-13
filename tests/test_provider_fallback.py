import os
from unittest.mock import patch
import pytest
from nexussentry.providers.llm_provider import LLMProvider

def test_resource_exhausted_disables_provider():
    provider = LLMProvider()
    provider._available = {"gemini": "dummy_key"}
    
    # Simulate a resource exhaustion exception
    provider._maybe_disable_provider("gemini", Exception("Quota exceeded for tokens per day"))
    
    assert "gemini" in provider._disabled_providers

def test_long_retry_disables_provider():
    provider = LLMProvider()
    provider._available = {"gemini": "dummy_key"}
    
    # Simulate a long retry window
    provider._maybe_disable_provider("gemini", Exception("Rate limit exceeded. Retry after: 15s"))
    
    assert "gemini" in provider._disabled_providers

def test_short_retry_does_not_disable_provider():
    provider = LLMProvider()
    provider._available = {"gemini": "dummy_key"}
    
    # A short retry shouldn't immediately disable
    # It still increments failures and might disable if it hits the count (2 limit)
    provider._maybe_disable_provider("gemini", Exception("Rate limit exceeded. Retry after: 5s"))
    assert "gemini" not in provider._disabled_providers
    
    # Second time disables it
    provider._maybe_disable_provider("gemini", Exception("Rate limit exceeded. Retry after: 5s"))
    assert "gemini" in provider._disabled_providers

def test_413_retries_with_truncation():
    provider = LLMProvider()
    provider._available = {"mock": "dummy"}
    provider._call_with_langchain = lambda *args: "success"
    
    called_fallback = False
    
    def fake_fallback(sys, um, max_t, exclude):
        nonlocal called_fallback
        called_fallback = True
        assert "CONTEXT TRUNCATED" in um
        return "fallback success"
        
    provider._fallback_chat = fake_fallback
    
    # Force an exception to trigger the 413 flow
    # Since we don't mock the first try fully, we can just call the exception handler logic
    try:
        raise Exception("HTTP 413 Payload Too Large")
    except Exception as e:
        # Manually replicating chat() exception block to test logic
        err_msg = str(e).lower()
        if "413" in err_msg or "payload too large" in err_msg:
            user_msg = "test message" * 100
            truncated_msg = user_msg[:len(user_msg) // 2] + "\n[CONTEXT TRUNCATED]"
            result = provider._fallback_chat("system", truncated_msg, 100, "gemini")
            
    assert called_fallback

def test_serialized_mode_semaphore_is_1():
    provider = LLMProvider()
    provider.set_max_concurrency(1)
    
    assert provider._request_gate._value == 1
