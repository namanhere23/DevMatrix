# nexussentry/utils/response_cache.py
"""
LLM Response Cache — Demo Reliability Layer

Caches every LLM API response to disk using MD5 hashing.
If the API is down during a live demo, cached responses are
served transparently. This is your safety net.

Features:
  - Cache versioning: bump CACHE_VERSION to invalidate stale entries
  - Session scoping: optional session_id to isolate cache per run
  - Agent exclusion: disable caching for specific agents (e.g. critic)

Usage:
    from nexussentry.utils.response_cache import ResponseCache
    cache = ResponseCache()
    result = cache.get_or_call(prompt, llm_function, *args, **kwargs)
"""

import json
import hashlib
import os
import logging
from pathlib import Path
from typing import Any, Callable, Optional, Set

logger = logging.getLogger("ResponseCache")

# Bump this version to invalidate all existing cache entries
CACHE_VERSION = "v2"

CACHE_DIR = Path(".demo_cache")


class ResponseCache:
    """
    MD5-keyed disk cache for LLM responses.
    Survives process restarts — perfect for demo reliability.
    """

    def __init__(self, cache_dir: str = ".demo_cache", enabled: bool = True,
                 session_id: Optional[str] = None,
                 excluded_agents: Optional[Set[str]] = None):
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        self.session_id = session_id or ""
        self.excluded_agents = excluded_agents or set()

        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, prompt: str, model: str = "") -> str:
        """Generate a deterministic, versioned cache key from prompt + model."""
        raw = f"{CACHE_VERSION}::{self.session_id}::{model}::{prompt}"
        return hashlib.md5(raw.encode()).hexdigest()

    def is_agent_excluded(self, agent_name: str) -> bool:
        """Check if an agent is excluded from caching."""
        return agent_name.lower() in {a.lower() for a in self.excluded_agents}

    def get(self, prompt: str, model: str = "") -> dict | None:
        """Try to get a cached response. Returns None on miss."""
        if not self.enabled:
            return None

        key = self._make_key(prompt, model)
        cache_file = self.cache_dir / f"{key}.json"

        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.hits += 1
                logger.info(f"[CACHE HIT] key={key[:8]}... (hits={self.hits})")
                return data
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def put(self, prompt: str, response: dict, model: str = ""):
        """Store a response in the cache."""
        if not self.enabled:
            return

        key = self._make_key(prompt, model)
        cache_file = self.cache_dir / f"{key}.json"

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(response, f, indent=2, default=str)
            logger.debug(f"[CACHE STORE] key={key[:8]}...")
            self._enforce_size_limit()
        except OSError as e:
            logger.warning(f"Cache write failed: {e}")

    def get_or_call(self, prompt: str, func: Callable, *args,
                    model: str = "", **kwargs) -> Any:
        """
        Check cache first; if miss, call func and cache the result.
        This is the main entry point for cache-aware LLM calls.
        """
        cached = self.get(prompt, model)
        if cached is not None:
            return cached

        self.misses += 1
        result = func(*args, **kwargs)

        # Cache it for next time
        if isinstance(result, dict):
            self.put(prompt, result, model)

        return result

    def _enforce_size_limit(self, max_files=1000):
        try:
            files = sorted(self.cache_dir.glob("*.json"), key=os.path.getmtime)
            if len(files) > max_files:
                for f in files[:-max_files]:
                    f.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Cache cleanup failed: {e}")

    def stats(self) -> dict:
        """Return cache hit/miss statistics."""
        total = self.hits + self.misses
        rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total": total,
            "hit_rate": f"{rate:.1f}%",
            "cache_dir": str(self.cache_dir),
            "cache_version": CACHE_VERSION,
        }


# Global singleton for easy import
_global_cache = None


def get_cache() -> ResponseCache:
    """Get the global response cache instance."""
    global _global_cache
    if _global_cache is None:
        enabled = os.getenv("NEXUS_CACHE_ENABLED", "true").lower() == "true"
        _global_cache = ResponseCache(enabled=enabled)
    return _global_cache
