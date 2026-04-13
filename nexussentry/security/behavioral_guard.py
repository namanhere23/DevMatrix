# nexussentry/security/behavioral_guard.py
"""
Behavioral Guardrail v3.0 — Runtime Anomaly Detection
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Detects anomalous agent behavior patterns that might indicate
prompt injection or model misbehavior mid-swarm.

Monitors the PATTERN of agent behavior over time, not individual outputs.
"""

import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger("BehavioralGuard")


class BehavioralGuardrail:
    """
    Detects anomalous agent behavior patterns across an entire swarm run.
    Called at the end of a swarm run to audit all agent outputs.
    """

    # Maximum output size before flagging as suspicious (50KB)
    MAX_OUTPUT_SIZE = 50_000

    # Maximum number of plans/outputs that can be identical before flagging
    MAX_IDENTICAL_PLANS = 2

    def audit_swarm_run(self, all_agent_outputs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Analyze all agent outputs from a swarm run for anomalies.
        Returns list of detected anomalies with severity and description.
        """
        anomalies = []

        # 1. Scope creep detection
        scope_creep = self._detect_scope_creep(all_agent_outputs)
        if scope_creep:
            anomalies.append({
                "type": "scope_creep",
                "severity": "warning",
                "description": scope_creep,
            })

        # 2. Complexity explosion
        complexity_issue = self._detect_complexity_explosion(all_agent_outputs)
        if complexity_issue:
            anomalies.append({
                "type": "complexity_explosion",
                "severity": "warning",
                "description": complexity_issue,
            })

        # 3. Copy-paste plans (model stuck in a loop)
        copy_paste = self._detect_copy_paste(all_agent_outputs)
        if copy_paste:
            anomalies.append({
                "type": "copy_paste_plans",
                "severity": "high",
                "description": copy_paste,
            })

        # 4. Unusually large outputs
        large_output = self._detect_large_outputs(all_agent_outputs)
        if large_output:
            anomalies.append({
                "type": "unusually_large_output",
                "severity": "info",
                "description": large_output,
            })

        if anomalies:
            logger.warning(f"Behavioral audit found {len(anomalies)} anomalies")
            for a in anomalies:
                logger.warning(f"  [{a['severity'].upper()}] {a['type']}: {a['description'][:100]}")

        return anomalies

    def _detect_scope_creep(self, outputs: List[Dict]) -> str:
        """Detect if later plans touch significantly more files than earlier ones."""
        file_counts = []
        for output in outputs:
            if "files_to_modify" in output:
                file_counts.append(len(output.get("files_to_modify", [])))
            elif "files_modified" in output:
                file_counts.append(len(output.get("files_modified", [])))

        if len(file_counts) >= 3:
            # Check if file count is growing exponentially
            first_half_avg = sum(file_counts[:len(file_counts)//2]) / max(1, len(file_counts)//2)
            second_half_avg = sum(file_counts[len(file_counts)//2:]) / max(1, len(file_counts) - len(file_counts)//2)

            if first_half_avg > 0 and second_half_avg > first_half_avg * 3:
                return (
                    f"Scope is expanding: early tasks avg {first_half_avg:.0f} files, "
                    f"later tasks avg {second_half_avg:.0f} files"
                )
        return ""

    def _detect_complexity_explosion(self, outputs: List[Dict]) -> str:
        """Detect if plan complexity is growing unreasonably."""
        plan_lengths = []
        for output in outputs:
            approach = output.get("approach", "")
            if approach:
                plan_lengths.append(len(approach))

        if len(plan_lengths) >= 3:
            first_avg = sum(plan_lengths[:2]) / 2
            last = plan_lengths[-1]
            if first_avg > 0 and last > first_avg * 5:
                return (
                    f"Plan complexity exploding: early plans ~{first_avg:.0f} chars, "
                    f"latest plan {last} chars"
                )
        return ""

    def _detect_copy_paste(self, outputs: List[Dict]) -> str:
        """Detect if the model is producing identical plans across attempts."""
        plan_summaries = []
        for output in outputs:
            summary = output.get("plan_summary", "")
            if summary:
                plan_summaries.append(summary.strip().lower())

        if not plan_summaries:
            return ""

        # Count duplicates
        from collections import Counter
        counts = Counter(plan_summaries)
        most_common = counts.most_common(1)
        if most_common and most_common[0][1] > self.MAX_IDENTICAL_PLANS:
            return (
                f"Identical plan repeated {most_common[0][1]} times: "
                f"'{most_common[0][0][:60]}...'"
            )
        return ""

    def _detect_large_outputs(self, outputs: List[Dict]) -> str:
        """Detect unusually large agent outputs."""
        large_files = []
        for output in outputs:
            for filename, content in output.get("generated_files", {}).items():
                size = len(content) if isinstance(content, str) else 0
                if size > self.MAX_OUTPUT_SIZE:
                    large_files.append(f"{filename} ({size:,} chars)")

        if large_files:
            return f"Unusually large outputs detected: {', '.join(large_files)}"
        return ""
