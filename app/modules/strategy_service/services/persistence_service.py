import logging
from typing import Any

from app.db.connect_db import AsyncSessionLocal
from app.modules.strategy_service.models.strategy_event_model import StrategyEvent

logger = logging.getLogger(__name__)


class PersistenceService:
    @staticmethod
    async def persist_event(event: Any) -> None:
        """Converts an EngineEvent (OrderFilledEvent, etc.) to StrategyEvent model and saves to DB."""
        run_id = None
        context = getattr(event, "context", None)
        if context:
            run_id = getattr(context, "strategy_run_id", None)

        if not run_id:
            logger.debug(
                f"Event {event} missing strategy_run_id context; skipping persistence."
            )
            return

        # EngineEvent subclasses are `@dataclass(slots=True, ...)` — instances
        # have no `__dict__`, so building the payload from `event.__dict__`
        # (as this used to) raises AttributeError on every call. That's silent
        # here because the caller wraps this in an unawaited asyncio.create_task.
        # to_dict() is the event's own supported serialization (already used
        # by app/modules/strategy_service/execution/event_publisher.py).
        d = event.to_dict()

        async with AsyncSessionLocal() as session:
            try:
                db_event = StrategyEvent(
                    strategy_run_id=run_id,
                    event_type=d["type"],
                    event_version=getattr(event, "event_version", "1.0"),
                    payload=d["payload"],
                )
                session.add(db_event)
                await session.commit()
                logger.debug(
                    f"Successfully persisted event {db_event.event_type} for run {run_id}"
                )
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to persist event to DB: {e}")
