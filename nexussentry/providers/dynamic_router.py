# nexussentry/providers/dynamic_router.py
"""
Dynamic Router v3.0 — Cost-Aware, Latency-Intelligent Provider Selection
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Replaces static AGENT_PREFERENCES with multi-criteria provider selection.

Balances cost, latency, and historical quality using rolling-window metrics.
Inspired by Twilio's A2A intelligent routing implementation.
"""

import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

logger = logging.getLogger("DynamicRouter")


@dataclass
class ProviderMetrics:
    """Rolling window statistics per provider, updated after every call."""
    latencies_ms: deque = field(default_factory=lambda: deque(maxlen=20))
    quality_scores: deque = field(default_factory=lambda: deque(maxlen=20))
    cost_per_1k_tokens: float = 0.0
    error_rate: float = 0.0
    is_available: bool = True
    last_health_check: float = 0.0
    total_calls: int = 0
    total_errors: int = 0
    total_cost_usd: float = 0.0


class DynamicRouter:
    """
    Multi-objective routing that balances cost, latency, and quality.
    Falls back to static preferences when insufficient data is available.
    """

    # Cost per 1K tokens (input+output combined estimate)
    PROVIDER_COSTS = {
        "gemini":      0.0004,   # Gemini 2.0 Flash
        "groq":        0.0008,   # Llama 3.3 70B
        "openrouter":  0.003,    # GPT-4o equivalent
        "huggingface": 0.0002,   # Open-source models
        "mock":        0.0,
    }

    # Task complexity → cost budget per 1K tokens
    COMPLEXITY_BUDGETS = {
        "simple":   0.001,
        "medium":   0.005,
        "complex":  0.020,
        "critical": 0.100,   # No budget constraint — use best model
    }

    # Static fallback preferences (same as existing v2.5)
    STATIC_PREFERENCES = {
        "scout":       "gemini",
        "architect":   "openrouter",
        "critic":      "groq",
        "builder":     "gemini",
        "integrator":  "openrouter",
        "qa_verifier": "groq",
        "guardian":    "gemini",
    }

    def __init__(self):
        self.metrics: Dict[str, ProviderMetrics] = {}
        for provider in self.PROVIDER_COSTS:
            self.metrics[provider] = ProviderMetrics(
                cost_per_1k_tokens=self.PROVIDER_COSTS[provider]
            )
        self._min_data_points = 3  # Need at least 3 calls before dynamic routing

    def select_provider(
        self,
        agent_name: str,
        available_providers: list,
        disabled_providers: set = None,
        task_complexity: str = "medium",
        security_sensitive: bool = False,
    ) -> str:
        """
        Multi-criteria provider selection:
        1. Filter by cost budget for task complexity
        2. Filter by availability and error rate < 10%
        3. Among candidates, score by composite: 0.4*quality + 0.4*latency_inv + 0.2*cost_inv
        4. Return top scorer

        Falls back to static preferences when insufficient data.
        """
        if not available_providers:
            return "mock"

        disabled = disabled_providers or set()
        active = [p for p in available_providers if p not in disabled]

        if not active:
            return "mock"

        # Security-sensitive tasks: mandate the most capable model
        if security_sensitive:
            for pref in ["openrouter", "gemini"]:
                if pref in active:
                    return pref
            return active[0]

        # Check if we have enough data for dynamic routing
        has_enough_data = any(
            self.metrics[p].total_calls >= self._min_data_points
            for p in active if p in self.metrics
        )

        if not has_enough_data:
            # Fall back to static preferences
            static_pref = self.STATIC_PREFERENCES.get(agent_name.lower(), "auto")
            if static_pref != "auto" and static_pref in active:
                return static_pref
            return active[0]

        # Dynamic routing with multi-criteria scoring
        budget = self.COMPLEXITY_BUDGETS.get(task_complexity, 0.005)

        candidates = []
        for name in active:
            if name not in self.metrics:
                continue
            m = self.metrics[name]

            # Filter: cost within budget (skip for "critical" tasks)
            if task_complexity != "critical" and m.cost_per_1k_tokens > budget:
                continue

            # Filter: error rate < 10%
            if m.total_calls > 0 and (m.total_errors / m.total_calls) > 0.10:
                continue

            candidates.append(name)

        if not candidates:
            # All filtered out — use static fallback
            static_pref = self.STATIC_PREFERENCES.get(agent_name.lower(), "auto")
            if static_pref != "auto" and static_pref in active:
                return static_pref
            return active[0]

        # Score candidates
        scored = []
        for name in candidates:
            m = self.metrics[name]

            avg_quality = (
                statistics.mean(m.quality_scores)
                if m.quality_scores
                else 75  # Default assumption
            )
            avg_latency = (
                statistics.mean(m.latencies_ms)
                if m.latencies_ms
                else 2000  # Default 2s assumption
            )
            cost = m.cost_per_1k_tokens

            # Normalize and score (higher is better for all)
            quality_score = avg_quality / 100.0
            latency_score = 1.0 / (avg_latency / 1000.0 + 0.1)
            cost_score = 1.0 / (cost * 1000 + 0.001)

            composite = 0.4 * quality_score + 0.4 * latency_score + 0.2 * cost_score
            scored.append((name, composite))

        if not scored:
            return active[0]

        best = max(scored, key=lambda x: x[1])
        return best[0]

    def record_outcome(
        self,
        provider: str,
        latency_ms: float,
        quality_score: Optional[int] = None,
        error: bool = False,
        tokens_used: int = 0,
    ):
        """Called after every LLM call to update rolling metrics."""
        if provider not in self.metrics:
            self.metrics[provider] = ProviderMetrics(
                cost_per_1k_tokens=self.PROVIDER_COSTS.get(provider, 0.001)
            )

        m = self.metrics[provider]
        m.total_calls += 1
        m.latencies_ms.append(latency_ms)

        if error:
            m.total_errors += 1
            m.error_rate = 0.9 * m.error_rate + 0.1  # EWMA
        else:
            m.error_rate = 0.9 * m.error_rate  # Decay toward 0
            if quality_score is not None:
                m.quality_scores.append(quality_score)

        # Track cost
        if tokens_used > 0:
            cost = (tokens_used / 1000.0) * m.cost_per_1k_tokens
            m.total_cost_usd += cost

    def get_provider_stats(self) -> Dict[str, Dict]:
        """Return human-readable stats for each provider."""
        stats = {}
        for name, m in self.metrics.items():
            if m.total_calls == 0:
                continue
            stats[name] = {
                "total_calls": m.total_calls,
                "total_errors": m.total_errors,
                "error_rate": round(m.error_rate, 3),
                "avg_latency_ms": round(statistics.mean(m.latencies_ms), 1) if m.latencies_ms else 0,
                "avg_quality": round(statistics.mean(m.quality_scores), 1) if m.quality_scores else 0,
                "total_cost_usd": round(m.total_cost_usd, 4),
                "cost_per_1k": m.cost_per_1k_tokens,
            }
        return stats

    def get_estimated_session_cost(self) -> float:
        """Return total estimated cost for this session across all providers."""
        return sum(m.total_cost_usd for m in self.metrics.values())

    def get_routing_explanation(self, agent_name: str, available: list,
                                task_complexity: str = "medium") -> str:
        """Return a human-readable explanation of why a provider was selected."""
        selected = self.select_provider(agent_name, available, task_complexity=task_complexity)
        m = self.metrics.get(selected)
        if not m or m.total_calls < self._min_data_points:
            return f"{selected} (static preference for {agent_name})"

        avg_q = round(statistics.mean(m.quality_scores), 1) if m.quality_scores else "?"
        avg_l = round(statistics.mean(m.latencies_ms), 0) if m.latencies_ms else "?"
        return f"{selected} (quality={avg_q}, latency={avg_l}ms, cost=${m.cost_per_1k_tokens}/1k)"
