"""
User Permission Gate
━━━━━━━━━━━━━━━━━━━━
Simple local user permission flow for retry decisions.
No Telegram integration.
"""

import sys


class UserPermissionGate:
    """Ask the user whether to retry or return current output."""

    async def request_retry_permission(self, message: str, details: dict | None = None) -> bool:
        print(f"\n⚖️  USER DECISION REQUIRED: {message}")
        if details:
            for k, v in details.items():
                print(f"   • {k}: {v}")
        print("   • y = retry one more time")
        print("   • n = return output generated so far")

        if not sys.stdin.isatty():
            print("  ⚠️ Non-interactive environment detected. Defaulting to 'n'.")
            return False

        ans = input("  Retry again? (y/n): ").strip().lower()
        return ans == "y"
