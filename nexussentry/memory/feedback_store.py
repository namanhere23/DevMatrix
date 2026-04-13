# nexussentry/memory/feedback_store.py
"""
Swarm Feedback Store — v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━
JSON-file-backed store for rejection history and HITL decisions.
Implements the RLAIF (Reinforcement Learning from AI Feedback) loop
WITHOUT vector databases or embeddings.

Every rejection, every HITL decision, every score becomes training signal.
"""

import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("FeedbackStore")

FEEDBACK_DIR = Path.home() / ".nexussentry" / "feedback"


class SwarmFeedbackStore:
    """
    Persists rejection history and HITL decisions to JSON files.
    Enables the Architect to learn from past failures using
    keyword-based similarity matching (no embeddings needed).
    """

    def __init__(self, feedback_dir: Optional[Path] = None):
        self.feedback_dir = feedback_dir or FEEDBACK_DIR
        self.failure_file = self.feedback_dir / "failures.jsonl"
        self.hitl_file = self.feedback_dir / "hitl_decisions.jsonl"
        self.feedback_dir.mkdir(parents=True, exist_ok=True)

    def record_rejection(self, task: str, plan: Dict[str, Any],
                         verdict: Dict[str, Any], attempt: int):
        """Store failed attempts — these teach the Architect what NOT to do."""
        score = verdict.get("score", 0)

        record = {
            "task": task,
            "plan_summary": plan.get("plan_summary", ""),
            "approach": plan.get("approach", ""),
            "score": score,
            "issues": verdict.get("issues_found", []),
            "suggestions": verdict.get("suggestions", []),
            "attempt": attempt,
            "timestamp": time.time(),
            "keywords": self._extract_keywords(task),
        }

        self._append_jsonl(self.failure_file, record)
        logger.debug(f"Recorded rejection: task='{task[:50]}...' score={score}")

    def record_hitl_decision(self, task: str, plan: Dict[str, Any],
                             human_decision: str, notes: str = ""):
        """
        Human decisions are gold-standard training data.
        When a human approves something the Critic rejected — that's a signal
        that the Critic's rubric is too strict in that dimension.
        When a human rejects something the Critic approved — that's a critical bug.
        """
        record = {
            "task": task,
            "plan_summary": plan.get("plan_summary", ""),
            "human_decision": human_decision,
            "human_notes": notes,
            "critic_was_wrong": (human_decision == "approve"),
            "timestamp": time.time(),
            "keywords": self._extract_keywords(task),
        }

        self._append_jsonl(self.hitl_file, record)
        logger.info(f"Recorded HITL decision: {human_decision} for '{task[:50]}...'")

    def get_negative_examples_for_task(self, task: str, max_results: int = 3) -> List[Dict[str, Any]]:
        """
        Architect receives not just what worked, but also what DIDN'T work.
        Uses keyword overlap for similarity (no embeddings needed).
        """
        task_keywords = self._extract_keywords(task)
        if not task_keywords:
            return []

        failures = self._read_jsonl(self.failure_file)
        if not failures:
            return []

        # Score each failure by keyword overlap with current task
        scored = []
        for failure in failures:
            failure_keywords = set(failure.get("keywords", []))
            if not failure_keywords:
                continue

            overlap = len(task_keywords & failure_keywords)
            union = len(task_keywords | failure_keywords)
            similarity = overlap / union if union > 0 else 0.0

            if similarity > 0.3:  # Minimum 30% keyword overlap
                scored.append({
                    "failed_approach": failure.get("approach", "N/A"),
                    "failure_reason": failure.get("issues", []),
                    "score": failure.get("score", 0),
                    "similarity": round(similarity, 2),
                })

        # Sort by similarity, return top N
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:max_results]

    def generate_critic_calibration_report(self) -> Dict[str, Any]:
        """
        Generate report: where is the Critic wrong?
        High false-rejection rate → Critic is too strict
        Any false-approval → Critical security issue
        """
        hitl_records = self._read_jsonl(self.hitl_file)
        if not hitl_records:
            return {
                "total_hitl_records": 0,
                "false_rejection_rate": 0.0,
                "recommendation": "Insufficient data",
            }

        # Filter to last 7 days
        cutoff = time.time() - (7 * 86400)
        recent = [r for r in hitl_records if r.get("timestamp", 0) > cutoff]

        if not recent:
            return {
                "total_hitl_records": len(hitl_records),
                "recent_records": 0,
                "false_rejection_rate": 0.0,
                "recommendation": "No recent HITL data",
            }

        false_rejections = [r for r in recent if r.get("critic_was_wrong")]

        rate = len(false_rejections) / max(len(recent), 1)
        recommendation = (
            "Raise score threshold — Critic is too strict"
            if rate > 0.3
            else "Calibration OK"
        )

        return {
            "total_hitl_records": len(hitl_records),
            "recent_records": len(recent),
            "false_rejection_rate": round(rate, 3),
            "false_rejections": len(false_rejections),
            "recommendation": recommendation,
        }

    def get_rejection_stats(self) -> Dict[str, Any]:
        """Get summary statistics about recorded rejections."""
        failures = self._read_jsonl(self.failure_file)
        if not failures:
            return {"total_rejections": 0}

        scores = [f.get("score", 0) for f in failures]
        all_issues = []
        for f in failures:
            all_issues.extend(f.get("issues", []))

        # Count issue frequency
        issue_counts: Dict[str, int] = {}
        for issue in all_issues:
            key = issue[:80]  # Truncate for grouping
            issue_counts[key] = issue_counts.get(key, 0) + 1

        # Top 5 most common issues
        top_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "total_rejections": len(failures),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "most_common_issues": top_issues,
        }

    def _extract_keywords(self, text: str) -> set:
        """Extract meaningful keywords from task text for similarity matching."""
        import re
        # Remove common stop words and extract meaningful words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "as", "into",
            "through", "during", "before", "after", "above", "below",
            "between", "out", "off", "over", "under", "again", "further",
            "then", "once", "and", "but", "or", "nor", "not", "so",
            "yet", "both", "either", "neither", "each", "every", "all",
            "any", "few", "more", "most", "other", "some", "such", "no",
            "only", "own", "same", "than", "too", "very", "just",
            "that", "this", "these", "those", "it", "its",
        }

        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        return {w for w in words if w not in stop_words}

    def _append_jsonl(self, filepath: Path, record: Dict[str, Any]):
        """Append a JSON record to a JSONL file."""
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError as e:
            logger.warning(f"Failed to write feedback: {e}")

    def _read_jsonl(self, filepath: Path) -> List[Dict[str, Any]]:
        """Read all records from a JSONL file."""
        if not filepath.exists():
            return []

        records = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError as e:
            logger.warning(f"Failed to read feedback: {e}")

        return records
