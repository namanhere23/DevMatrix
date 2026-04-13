# nexussentry/learning/feedback_store.py
"""
Re-export for v3.0 spec compatibility.
The actual implementation lives in nexussentry.memory.feedback_store.
"""
from nexussentry.memory.feedback_store import SwarmFeedbackStore as FeedbackStore

__all__ = ["FeedbackStore"]
