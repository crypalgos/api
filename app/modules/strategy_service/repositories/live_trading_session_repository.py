import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.live_trading_session_model import (
    LiveTradingSession,
)

logger = logging.getLogger(__name__)


class LiveTradingSessionRepository(BaseRepository[LiveTradingSession]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, LiveTradingSession)

    async def get_by_strategy(self, strategy_id: str) -> List[LiveTradingSession]:
        """List all sessions for a strategy, newest first."""
        result = await self.session.execute(
            select(LiveTradingSession)
            .where(LiveTradingSession.strategy_id == strategy_id)
            .order_by(LiveTradingSession.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_session(
        self, strategy_id: str
    ) -> Optional[LiveTradingSession]:
        """Return the currently RUNNING or STARTING session for a strategy, if any."""
        result = await self.session.execute(
            select(LiveTradingSession)
            .where(
                LiveTradingSession.strategy_id == strategy_id,
                LiveTradingSession.status.in_(["STARTING", "RUNNING", "RECOVERING"]),
            )
            .limit(1)
        )
        return result.scalars().first()

    async def update_status(
        self,
        session_id: str,
        status: str,
        error_msg: Optional[str] = None,
        started_at: Optional[datetime] = None,
        stopped_at: Optional[datetime] = None,
    ) -> Optional[LiveTradingSession]:
        """Update lifecycle status and optional timestamps."""
        live_session = await self.get_by_id(session_id)
        if not live_session:
            return None

        live_session.status = status
        if error_msg is not None:
            live_session.error_msg = error_msg
        if started_at is not None:
            live_session.started_at = started_at
        if stopped_at is not None:
            live_session.stopped_at = stopped_at

        await self.session.commit()
        await self.session.refresh(live_session)
        return live_session

    async def update_heartbeat(
        self,
        session_id: str,
        heartbeat_at: datetime,
        last_processed_timestamp: Optional[int] = None,
    ) -> None:
        """Update runner heartbeat and optionally the last processed bar timestamp."""
        live_session = await self.get_by_id(session_id)
        if not live_session:
            return

        live_session.heartbeat_at = heartbeat_at
        if last_processed_timestamp is not None:
            live_session.last_processed_timestamp = last_processed_timestamp

        await self.session.commit()

    async def set_celery_task_id(self, session_id: str, celery_task_id: str) -> None:
        """Store Celery task ID after enqueue for tracking/revoke."""
        live_session = await self.get_by_id(session_id)
        if live_session:
            live_session.celery_task_id = celery_task_id
            await self.session.commit()
