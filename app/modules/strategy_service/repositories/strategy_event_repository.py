import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.base_repositories import BaseRepository
from app.modules.strategy_service.models.strategy_event_model import StrategyEvent

logger = logging.getLogger(__name__)


class StrategyEventRepository(BaseRepository[StrategyEvent]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, StrategyEvent)

    async def list_for_session(
        self,
        session_id: str,
        since: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[StrategyEvent]:
        """REST scrollback for GET /live-sessions/{id}/timeline.

        `since` (reconnect case): the caller already has everything up to a
        known point and wants just what's new -- ascending + limit from that
        cutoff is correct as a forward scan.

        No `since` (initial snapshot -- WS connect, or REST first page): the
        caller wants recent context, not the session's oldest events. Fixed
        bug: this used to be ORDER BY created_at ASC LIMIT N unconditionally,
        which returns the OLDEST N rows -- for any session with more than N
        events total, the initial snapshot got stuck showing only the
        beginning forever, never advancing to recent activity (made acutely
        visible once RuntimeFactory started persisting ~500 warmup candles
        at bootstrap: the very first page was entirely warmup history with
        no room left for anything live). Fetch the most recent `limit` rows
        instead, then restore chronological order for display.
        """
        if since is not None:
            stmt = (
                select(StrategyEvent)
                .where(StrategyEvent.session_id == session_id, StrategyEvent.created_at > since)
                .order_by(StrategyEvent.created_at.asc())
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())

        stmt = (
            select(StrategyEvent)
            .where(StrategyEvent.session_id == session_id)
            .order_by(StrategyEvent.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(reversed(result.scalars().all()))
