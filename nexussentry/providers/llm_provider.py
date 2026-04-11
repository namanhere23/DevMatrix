# nexussentry/providers/llm_provider.py
"""
╔═══════════════════════════════════════════════════════════╗
║          Unified Multi-LLM Provider Layer                 ║
║                                                           ║
║  Routes AI calls to the BEST available provider:          ║
║    • Gemini   (Google)    — fast, cheap                   ║
║    • Groq     (Groq)      — fast reasoning                ║
║    • OpenRouter (multi)   — diverse model access           ║
║    • Hugging Face         — fast fallback                  ║
║    • Mock                 — demo mode, no keys needed     ║
║                                                           ║
║  Auto-detects available API keys from .env                ║
║  Zero extra SDKs — uses raw HTTP for Groq/OpenRouter/Gemini║
╚═══════════════════════════════════════════════════════════╝
"""

import json
import os
import sys
import logging
import threading
from typing import Any, Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
from langchain_openai import ChatOpenAI

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
        "default_model": "gemini-2.5-flash",
        "label": "Google Gemini",
        "icon": "💎",
    },
    "groq": {
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "groq/compound",
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
    "huggingface": {
        "env_key": "HUGGINGFACE_API_KEY",
        "base_url": "https://router.huggingface.co/v1",
        "default_model": "Qwen/Qwen2.5-7B-Instruct",
        "label": "Hugging Face",
        "icon": "🤖",
    },
}

# Priority order for auto-selection (cheapest/fastest first)
AUTO_PRIORITY = ["gemini", "groq", "openrouter", "huggingface"]

