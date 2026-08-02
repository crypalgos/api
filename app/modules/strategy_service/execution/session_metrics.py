from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class SessionMetrics:
    """In-memory per-TradingRuntime counters, updated by
    EventPublisher.record_metrics() from each tick's event batch. Surfaced
    through the existing heartbeat write (LiveTradingRunner._update_heartbeat)
    so it's visible without new plumbing.
    """

    bars_processed: int = 0
    orders_sent: int = 0
    orders_failed: int = 0
    risk_blocks: int = 0
    last_bar_at: Optional[datetime] = None
    ws_clients_connected: int = 0

    def record_bar(self) -> None:
        self.bars_processed += 1
        self.last_bar_at = datetime.now(timezone.utc)

    def record_event_counts(self, event_type_names: list[str]) -> None:
        for name in event_type_names:
            if name in ("OrderFilledEvent",):
                self.orders_sent += 1
            elif name in ("OrderRejectedEvent",):
                self.orders_failed += 1
            elif name == "RiskViolationEvent":
                self.risk_blocks += 1

    def to_dict(self) -> dict:
        return {
            "bars_processed": self.bars_processed,
            "orders_sent": self.orders_sent,
            "orders_failed": self.orders_failed,
            "risk_blocks": self.risk_blocks,
            "last_bar_at": self.last_bar_at.isoformat() if self.last_bar_at else None,
            "ws_clients_connected": self.ws_clients_connected,
        }
