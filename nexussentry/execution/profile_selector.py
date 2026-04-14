"""Execution profile selector between Architect and Builder pool."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutionProfile:
    mode: str
    builder_count: int
    reason: str


class ExecutionProfileSelector:
    """Validates and normalizes execution profile decisions from architect metadata."""

    MAX_BUILDERS = 5

    def resolve(self, plan: dict) -> ExecutionProfile:
        """Resolve mode/count from plan metadata without applying policy heuristics."""
        dispatch = plan.get("builder_dispatch", {}) or {}
        requested_mode = str(
            dispatch.get("execution_profile")
            or plan.get("execution_profile")
            or "sequential"
        ).lower()

        requested_builders = int(dispatch.get("builder_count", 1) or 1)
        requested_builders = max(1, min(self.MAX_BUILDERS, requested_builders))

        if requested_mode not in {"parallel", "sequential"}:
            requested_mode = "sequential"

        if requested_mode == "parallel":
            return ExecutionProfile(
                mode="parallel",
                builder_count=requested_builders,
                reason="Architect marked task parallelizable.",
            )

        return ExecutionProfile(
            mode="sequential",
            builder_count=1,
            reason="Architect requested ordered execution.",
        )
