import logging
from typing import Any, Callable, List

logger = logging.getLogger(__name__)


class EventBus:
    """
    Simple in-process async pub/sub bus.
    Projections register as subscribers via subscribe().
    The bus is injected into LiveTradingRunner — never constructed inside it.

    Future projections can be added without touching the runner:
        event_bus.subscribe(MetricsProjection().handle)
        event_bus.subscribe(WebSocketProjection().handle)
        event_bus.subscribe(AuditProjection().handle)
    """

    def __init__(self) -> None:
        self._subscribers: List[Callable] = []

    def subscribe(self, handler: Callable) -> None:
        """Register a projection handler."""
        self._subscribers.append(handler)

    async def publish(self, event: Any) -> None:
        """Publish an event to all registered subscribers."""
        for handler in self._subscribers:
            try:
                await handler(event)
            except Exception:
                logger.exception(
                    f"EventBus handler {handler.__qualname__} failed for event {type(event).__name__}"
                )
