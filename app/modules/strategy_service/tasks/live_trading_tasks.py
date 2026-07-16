import asyncio
import logging

from app.celery_app import celery_app
from app.modules.strategy_service.utils.event_bus import EventBus
from app.modules.notification_service.notification_projection import (
    NotificationProjection,
)
from app.modules.strategy_service.tasks.live_runner import LiveTradingRunner

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="run_live_trading_task",
    max_retries=0,  # Never auto-retry live trading — explicit restart only
    acks_late=True,  # Acknowledge after completion, not on receipt
    reject_on_worker_lost=True,
)
def run_live_trading_task(self, session_id: str) -> None:
    """
    Thin Celery shell for Live/Paper trading.

    ONLY session_id is passed — no secrets in Celery queue.
    All configuration, credentials, and broker setup happen inside LiveTradingRunner.run().

    EventBus is constructed here (in the Celery process) and projections are
    registered before runner starts. Adding new projections never requires
    modifying LiveTradingRunner.

    Future projections:
        event_bus.subscribe(MetricsProjection().handle)
        event_bus.subscribe(WebSocketProjection().handle)
        event_bus.subscribe(AuditProjection().handle)
    """
    logger.info(f"[Celery] live_trading_task started for session={session_id}")

    # Build EventBus and register projections in Celery worker process
    event_bus = EventBus()
    event_bus.subscribe(NotificationProjection().handle)

    # Runner is Celery-agnostic — can be moved to any process manager later
    runner = LiveTradingRunner(session_id=session_id, event_bus=event_bus)

    try:
        asyncio.run(runner.run())
    except Exception as e:
        logger.exception(
            f"[Celery] live_trading_task failed for session={session_id}: {e}"
        )
        raise
    finally:
        logger.info(f"[Celery] live_trading_task finished for session={session_id}")
