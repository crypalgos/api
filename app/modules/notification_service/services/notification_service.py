import logging
import asyncio
from typing import Any
from crypalgos_core.engine.context import ExecutionMode
from app.modules.notification_service.utils.telegram_adapter import telegram_adapter

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    async def process_event(event: Any) -> None:
        """Processes execution events and dispatches user notifications for LIVE/PAPER runs."""
        context = getattr(event, "context", None)
        if not context:
            return

        # Guard: Only notify on LIVE or PAPER execution modes
        if context.mode not in (ExecutionMode.LIVE, ExecutionMode.PAPER):
            return

        # Fetch notification preference
        try:
            from app.modules.user_service.services.credential_service import (
                credential_service,
            )

            prefs = await credential_service.get_notification_preference(
                context.user_id
            )
            if not prefs or not prefs.get("telegram_enabled"):
                return

            # Check mode level alerts
            if context.mode == ExecutionMode.PAPER and not prefs.get("paper_alerts"):
                return
            if context.mode == ExecutionMode.LIVE and not prefs.get("live_alerts"):
                return

            chat_id = prefs.get("telegram_chat_id")
        except Exception as e:
            logger.error(f"Error checking user notification preferences: {e}")
            return

        event_name = event.__class__.__name__
        msg = ""

        # Format message based on event type
        if event_name == "OrderFilledEvent":
            msg = (
                f"🔔 <b>Trade Executed ({context.mode.name})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Strategy:</b> {context.strategy_run_id}\n"
                f"<b>Symbol:</b> {event.symbol_id}\n"
                f"<b>Action:</b> {event.side}\n"
                f"<b>Price:</b> {event.fill_price:.2f}\n"
                f"<b>Quantity:</b> {event.fill_quantity}\n"
                f"<b>Order ID:</b> <code>{event.order_id}</code>"
            )
        elif event_name == "PositionOpenedEvent":
            msg = (
                f"🚀 <b>Position Opened ({context.mode.name})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Strategy:</b> {context.strategy_run_id}\n"
                f"<b>Symbol:</b> {event.symbol_id}\n"
                f"<b>Side:</b> {event.side}\n"
                f"<b>Entry Price:</b> {event.entry_price:.2f}"
            )
        elif event_name == "PositionClosedEvent":
            msg = (
                f"🏁 <b>Position Closed ({context.mode.name})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Strategy:</b> {context.strategy_run_id}\n"
                f"<b>Symbol:</b> {event.symbol_id}\n"
                f"<b>Exit Price:</b> {event.exit_price:.2f}\n"
                f"<b>Realized PnL:</b> {event.realized_pnl:.2f}"
            )

        if msg:
            await telegram_adapter.send_message(msg, chat_id=chat_id)
