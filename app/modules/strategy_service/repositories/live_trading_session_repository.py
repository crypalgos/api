import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.live_trading_session_model import (
    LiveTradingSession,
)
from app.modules.strategy_service.models.strategy_model import Strategy

logger = logging.getLogger(__name__)

# A Celery worker that's killed outright (pkill/SIGKILL/OOM) or never picks
# up the queued task at all never runs LiveTradingRunner.run()'s own
# except/finally status transition -- the session is left claiming
# STARTING/RUNNING/STOPPING forever with a heartbeat that stopped advancing.
# These thresholds are generous multiples of LiveTradingRunner's own
# HEARTBEAT_INTERVAL_SECS=10 / STOP_POLL_INTERVAL_SECS=5, to avoid flagging a
# session that's merely mid-bootstrap (ClickHouse warmup fetch, WS connect)
# or between two ordinary heartbeat ticks as dead.
STALE_HEARTBEAT_THRESHOLD_SECS = 30
STALE_STARTING_THRESHOLD_SECS = 60


class LiveTradingSessionRepository(BaseRepository[LiveTradingSession]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, LiveTradingSession)

    async def reap_if_stale(
        self, live_session: LiveTradingSession
    ) -> LiveTradingSession:
        """Crash-detection via heartbeat_at (see the model's own docstring for
        that field) -- every read path that surfaces a session's status to a
        caller must reconcile it here first, otherwise a session whose worker
        process died blocks new starts (get_active_session) and shows as
        permanently "in progress" in the UI forever."""
        if live_session.status not in ("STARTING", "RUNNING", "STOPPING"):
            return live_session

        now = datetime.now(timezone.utc)
        if live_session.status == "STARTING":
            # No heartbeat yet at this stage -- bootstrap hasn't gotten that
            # far. updated_at is the closest signal of "still alive".
            reference = live_session.updated_at
            threshold = STALE_STARTING_THRESHOLD_SECS
        else:
            reference = live_session.heartbeat_at or live_session.updated_at
            threshold = STALE_HEARTBEAT_THRESHOLD_SECS

        if reference is None or (now - reference).total_seconds() < threshold:
            return live_session

        live_session.status = "ERROR"
        live_session.error_msg = (
            "Worker heartbeat lost -- the process likely crashed or was killed."
        )
        live_session.stopped_at = now
        await self.session.commit()
        await self.session.refresh(live_session)
        return live_session

    async def get_by_id_with_relations(
        self, session_id: str
    ) -> Optional[LiveTradingSession]:
        """Eager-loads .strategy and .version — needed by RuntimeFactory.build(),
        which is called after this repository's AsyncSession has already closed
        (see LiveTradingRunner._bootstrap()); a detached ORM object can't lazy-
        load relationships, so they must be fetched up front."""
        result = await self.session.execute(
            select(LiveTradingSession)
            .options(
                selectinload(LiveTradingSession.strategy),
                selectinload(LiveTradingSession.version),
            )
            .where(LiveTradingSession.id == session_id)
        )
        return result.scalars().first()

    async def get_by_strategy(self, strategy_id: str) -> List[LiveTradingSession]:
        """List all sessions for a strategy, newest first."""
        result = await self.session.execute(
            select(LiveTradingSession)
            .where(LiveTradingSession.strategy_id == strategy_id)
            .order_by(LiveTradingSession.created_at.desc())
        )
        sessions = list(result.scalars().all())
        return [await self.reap_if_stale(s) for s in sessions]

    async def list_all_for_user(
        self,
        user_id: str,
        status: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> List[LiveTradingSession]:
        """Cross-strategy session list, scoped to the authenticated user via
        a join on Strategy.user_id — today's get_by_strategy() is
        single-strategy-scoped only, which the fleet page needs to see past."""
        stmt = (
            select(LiveTradingSession)
            .join(Strategy, LiveTradingSession.strategy_id == Strategy.id)
            .where(Strategy.user_id == user_id)
            .order_by(LiveTradingSession.created_at.desc())
        )
        if status:
            stmt = stmt.where(LiveTradingSession.status == status.upper())
        if mode:
            stmt = stmt.where(LiveTradingSession.mode == mode.upper())

        result = await self.session.execute(stmt)
        sessions = list(result.scalars().all())
        return [await self.reap_if_stale(s) for s in sessions]

    async def get_active_session(
        self, strategy_id: str
    ) -> Optional[LiveTradingSession]:
        """Return the currently RUNNING or STARTING session for a strategy, if
        any -- reaped first, so a session whose worker died doesn't block a
        new one from starting forever."""
        result = await self.session.execute(
            select(LiveTradingSession)
            .where(
                LiveTradingSession.strategy_id == strategy_id,
                LiveTradingSession.status.in_(["STARTING", "RUNNING", "RECOVERING"]),
            )
            .limit(1)
        )
        live_session = result.scalars().first()
        if live_session is None:
            return None
        live_session = await self.reap_if_stale(live_session)
        return (
            live_session
            if live_session.status in ("STARTING", "RUNNING", "RECOVERING")
            else None
        )

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
