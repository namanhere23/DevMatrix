# nexussentry/routing/__init__.py
"""Routing subsystem — re-exports from providers.dynamic_router for spec compatibility."""
from nexussentry.providers.dynamic_router import DynamicRouter

__all__ = ["DynamicRouter"]
