"""
Agent G — Optimizer
━━━━━━━━━━━━━━━━━━━
Rewrites user prompts into clearer, implementation-ready goals.

Use case:
- Frontend "Optimize" button before running the swarm.
"""

import logging
from typing import Any

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from nexussentry.providers.llm_provider import get_provider

logger = logging.getLogger("Optimizer")

OPTIMIZER_SYSTEM = """You are The Optimizer — a silent prompt engineer embedded in an AI developer workspace.

Your sole job is to transform a lazy, vague, or incomplete developer prompt into a precise, implementation-ready task description that an AI coding agent can execute with minimal ambiguity.

## Your Behavior Rules
- PRESERVE the original intent exactly — never change what the developer wants, only how it's expressed
- INFER missing but obvious context (e.g. "add login" → assume JWT/session, existing codebase conventions)
- EXPAND shorthand naturally (e.g. "fix the bug" → describe the bug type and expected fix behavior if inferable)
- ADD structure only where it reduces ambiguity — don't pad or over-engineer simple requests
- USE technical language appropriate for software engineers and LLM agents
- If the prompt is already clear and detailed, make minimal changes

## What to Optimize For
- Clarity of the end goal
- Explicit acceptance criteria (what "done" looks like)
- Scope boundaries (what NOT to touch, if inferable)
- Relevant technical context (language, framework, pattern) if mentioned or strongly implied

## Output Format
Respond ONLY with valid JSON — no explanation, no markdown, no preamble:
{
  "optimized_prompt": "A single, complete, implementation-ready task description written for an AI coding agent",
  "extracted_requirements": [
    "Concrete requirement 1",
    "Concrete requirement 2"
  ],
  "assumptions": [
    "Assumption made due to missing context"
  ],
  "scope_notes": [
    "What is explicitly out of scope or should not be changed"
  ]
}

## Examples
Raw: "add dark mode"
Optimized: "Implement a dark/light theme toggle for the application. Add a theme context provider, persist user preference to localStorage, and apply CSS variables or Tailwind dark: classes consistently across all existing UI components. Default to system preference on first load."

Raw: "the search is slow fix it"
Optimized: "Investigate and optimize the search functionality for performance. Profile the current implementation to identify bottlenecks — likely causes include missing database indexes, unoptimized queries, or lack of debouncing on the frontend. Implement the appropriate fix without changing the search behavior or UI."
"""


class OptimizerAgent:
    """Turns rough user prompts into better execution prompts."""

    def optimize(self, user_prompt: str, tracer=None) -> dict[str, Any]:
        prompt = (user_prompt or "").strip()
        if not prompt:
            raise ValueError("Prompt cannot be empty")

        if tracer:
            tracer.log("Optimizer", "optimize_start", {"length": len(prompt)})

        provider = get_provider()
        selected_provider = provider.get_provider_for_agent("optimizer")

        user_msg = PromptTemplate.from_template(
            """Original prompt: {prompt}
            Rewrite this into a precise software-task prompt with explicit scope and clear deliverable expectations."""
        ).format(prompt=prompt)

        try:
            raw = provider.chat(
                system=OPTIMIZER_SYSTEM,
                user_msg=user_msg,
                max_tokens=900,
                agent_name="optimizer",
            )
            result = self._parse_json_response(raw)
        except Exception as exc:
            logger.warning("Optimizer fallback used: %s", exc)
            result = self._fallback(prompt, error=str(exc))

        actual_provider = provider.get_last_provider_used()

        result.setdefault("optimized_prompt", prompt)
        result.setdefault("extracted_requirements", [])
        result.setdefault("assumptions", [])
        result.setdefault("scope_notes", [])
        result.pop("original_prompt", None)
        result.pop("provider", None)
        result.pop("provider_selected", None)

        if tracer:
            tracer.log("Optimizer", "optimize_done", {
                "provider": actual_provider,
                "complexity": result.get("complexity", "medium"),
            })

        return result

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        parsed = JsonOutputParser().parse(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Could not parse optimizer JSON response: {text[:200]}")

    def _fallback(self, prompt: str, error: str = "") -> dict[str, Any]:
        return {
            "optimized_prompt": (
                "Build a production-ready implementation for the following request: "
                f"{prompt}. Include clear scope, files to modify, acceptance criteria, "
                "and edge-case handling."
            ),
            "extracted_requirements": [prompt],
            "assumptions": ["User expects runnable output with basic validation."],
            "scope_notes": [
                "Do not expand scope beyond the user request unless explicitly asked.",
            ],
            "fallback_reason": error[:300],
        }
