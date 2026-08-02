import asyncio
import logging

from app.celery_app import celery_app
from app.modules.notification_service.notification_projection import (
    NotificationProjection,
)
from app.modules.strategy_service.tasks.live_runner import LiveTradingRunner
from app.modules.strategy_service.utils.event_bus import EventBus

logger = logging.getLogger(__name__)


async def _run_with_database_cleanup(runner: LiveTradingRunner) -> None:
    """Run one live session and close async DB connections on its own loop."""
    from app.db.connect_db import engine as db_engine

    try:
        await runner.run()
    finally:
        # `AsyncEngine.sync_engine.dispose()` attempts to close asyncpg
        # connections without SQLAlchemy's greenlet bridge, causing
        # MissingGreenlet. Awaiting this before asyncio.run() closes its loop
        # releases this task's pool safely and leaves no prior-loop connection
        # for the next prefork task to inherit.
        await db_engine.dispose()


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

    # Runner is Celery-agnostic — can be moved to any process manager later.
    # Its async DB pool is disposed inside this same asyncio.run() invocation,
    # avoiding cross-loop asyncpg cleanup between prefork tasks.
    runner = LiveTradingRunner(session_id=session_id, event_bus=event_bus)

    try:
        asyncio.run(_run_with_database_cleanup(runner))
    except Exception as e:
        logger.exception(
            f"[Celery] live_trading_task failed for session={session_id}: {e}"
        )
        raise
    finally:
        logger.info(f"[Celery] live_trading_task finished for session={session_id}")
