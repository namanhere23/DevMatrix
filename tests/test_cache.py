import os
import shutil
import pytest
from nexussentry.utils.response_cache import ResponseCache, CACHE_VERSION

def test_cache_put_get():
    # Use distinct test dir
    test_dir = ".pytest_cache_tests"
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
        
    cache = ResponseCache(cache_dir=test_dir)
    
    # Enable cache for test
    cache.enabled = True
    
    key = "test_key_123"
    data = {"some": "data", "id": 1}
    
    # Should not exist initially
    assert cache.get(key) is None
    
    # Store it
    cache.put(key, data, model="mock")
    
    # Should be retrievable
    cached_data = cache.get(key, model="mock")
    assert cached_data is not None
    assert cached_data["some"] == "data"
    assert cached_data["id"] == 1
    
    # Stats should reflect 1 hit and 1 put
    stats = cache.stats()
    assert stats["hits"] == 1
    
    # Cleanup
    shutil.rmtree(test_dir)

def test_cache_disabled():
    test_dir = ".pytest_cache_tests_disabled"
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
        
    cache = ResponseCache(cache_dir=test_dir)
    cache.enabled = False
    
    key = "test_disabled"
    data = {"hello": "world"}
    
    cache.put(key, data)
    assert cache.get(key) is None


def test_cache_version_in_key():
    """Cache keys should include the version to allow invalidation."""
    test_dir = ".pytest_cache_version_test"
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

    cache = ResponseCache(cache_dir=test_dir)
    cache.enabled = True

    key1 = cache._make_key("test prompt", "model1")

    # Key should be deterministic
    key2 = cache._make_key("test prompt", "model1")
    assert key1 == key2

    # Different prompts should produce different keys
    key3 = cache._make_key("different prompt", "model1")
    assert key1 != key3

    # Stats should include cache version
    stats = cache.stats()
    assert stats["cache_version"] == CACHE_VERSION

    # Cleanup
    shutil.rmtree(test_dir)


def test_cache_session_scoping():
    """Session-scoped caches should not share entries."""
    test_dir = ".pytest_cache_session_test"
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)

    cache_a = ResponseCache(cache_dir=test_dir, session_id="session_a")
    cache_b = ResponseCache(cache_dir=test_dir, session_id="session_b")
    cache_a.enabled = True
    cache_b.enabled = True

    # Store in session A
    cache_a.put("shared_key", {"source": "session_a"}, model="test")

    # Session B should NOT see session A's data
    result = cache_b.get("shared_key", model="test")
    assert result is None

    # Session A should see its own data
    result_a = cache_a.get("shared_key", model="test")
    assert result_a is not None
    assert result_a["source"] == "session_a"

    # Cleanup
    shutil.rmtree(test_dir)


def test_cache_agent_exclusion():
    """Excluded agents should be detectable."""
    cache = ResponseCache(excluded_agents={"critic", "guardian"})

    assert cache.is_agent_excluded("critic") is True
    assert cache.is_agent_excluded("Critic") is True  # case-insensitive
    assert cache.is_agent_excluded("guardian") is True
    assert cache.is_agent_excluded("scout") is False
    assert cache.is_agent_excluded("architect") is False
