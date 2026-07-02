import httpx
import logging
from typing import Optional
from app.config.settings import settings

logger = logging.getLogger(__name__)


class TelegramAdapter:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or getattr(settings, "TELEGRAM_CHAT_ID", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    async def send_message(self, message: str, chat_id: Optional[str] = None) -> bool:
        target_chat = chat_id or self.chat_id
        if not self.bot_token or not target_chat:
            logger.warning(
                "Telegram Bot Token or Chat ID not configured; skipping notification."
            )
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": target_chat, "text": message, "parse_mode": "HTML"}

        async with httpx.AsyncClient(timeout=10) as client:
            try:
                res = await client.post(url, json=payload)
                res.raise_for_status()
                logger.debug("Telegram alert sent successfully.")
                return True
            except Exception as e:
                logger.error(f"Failed to send Telegram alert: {e}")
                return False


# Global singleton
telegram_adapter = TelegramAdapter()
