# nexussentry/providers/llm_provider.py
"""
╔═══════════════════════════════════════════════════════════╗
║          Unified Multi-LLM Provider Layer                 ║
║                                                           ║
║  Routes AI calls to the BEST available provider:          ║
║    • Gemini   (Google)    — fast, cheap                   ║
║    • Groq     (Groq)      — fast reasoning                ║
║    • OpenRouter (multi)   — diverse model access           ║
║    • Anthropic (Claude)   — premium fallback              ║
║    • Mock                 — demo mode, no keys needed     ║
║                                                           ║
║  Auto-detects available API keys from .env                ║
║  Zero extra SDKs — uses raw HTTP for Groq/OpenRouter/Gemini║
╚═══════════════════════════════════════════════════════════╝
"""

import json
import os
import re
import sys
import time
import logging
from typing import Optional

logger = logging.getLogger("LLMProvider")


def _safe_print(text: str):
    """Print with safe encoding fallback for Windows cp1252 consoles."""
    try:
        print(text)
    except UnicodeEncodeError:
        safe = text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )
        print(safe)

# ── Provider Configuration ──
PROVIDER_CONFIG = {
    "gemini": {
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "gemini-2.0-flash",
        "label": "Google Gemini",
        "icon": "💎",
    },
    "groq": {
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "label": "Groq",
        "icon": "🧠",
    },
    "openrouter": {
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "google/gemini-2.0-flash-001",
        "label": "OpenRouter",
        "icon": "🌐",
    },
    "anthropic": {
        "env_key": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-4-20250514",
        "label": "Anthropic Claude",
        "icon": "🤖",
    },
}

# Priority order for auto-selection (cheapest/fastest first)
AUTO_PRIORITY = ["gemini", "groq", "openrouter", "anthropic"]

# Agent → preferred provider mapping
AGENT_PREFERENCES = {
    "scout": "gemini",       # Fast decomposition
    "architect": "openrouter",  # Diverse model access
    "critic": "groq",        # Fast reasoning
    "fixer": "auto",         # Whatever's available
    "guardian": "gemini",    # Speed for security scanning
}


