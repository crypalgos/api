import logging
from typing import Any
from crypalgos_core.events import Event
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

        # Prepare payload dictionary
        payload = {}
        for key, val in event.__dict__.items():
            if key == "context":
                # Convert context object to dict format
                payload["context"] = {
                    "strategy_run_id": val.strategy_run_id,
                    "user_id": val.user_id,
                    "mode": (
                        val.mode.name if hasattr(val.mode, "name") else str(val.mode)
                    ),
                    "workspace_id": val.workspace_id,
                    "started_at": val.started_at,
                }
            elif hasattr(val, "name"):
                # Enum conversions
                payload[key] = val.name
            else:
                payload[key] = val

        async with AsyncSessionLocal() as session:
            try:
                db_event = StrategyEvent(
                    strategy_run_id=run_id,
                    event_type=event.__class__.__name__,
                    event_version=getattr(event, "event_version", "1.0"),
                    payload=payload,
                )
                session.add(db_event)
                await session.commit()
                logger.debug(
                    f"Successfully persisted event {db_event.event_type} for run {run_id}"
                )
            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to persist event to DB: {e}")
