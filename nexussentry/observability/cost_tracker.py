# nexussentry/observability/cost_tracker.py
"""
Cost Tracker v3.0 — Token usage and cost per provider per agent per session.
Standalone module for tracking and reporting LLM spend.
"""
import time
from collections import defaultdict
from typing import Dict


COST_PER_1K_TOKENS = {
    "gemini":      0.0004,
    "groq":        0.0008,
    "openrouter":  0.003,
    "huggingface": 0.0002,
    "anthropic":   0.015,
    "mock":        0.0,
}


class CostTracker:
    """Tracks token usage and cost per provider:agent combination."""

    def __init__(self):
        self.records = defaultdict(lambda: {"tokens": 0, "cost_usd": 0.0, "calls": 0})
        self.session_start = time.time()

    def record(self, provider: str, agent: str,
                prompt_tokens: int, completion_tokens: int):
        total_tokens = prompt_tokens + completion_tokens
        cost = (total_tokens / 1000) * COST_PER_1K_TOKENS.get(provider, 0.001)

        key = f"{provider}:{agent}"
        self.records[key]["tokens"] += total_tokens
        self.records[key]["cost_usd"] += cost
        self.records[key]["calls"] += 1

    def estimate_tokens(self, text: str) -> int:
        """Rough estimate: 1 token ~ 4 characters."""
        return len(text) // 4

    def summary(self) -> Dict:
        total_cost = sum(v["cost_usd"] for v in self.records.values())
        total_tokens = sum(v["tokens"] for v in self.records.values())
        by_provider = defaultdict(float)
        by_agent = defaultdict(float)
        for key, val in self.records.items():
            parts = key.split(":", 1)
            provider = parts[0]
            agent = parts[1] if len(parts) > 1 else "unknown"
            by_provider[provider] += val["cost_usd"]
            by_agent[agent] += val["cost_usd"]

        return {
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
            "total_calls": sum(v["calls"] for v in self.records.values()),
            "by_provider": dict(by_provider),
            "by_agent": dict(by_agent),
            "by_agent_provider": {k: dict(v) for k, v in self.records.items()},
            "session_duration_s": round(time.time() - self.session_start, 1),
        }

    def print_summary(self):
        """Print a formatted cost summary to console."""
        s = self.summary()
        print(f"\n  💰 COST SUMMARY")
        print(f"    Total cost: ${s['total_cost_usd']:.6f} USD")
        print(f"    Total tokens: {s['total_tokens']:,}")
        print(f"    Total calls: {s['total_calls']}")
        if s['by_provider']:
            print(f"    By provider: {s['by_provider']}")
