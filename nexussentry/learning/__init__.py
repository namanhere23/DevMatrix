# nexussentry/learning/__init__.py
"""Learning subsystem — re-exports from memory.feedback_store for spec compatibility."""
from nexussentry.memory.feedback_store import SwarmFeedbackStore as FeedbackStore

__all__ = ["FeedbackStore"]
