from typing import Any
from app.modules.notification_service.services.notification_service import (
    NotificationService,
)


class NotificationProjection:
    """
    EventBus subscriber that dispatches execution events to NotificationService.

    Registered at Celery task startup:
        event_bus.subscribe(NotificationProjection().handle)

    Future projections follow the same pattern:
        event_bus.subscribe(MetricsProjection().handle)
        event_bus.subscribe(WebSocketProjection().handle)
        event_bus.subscribe(AuditProjection().handle)
    """

    async def handle(self, event: Any) -> None:
        await NotificationService.process_event(event)
