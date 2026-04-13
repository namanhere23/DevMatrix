# nexussentry/security/constitutional/guard.py
"""
Re-export for v3.0 spec compatibility.
The actual implementation lives in nexussentry.security.constitutional_guard.
"""
from nexussentry.security.constitutional_guard import (
    ConstitutionalGuard,
    ConstitutionalVerdict,
    CONSTITUTION,
    HARD_STOPS,
)

__all__ = ["ConstitutionalGuard", "ConstitutionalVerdict", "CONSTITUTION", "HARD_STOPS"]
