# nexussentry/hitl/telegram.py
"""
Human-in-the-Loop — Telegram Integration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sends approval requests to Telegram when the Critic escalates.
Gracefully falls back to console if Telegram isn't configured.
"""

import os
import sys
import logging

log = logging.getLogger("TelegramHITL")

# Graceful import — don't crash if python-telegram-bot isn't installed
try:
    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    log.debug("python-telegram-bot not installed. Telegram HITL will use console fallback.")


class TelegramHITL:
    """
    Human-in-the-loop via Telegram.
    Falls back to console input if Telegram is not configured.
    """

    def __init__(self):
        self.token = os.getenv("POCKETPAW_TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.bot = None

        if TELEGRAM_AVAILABLE and self.token and not self.token.endswith("_TOKEN"):
            try:
                self.bot = Bot(token=self.token)
            except Exception as e:
                log.warning(f"Failed to initialize Telegram bot: {e}")

    async def request_approval(self, message: str,
                                details: dict = {}) -> bool:
        """Send approval request. Returns True if approved."""
        if not self.bot or not self.chat_id or self.chat_id.endswith("_ID"):
            # Console fallback — works everywhere
            print(f"\n🚨 HITL REQUEST: {message}")
            if details:
                for k, v in details.items():
                    print(f"   • {k}: {v}")
            if not sys.stdin.isatty():
                print("  ⚠️ Non-interactive environment detected. Auto-rejecting HITL request.")
                return False
            ans = input("  Approve? (y/n): ").strip().lower()
            return ans == "y"

        # Send to Telegram
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍 Approve", callback_data="approve"),
            InlineKeyboardButton("👎 Reject",  callback_data="reject"),
        ]])

        detail_text = "\n".join(f"  • {k}: {v}" for k, v in details.items())
        full_msg = (
            f"🚨 *NexusSentry — Human Approval Required*\n\n"
            f"*Action:* {message}\n\n"
            f"{detail_text}\n\n"
            f"_Approve or reject below:_"
        )

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=full_msg,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            log.info("Approval request sent to Telegram. Waiting...")
        except Exception as e:
            print(f"  ⚠️  Telegram send failed: {e}")

        # Console fallback after sending notification
        if not sys.stdin.isatty():
            print("\n  ⚠️ Non-interactive environment detected. Auto-rejecting HITL request.")
            return False
        ans = input("\n  [Waiting for approval] (y/n): ").strip()
        return ans.lower() == "y"
