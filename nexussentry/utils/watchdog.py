# nexussentry/utils/watchdog.py
"""
Swarm Watchdog v3.0 — Formal Termination Guarantee
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Provides a hard, time-based termination guarantee independent
of the retry counter. Prevents runaway swarms in production.

As the deadline approaches, progressively reduces token budgets
to force faster, more concise agent responses.
"""

import time
import logging

logger = logging.getLogger("SwarmWatchdog")


class SwarmTimeoutError(Exception):
    """Raised when the swarm exceeds its maximum wall time."""
    pass


class SwarmWatchdog:
    """
    Hard time-based termination guarantee.
    Independent of retry counters — this is the absolute safety net.
    """

    def __init__(self, max_wall_time_seconds: int = 300):
        self.max_wall_time_seconds = max_wall_time_seconds
        self.start_time = time.time()
        self.deadline = self.start_time + max_wall_time_seconds
        self.completed_tasks = 0
        self.total_tasks = 0
        self._warned_75 = False
        self._warned_90 = False

    def check(self) -> bool:
        """
        Call at the start of every agent invocation.
        Raises SwarmTimeoutError if the deadline is exceeded.
        Prints warnings at 75% and 90% time usage.
        """
        now = time.time()
        elapsed = now - self.start_time
        ratio = elapsed / self.max_wall_time_seconds

        # Print progressive warnings
        if ratio >= 0.90 and not self._warned_90:
            self._warned_90 = True
            remaining = round(self.deadline - now, 1)
            logger.warning(
                f"⏰ Watchdog: 90% time used ({elapsed:.0f}s / {self.max_wall_time_seconds}s). "
                f"{remaining}s remaining. "
                f"Progress: {self.completed_tasks}/{self.total_tasks} tasks."
            )
            print(f"\n  ⏰ WATCHDOG WARNING: Only {remaining}s remaining!")

        elif ratio >= 0.75 and not self._warned_75:
            self._warned_75 = True
            remaining = round(self.deadline - now, 1)
            logger.info(
                f"⏰ Watchdog: 75% time used. {remaining}s remaining."
            )

        if now > self.deadline:
            raise SwarmTimeoutError(
                f"Swarm exceeded {self.max_wall_time_seconds}s wall time. "
                f"Processed {self.completed_tasks}/{self.total_tasks} tasks. "
                f"Total elapsed: {elapsed:.1f}s."
            )

        return True

    def get_remaining_seconds(self) -> float:
        """Get remaining time in seconds."""
        return max(0, self.deadline - time.time())

    def get_time_ratio(self) -> float:
        """Get ratio of elapsed time to total budget (0.0 to 1.0+)."""
        elapsed = time.time() - self.start_time
        return elapsed / self.max_wall_time_seconds

    def get_remaining_budget_tokens(self, base_budget: int) -> int:
        """
        As the deadline approaches, progressively reduce the token budget
        for remaining agents — forcing faster, more concise responses.

        At 100% time: budget = 30% of base (minimum floor)
        At 75% time: budget = 60% of base
        At 50% time: budget = 80% of base
        Below 50%: full budget
        """
        ratio = self.get_time_ratio()

        if ratio >= 0.90:
            scale = 0.30  # Emergency mode
        elif ratio >= 0.75:
            scale = 0.60
        elif ratio >= 0.50:
            scale = 0.80
        else:
            scale = 1.0

        adjusted = int(base_budget * scale)
        return max(200, adjusted)  # Minimum 200 tokens

    def record_task_complete(self):
        """Record that a task was completed."""
        self.completed_tasks += 1

    def set_total_tasks(self, total: int):
        """Set the total number of tasks for progress tracking."""
        self.total_tasks = total

    def summary(self) -> dict:
        """Return watchdog summary statistics."""
        elapsed = time.time() - self.start_time
        return {
            "max_wall_time_s": self.max_wall_time_seconds,
            "elapsed_s": round(elapsed, 1),
            "remaining_s": round(max(0, self.deadline - time.time()), 1),
            "time_ratio": round(self.get_time_ratio(), 3),
            "completed_tasks": self.completed_tasks,
            "total_tasks": self.total_tasks,
            "timed_out": time.time() > self.deadline,
        }
