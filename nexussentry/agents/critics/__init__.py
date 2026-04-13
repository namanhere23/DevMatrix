# nexussentry/agents/critics/__init__.py
"""
Specialist Judge Panel for MoA Debate.
Each judge evaluates independently then debates to consensus.
"""
from nexussentry.agents.critics.base_judge import BaseJudge
from nexussentry.agents.critics.correctness_judge import CorrectnessJudge
from nexussentry.agents.critics.security_judge import SecurityJudge
from nexussentry.agents.critics.architecture_judge import ArchitectureJudge

__all__ = ["BaseJudge", "CorrectnessJudge", "SecurityJudge", "ArchitectureJudge"]