# Agent → preferred provider mapping
AGENT_PREFERENCES = {
    "scout": "gemini",       # Fast decomposition
    "architect": "openrouter",  # Diverse model access
    "critic": "groq",        # Fast reasoning
    "builder": "auto",       # Execution layer
    "integrator": "openrouter",  # Synthesis and merge
    "qa_verifier": "groq",   # Fast validation reasoning
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
        self._disabled_providers: set[str] = set()
        self._provider_failures: dict[str, int] = {}
        max_concurrency = max(1, int(os.getenv("NEXUS_LLM_MAX_CONCURRENCY", "2")))
        self._request_gate = threading.BoundedSemaphore(value=max_concurrency)

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
        if prefer != "auto" and prefer in self._available and prefer not in self._disabled_providers:
            return prefer

        # Auto: follow priority order
        for p in AUTO_PRIORITY:
            if p in self._available and p not in self._disabled_providers:
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
            prefer: Preferred provider ("gemini", "groq", "openrouter", "huggingface", "auto")
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
            if provider != "mock":
                with self._request_gate:
                    return self._call_with_langchain(provider, system, user_msg, max_tokens)

            if provider == "gemini":
                return self._call_gemini(system, user_msg, max_tokens)
            elif provider == "groq":
                return self._call_groq(system, user_msg, max_tokens)
            elif provider == "openrouter":
                return self._call_openrouter(system, user_msg, max_tokens)
            elif provider == "huggingface":
                return self._call_huggingface(system, user_msg, max_tokens)
            else:
                return self._mock_response(system, user_msg, agent_name=agent_name)
        except Exception as e:
            logger.warning(f"  ⚠️  {label} failed: {e}. Trying fallback...")
            self._maybe_disable_provider(provider, e)
            return self._fallback_chat(system, user_msg, max_tokens, exclude=provider)

    def _fallback_chat(self, system: str, user_msg: str,
                       max_tokens: int, exclude: str) -> str:
        """Try other providers if primary fails."""
        for p in AUTO_PRIORITY:
            if p != exclude and p in self._available and p not in self._disabled_providers:
                try:
                    logger.info(f"  🔄 Fallback → {PROVIDER_CONFIG[p]['label']}")
                    with self._request_gate:
                        return self._call_with_langchain(p, system, user_msg, max_tokens)
                except Exception as e:
                    logger.warning(f"  ⚠️  Fallback {p} also failed: {e}")
                    self._maybe_disable_provider(p, e)
                    continue

        logger.warning("  ⚠️  All providers failed. Using mock response.")
        return self._mock_response(system, user_msg)

    # ═══════════════════════════════════════════
    # Provider Implementations
    # ═══════════════════════════════════════════

    def _build_chat_messages(self, system: str, user_msg: str) -> list[Any]:
        """Build messages with ChatPromptTemplate."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system}"),
            ("human", "{user_msg}"),
        ])
        return prompt.format_messages(system=system, user_msg=user_msg)

    def _extract_text_content(self, content: Any) -> str:
        """Normalize LangChain model output content into plain text."""
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
            merged = "\n".join(part for part in parts if part).strip()
            if merged:
                return merged

        return str(content)

    def _call_with_langchain(self, provider: str, system: str, user_msg: str, max_tokens: int) -> str:
        """Use LangChain chat models for provider invocation."""

        config = PROVIDER_CONFIG[provider]
        model = config["default_model"]
        api_key = self._available[provider]
        messages = self._build_chat_messages(system, user_msg)

        if provider == "gemini":
            chat_model = ChatGoogleGenerativeAI(
                model=model,
                google_api_key=api_key,
                temperature=0.7,
                max_output_tokens=max_tokens,
            )
        elif provider == "huggingface":
            if not os.getenv("HUGGINGFACEHUB_API_TOKEN"):
                os.environ["HUGGINGFACEHUB_API_TOKEN"] = api_key

            hf_llm = HuggingFaceEndpoint(
                repo_id=model,
                task="text-generation",
                provider="auto",
                max_new_tokens=max_tokens,
                huggingfacehub_api_token=api_key,
            )
            chat_model = ChatHuggingFace(llm=hf_llm)
        else:
            chat_model = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=config["base_url"],
                temperature=0.7,
                max_tokens=max_tokens,
                timeout=60,
            )

        response = chat_model.invoke(messages)
        return self._extract_text_content(getattr(response, "content", response))

    def _maybe_disable_provider(self, provider: str, err: Exception):
        """Disable providers with hard quota/auth failures for the remainder of this run."""
        msg = str(err).lower()
        self._provider_failures[provider] = self._provider_failures.get(provider, 0) + 1

        is_rate_hard_limit = (
            "tokens per day" in msg
            or "tpd" in msg
            or "requests per minute" in msg
            or "rpm" in msg
            or "rate_limit_exceeded" in msg
        )
        is_fatal = (
            "402" in msg
            or "payment required" in msg
            or "401" in msg
            or "unauthorized" in msg
            or "invalid api key" in msg
            or "insufficient" in msg
            or (is_rate_hard_limit and self._provider_failures.get(provider, 0) >= 3)
        )
        if is_fatal and provider in self._available and provider not in self._disabled_providers:
            self._disabled_providers.add(provider)
            logger.warning(f"  ⛔ Disabling provider '{provider}' for this run due to hard failure.")

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

    def _call_huggingface(self, system: str, user_msg: str, max_tokens: int) -> str:
        """Call Hugging Face Inference Router API (OpenAI-compatible)."""
        import requests

        api_key = self._available["huggingface"]
        url = f"{PROVIDER_CONFIG['huggingface']['base_url']}/chat/completions"
        model = PROVIDER_CONFIG["huggingface"]["default_model"]

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
            goal = user_msg.strip().splitlines()[0][:120] or "Build requested feature"
            return json.dumps({
                "goal_summary": goal,
                "sub_tasks": [
                    {"id": 1, "task": f"Define scope and requirements for: {goal}", "priority": "high", "depends_on": []},
                    {"id": 2, "task": "Create core project/file structure and baseline implementation", "priority": "high", "depends_on": [1]},
                    {"id": 3, "task": "Implement main feature logic and user interaction flow", "priority": "high", "depends_on": [2]},
                    {"id": 4, "task": "Polish behavior, validate edge cases, and finalize output", "priority": "medium", "depends_on": [3]},
                ],
                "estimated_complexity": "medium"
            })

        elif "architect" in system_lower or "planner" in system_lower:
            task_hint = user_msg.strip().splitlines()[0].replace("Sub-task:", "").strip()
            files = ["index.html", "game.js", "styles.css"]
            if "python" in user_msg.lower() or "api" in user_msg.lower():
                files.append("main.py")
            return json.dumps({
                "plan_summary": task_hint or "Implement requested feature",
                "approach": "Deliver complete, production-ready files with coherent integration and edge-case handling.",
                "files_to_read": [],
                "files_to_modify": files,
                "commands_to_run": ["python -m pytest -q"],
                "success_criteria": "Feature works end-to-end without placeholder code.",
                "risks": ["Provider fallback mode may reduce depth; verify generated artifacts."]
            })

        elif "critic" in system_lower or "reviewer" in system_lower:
            # SMART MOCK: Reject the first attempt to show the feedback loop
            if call_count == 1:
                return json.dumps({
                    "decision": "reject",
                    "score": 68,
                    "reasoning": "Core direction is acceptable, but generated output lacks completeness and integration detail.",
                    "issues_found": ["Incomplete implementation coverage", "Missing robustness for edge cases"],
                    "suggestions": ["Return full file-level implementations with integrated behavior"]
                })
            else:
                return json.dumps({
                    "decision": "approve",
                    "score": 87,
                    "reasoning": "Implementation is coherent and complete enough for simulated execution context.",
                    "issues_found": [],
                    "suggestions": ["Add focused runtime tests for gameplay interactions"]
                })

        elif "qa verifier" in system_lower or "qa" in system_lower:
            return json.dumps({
                "decision": "pass",
                "score": 85,
                "issues_found": [],
                "suggestions": ["Run a quick manual smoke test on generated artifacts"],
                "summary": "Fallback QA accepted generated outputs in degraded provider mode."
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
