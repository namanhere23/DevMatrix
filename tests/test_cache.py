import os
import shutil
import pytest
from nexussentry.utils.response_cache import ResponseCache

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