class LLMProvider:
    """
    Unified interface for calling ANY LLM provider.
    Auto-detects available API keys and routes accordingly.
    Includes automatic fallback, retry, and mock mode.
    """

    def __init__(self):
        self._available = {}
        self._detect_providers()
        self._call_count = 0
        self._provider_usage = {}  # Track which provider was used how many times
        self._mock_call_counts = {}  # Track mock calls per agent for smart responses

    def _detect_providers(self):
        """Scan .env for available API keys."""
        for name, config in PROVIDER_CONFIG.items():
            key = os.getenv(config["env_key"], "").strip()
            # Backward compatibility for existing setups.
            if name == "groq" and not key:
                key = os.getenv("GROK_API_KEY", "").strip()
            # Filter out placeholder/dummy values
            is_placeholder = (
                not key
                or key.lower().endswith("_here")
                or key.lower().startswith("your_")
                or key == "YOUR_BOT_TOKEN"
                or len(key) < 10
            )
            if not is_placeholder:
                self._available[name] = key
                logger.info(f"  {config['label']}: Available")
            else:
                logger.debug(f"  {config['label']}: Not configured")

        if not self._available:
            logger.warning("  No LLM API keys found. Running in MOCK mode.")

    @property
    def available_providers(self) -> list[str]:
        """List of providers with valid API keys."""
        return list(self._available.keys())

    @property
    def mock_mode(self) -> bool:
        """True if no providers are available."""
        return len(self._available) == 0

    def get_provider_for_agent(self, agent_name: str) -> str:
        """Get the best provider for a specific agent role."""
        preferred = AGENT_PREFERENCES.get(agent_name.lower(), "auto")
        return self._resolve_provider(preferred)

    def _resolve_provider(self, prefer: str = "auto") -> str:
        """Resolve which provider to actually use."""
        if not self._available:
            return "mock"

        # If specific provider requested and available, use it
        if prefer != "auto" and prefer in self._available:
            return prefer

        # Auto: follow priority order
        for p in AUTO_PRIORITY:
            if p in self._available:
                return p

        return "mock"

    def chat(self, system: str, user_msg: str,
             max_tokens: int = 1000, prefer: str = "auto",
             agent_name: str = "") -> str:
        """
        Send a chat completion request to the best available LLM.

        Args:
            system: System prompt
            user_msg: User message
            max_tokens: Maximum tokens in response
            prefer: Preferred provider ("gemini", "groq", "openrouter", "anthropic", "auto")
            agent_name: Name of the calling agent (for smart routing)

        Returns:
            The LLM's response text
        """
        # Resolve provider
        if agent_name and prefer == "auto":
            provider = self.get_provider_for_agent(agent_name)
        else:
            provider = self._resolve_provider(prefer)

        self._call_count += 1
        self._provider_usage[provider] = self._provider_usage.get(provider, 0) + 1

        config = PROVIDER_CONFIG.get(provider, {})
        icon = config.get("icon", "🤖")
        label = config.get("label", provider)
        logger.info(f"  {icon} LLM call #{self._call_count} → {label}")

        # Route to correct provider
        try:
            if provider == "gemini":
                return self._call_gemini(system, user_msg, max_tokens)
            elif provider == "groq":
                return self._call_groq(system, user_msg, max_tokens)
            elif provider == "openrouter":
                return self._call_openrouter(system, user_msg, max_tokens)
            elif provider == "anthropic":
                return self._call_anthropic(system, user_msg, max_tokens)
            else:
                return self._mock_response(system, user_msg, agent_name=agent_name)
        except Exception as e:
            logger.warning(f"  ⚠️  {label} failed: {e}. Trying fallback...")
            return self._fallback_chat(system, user_msg, max_tokens, exclude=provider)

    def _fallback_chat(self, system: str, user_msg: str,
                       max_tokens: int, exclude: str) -> str:
        """Try other providers if primary fails."""
        for p in AUTO_PRIORITY:
            if p != exclude and p in self._available:
                try:
                    logger.info(f"  🔄 Fallback → {PROVIDER_CONFIG[p]['label']}")
                    if p == "gemini":
                        return self._call_gemini(system, user_msg, max_tokens)
                    elif p == "groq":
                        return self._call_groq(system, user_msg, max_tokens)
                    elif p == "openrouter":
                        return self._call_openrouter(system, user_msg, max_tokens)
                    elif p == "anthropic":
                        return self._call_anthropic(system, user_msg, max_tokens)
                except Exception as e:
                    logger.warning(f"  ⚠️  Fallback {p} also failed: {e}")
                    continue

        logger.warning("  ⚠️  All providers failed. Using mock response.")
        return self._mock_response(system, user_msg)

    # ═══════════════════════════════════════════
    # Provider Implementations
    # ═══════════════════════════════════════════

    def _call_gemini(self, system: str, user_msg: str, max_tokens: int) -> str:
        """Call Google Gemini API via REST."""
        import requests

        api_key = self._available["gemini"]
        model = PROVIDER_CONFIG["gemini"]["default_model"]
        url = f"{PROVIDER_CONFIG['gemini']['base_url']}/models/{model}:generateContent"

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": f"{system}\n\n{user_msg}"}]}
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.7,
            },
            "systemInstruction": {
                "parts": [{"text": system}]
            }
        }

        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json"
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        # Extract text from Gemini response
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise ValueError(f"Unexpected Gemini response: {json.dumps(data)[:200]}")

    def _call_groq(self, system: str, user_msg: str, max_tokens: int) -> str:
        """Call Groq API (OpenAI-compatible)."""
        import requests

        api_key = self._available["groq"]
        url = f"{PROVIDER_CONFIG['groq']['base_url']}/chat/completions"
        model = PROVIDER_CONFIG["groq"]["default_model"]

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        return data["choices"][0]["message"]["content"]

    def _call_openrouter(self, system: str, user_msg: str, max_tokens: int) -> str:
        """Call OpenRouter API (OpenAI-compatible, routes to many models)."""
        import requests

        api_key = self._available["openrouter"]
        url = f"{PROVIDER_CONFIG['openrouter']['base_url']}/chat/completions"
        model = PROVIDER_CONFIG["openrouter"]["default_model"]

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://nexussentry.dev",
            "X-Title": "NexusSentry",
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        return data["choices"][0]["message"]["content"]

    def _call_anthropic(self, system: str, user_msg: str, max_tokens: int) -> str:
        """Call Anthropic Claude API."""
        try:
            from anthropic import Anthropic
            client = Anthropic()
            resp = client.messages.create(
                model=PROVIDER_CONFIG["anthropic"]["default_model"],
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            return resp.content[0].text
        except ImportError:
            # If anthropic SDK not installed, use raw HTTP
            import requests

            api_key = self._available["anthropic"]
            url = f"{PROVIDER_CONFIG['anthropic']['base_url']}/messages"

            payload = {
                "model": PROVIDER_CONFIG["anthropic"]["default_model"],
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user_msg}],
            }

            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]

    def _mock_response(self, system: str, user_msg: str, agent_name: str = "") -> str:
        """
        Generate realistic mock responses for demo mode.
        Detects what kind of response is expected and returns appropriate JSON.
        """
        logger.info("  🎭 Using mock response (no API keys configured)")

        # Track mock calls per agent
        agent_key = agent_name or "unknown"
        self._mock_call_counts[agent_key] = self._mock_call_counts.get(agent_key, 0) + 1
        call_count = self._mock_call_counts[agent_key]

        # Detect what the agent expects based on system prompt keywords
        system_lower = system.lower()

        if "decompos" in system_lower or "scout" in system_lower:
            return json.dumps({
                "goal_summary": "Analyze and fix security vulnerabilities",
                "sub_tasks": [
                    {"id": 1, "task": "Scan codebase for SQL injection vulnerabilities in database query functions", "priority": "high"},
                    {"id": 2, "task": "Identify and patch XSS vulnerabilities in user input handling", "priority": "high"},
                    {"id": 3, "task": "Review authentication module for insecure password hashing", "priority": "medium"},
                ],
                "estimated_complexity": "complex"
            })

        elif "architect" in system_lower or "planner" in system_lower:
            # Different plan based on attempt
            if call_count == 1:
                return json.dumps({
                    "plan_summary": "Implement parameterized queries to prevent SQL injection",
                    "approach": "Replace all string concatenation in SQL queries with parameterized statements using '?' placeholders",
                    "files_to_read": ["db/queries.py", "models/user.py"],
                    "files_to_modify": ["db/queries.py", "api/endpoints.py"],
                    "commands_to_run": ["pytest tests/test_security.py", "bandit -r src/"],
                    "success_criteria": "All SQL queries use parameterized statements",
                    "risks": ["Existing query patterns may break if column names are dynamic"]
                })
            else:
                return json.dumps({
                    "plan_summary": "Implement strict parameterized queries with input validation (Revised)",
                    "approach": "Address critic feedback: add robust input validation before parameterized queries.",
                    "files_to_read": ["db/queries.py", "models/user.py"],
                    "files_to_modify": ["db/queries.py", "api/endpoints.py", "utils/validation.py"],
                    "commands_to_run": ["pytest tests/test_security.py", "bandit -r src/"],
                    "success_criteria": "All SQL queries use parameterized statements AND input validation is added",
                    "risks": ["More extensive file changes required"]
                })

        elif "critic" in system_lower or "reviewer" in system_lower:
            # SMART MOCK: Reject the first attempt to show the feedback loop
            if call_count == 1:
                return json.dumps({
                    "decision": "reject",
                    "score": 62,
                    "reasoning": "The implementation correctly uses parameterized queries, BUT completely misses input validation for edge cases.",
                    "issues_found": ["Critical: Missing input validation before DB queries", "Minor: Error messages leak table names"],
                    "suggestions": ["Add a strict validation layer before hitting the DB"]
                })
            else:
                return json.dumps({
                    "decision": "approve",
                    "score": 88,
                    "reasoning": "The revised implementation uses parameterized queries AND includes robust input validation. Security improved.",
                    "issues_found": ["Minor: Performance impact of extra validation layer (acceptable)"],
                    "suggestions": ["Add integration tests for edge cases with special characters"]
                })

        elif "security" in system_lower or "scanner" in system_lower:
            return json.dumps({"safe": True})

        else:
            return json.dumps({
                "success": True,
                "output": f"Processed: {user_msg[:100]}",
                "details": "Mock response — configure API keys for real LLM output"
            })

    # ═══════════════════════════════════════════
    # Stats & Info
    # ═══════════════════════════════════════════

    def stats(self) -> dict:
        """Return provider usage statistics."""
        return {
            "total_calls": self._call_count,
            "providers_available": self.available_providers,
            "provider_usage": self._provider_usage.copy(),
            "mock_mode": self.mock_mode,
        }

    def provider_summary_str(self) -> str:
        """Human-readable summary of available providers."""
        if self.mock_mode:
            return "MOCK MODE (no API keys configured)"

        parts = []
        for p in self.available_providers:
            cfg = PROVIDER_CONFIG[p]
            parts.append(f"{cfg['icon']} {cfg['label']}")
        return " | ".join(parts)

    def agent_routing_str(self) -> str:
        """Show which provider each agent will use."""
        lines = []
        for agent, preferred in AGENT_PREFERENCES.items():
            actual = self.get_provider_for_agent(agent)
            cfg = PROVIDER_CONFIG.get(actual, {})
            icon = cfg.get("icon", "*")
            label = cfg.get("label", "Mock")
            lines.append(f"    {icon} {agent.capitalize():12} -> {label}")
        return "\n".join(lines)


# ═══════════════════════════════════════════
# Global Singleton
# ═══════════════════════════════════════════

_global_provider: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    """Get the global LLM provider instance (singleton)."""
    global _global_provider
    if _global_provider is None:
        _global_provider = LLMProvider()
    return _global_provider
