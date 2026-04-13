import os
import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def mock_env_vars():
    """Ensure tests run consistently regardless of local .env"""
    with patch.dict(os.environ, {
        "NEXUS_CACHE_ENABLED": "false",
    }):
        yield
